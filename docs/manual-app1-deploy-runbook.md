# Runbook: ручной деплой только `app1` / `app-service`

Документ для AI-агентов и DevOps-операторов. Описывает процедуру безопасного
деплоя и перезапуска только основного сервиса приложения (`app1`) на целевой VM
или на другой машине с аналогичной `docker compose`-структурой.

Связанные документы:

- [`manual-infra-and-rmq-deploy-runbook.md`](manual-infra-and-rmq-deploy-runbook.md) — регламент деплоя инфраструктуры RabbitMQ, межсервисных сетей, definitions и reverse-proxy.
- [`deploy-plan.md`](deploy-plan.md) — общий план архитектуры и деплоя.
- [`deploy-plan.md` §6.2](deploy-plan.md#62-env-и-конфигурация-app1-без-локального-билда) — почему `app-service/.env` прокидывается через `env_file`.
- [`deploy-plan.md` §6.4](deploy-plan.md#64-ручной-деплой-на-vm-текущий-флоу-по-сервисам) — общий ручной флоу по сервисам.
- [`rabbitmq-acl-recovery.md`](rabbitmq-acl-recovery.md) — регламент восстановления динамических ACL устройств.

---

## 0. Обязательное уточнение перед любым деплоем

Перед SSH-подключением и изменениями агент/оператор обязан явно определить режим операции:

1. **Основной сценарий (Default): Сборка напрямую на целевом хосте** — синхронизировать
   код на сервере, собрать образ локально через `docker compose build app1` и
   пересоздать контейнер `docker compose up -d --no-deps app1`. Это **основной и фактический
   вариант деплоя**.
2. **Альтернативный сценарий: Деплой из GitHub Packages (GHCR)** — **использовать ТОЛЬКО при
   прямом указании заказчика**. Подтянуть готовый immutable-образ `app-service` из GHCR
   (`docker compose pull app1`) и пересоздать контейнер.
3. **Восстановление / перезапуск текущего состояния** — перезапустить `app1` без пересборки
   через `docker compose up -d --no-deps --force-recreate app1`.
4. **Откат (Rollback)** — переключить git на предыдущий стабильный коммит и выполнить
   ребилд `docker compose build app1` (для основного сценария) либо вернуть предыдущий
   `IMAGE_TAG` в `.env` (для сценария с GHCR).

Также уточнить:

- хост, пользователя и SSH-ключ (`user1@87.242.100.34`, ключ `d:\.ssh\id_ed25519`);
- каталоги на сервере: корень compose `/home/user1` (где лежит `/home/user1/compose.yaml`) и каталог репозитория приложения `/home/user1/iot-rpc-rest-app`;
- сервис: только `app1` / `app-service` или ещё другие компоненты;
- допустимо ли запускать Alembic-миграции при старте `app1`
  (`prestart.sh` автоматически выполняет `alembic upgrade head`).

> ⚠️ **Критическое правило изоляции:**
> Если запрос «только app», **строго запрещено** выполнять `docker compose up -d` без
> имени сервиса и **запрещено** пересоздавать `rabbitmq`, `nginx`, `nginx-mutual`,
> `processing-backend`, `menubuilder-backend`. Всегда использовать флаг `--no-deps app1`.
> 
> 💡 Если задача включает обновление конфигурации брокера сообщений (`rmq/rabbitmq.conf`, `rmq/definitions.json`),
> сетевой топологии Docker Compose или комплексный рестарт сервисов,
> используйте регламент: [`manual-infra-and-rmq-deploy-runbook.md`](manual-infra-and-rmq-deploy-runbook.md).

---

## 1. Проверенная конфигурация

На новом сервере мультисервисный оркестратор платформы находится в `/home/user1/compose.yaml`,
а репозиторий приложения — в `/home/user1/iot-rpc-rest-app`:

```yaml
# /home/user1/compose.yaml
services:
  app1:
    build:
      context: ./iot-rpc-rest-app
      dockerfile: ./docker-files/app-service/Dockerfile
    container_name: app1
    restart: always
    env_file:
      - ./iot-rpc-rest-app/app-service/.env
    volumes:
      - ./iot-rpc-rest-app/logs:/var/log/app
```

В каталоге репозитория `./iot-rpc-rest-app/app-service/.env` находятся
runtime-переменные приложения (настройки внешней БД `10.0.0.7:5432/iot_rpc`, брокера RabbitMQ, API-ключей). Файл `.env`
не коммитится в git и не должен выводиться целиком в чат/логи.

Проверенный рабочий стенд (новый сервер):

- SSH: `user1@87.242.100.34`
- SSH-ключ (Windows): `d:\.ssh\id_ed25519`
- Каталог оркестратора Compose: `/home/user1` (`/home/user1/compose.yaml`)
- Каталог репозитория на VM: `/home/user1/iot-rpc-rest-app`
- Основной сервис: `app1`

---

## 2. Безопасная подготовка и диагностика

Команды ниже предполагают Windows PowerShell на рабочей машине оператора и bash на VM.

### 2.1. Проверить доступность SSH и каталоги проекта

```powershell
ssh -n -i "d:\.ssh\id_ed25519" user1@87.242.100.34 "pwd; hostname; ls -la /home/user1/compose.yaml /home/user1/iot-rpc-rest-app/docker-files/app-service/Dockerfile"
```

### 2.2. Проверить статус текущего контейнера `app1`

```powershell
ssh -n -i "d:\.ssh\id_ed25519" user1@87.242.100.34 "cd /home/user1 && sudo docker compose ps app1"
```

### 2.3. Создать бэкап runtime-конфигурации

Перед проведением любых работ обязательно создать резервную копию конфигурационных файлов:

```powershell
ssh -n -i "d:\.ssh\id_ed25519" user1@87.242.100.34 "cd /home/user1/iot-rpc-rest-app && cp app-service/.env app-service/.env.backup-\$(date +%Y%m%d-%H%M%S) 2>/dev/null || true"
```

---

## 3. ОСНОВНОЙ СЦЕНАРИЙ: Деплой через сборку напрямую на целевом хосте

Этот сценарий является **дефолтным и основным** для развертывания изменений.

### 3.1. Синхронизация актуального кода на сервере

Перейти в каталог репозитория на VM и получить актуальный код:

```powershell
$script = @'
set -euo pipefail
cd /home/user1/iot-rpc-rest-app

echo "=== 1. Git fetch & pull ==="
git fetch origin
git checkout master
git pull --ff-only
git status
git log -1 --oneline
'@

$script | ssh -i "d:\.ssh\id_ed25519" user1@87.242.100.34 "bash -s"
```

*(Если изменения переносятся напрямую или через checkout конкретной ветки/коммита, убедитесь, что рабочее дерево содержит нужный коммит).*

### 3.2. Сборка Docker-образа напрямую на целевой машине

Запустить сборку сервиса `app1` из корня compose `/home/user1`:

```powershell
$script = @'
set -euo pipefail
cd /home/user1

echo "=== 2. Building app1 image locally ==="
sudo docker compose build app1
'@

$script | ssh -i "d:\.ssh\id_ed25519" user1@87.242.100.34 "bash -s"
```

### 3.3. Безопасный перезапуск только `app1`

Перезапустить сервис с флагом `--no-deps`, чтобы не затронуть базу данных, брокер сообщений и reverse-proxy:

```powershell
$script = @'
set -euo pipefail
cd /home/user1

echo "=== 3. Restarting app1 container ==="
sudo docker compose up -d --no-deps app1
sudo docker compose ps app1
'@

$script | ssh -i "d:\.ssh\id_ed25519" user1@87.242.100.34 "bash -s"
```

---

## 4. АЛЬТЕРНАТИВНЫЙ СЦЕНАРИЙ: Деплой из GitHub Packages (GHCR)

> ⚠️ **ВНИМАНИЕ:** Этот сценарий используется **ТОЛЬКО при наличии прямого указания** заказчика
> использовать предсобранные образы из GitHub Packages / GHCR.

### 4.1. Определение immutable tag

На рабочей машине определить целевой commit hash default-ветки:

```powershell
git rev-parse --short origin/master
```

Целевой тег: `sha-<short-sha>` (например, `sha-73193e3`).

### 4.2. Предварительный Pull образа из GHCR

```powershell
ssh -n -i "d:\.ssh\id_ed25519" user1@87.242.100.34 'set -e; cd /home/user1; TARGET_TAG=sha-73193e3; echo "Pulling $TARGET_TAG"; sudo env IMAGE_TAG=$TARGET_TAG docker compose pull app1'
```

Если pull падает с `manifest unknown`, значит пакет ещё не собран в GHCR. Не менять `.env`.

### 4.3. Фиксация `IMAGE_TAG` и запуск `app1`

```powershell
$script = @'
set -euo pipefail
cd /home/user1

TARGET_TAG=sha-73193e3
BACKUP=.env.backup-before-app1-deploy-$(date +%Y%m%d-%H%M%S)

sudo cp .env "$BACKUP" 2>/dev/null || touch .env
sudo sed -i "s/^IMAGE_TAG=.*/IMAGE_TAG=$TARGET_TAG/" .env || echo "IMAGE_TAG=$TARGET_TAG" | sudo tee -a .env

sudo env IMAGE_TAG=$TARGET_TAG docker compose up -d --no-deps app1
sudo docker compose ps app1
'@

$script | ssh -i "d:\.ssh\id_ed25519" user1@87.242.100.34 "bash -s"
```

---

## 5. Откат изменений (Rollback)

### Вариант 5.1. Откат для основного сценария (сборка на хосте)

1. Переключить git на предыдущий стабильный коммит в каталоге репозитория:
   ```bash
   cd /home/user1/iot-rpc-rest-app
   git checkout <previous_commit_sha>
   ```
2. Пересобрать и перезапустить `app1` из корня compose:
   ```bash
   cd /home/user1
   sudo docker compose build app1
   sudo docker compose up -d --no-deps app1
   ```

### Вариант 5.2. Откат для сценария GHCR

1. Найти резервную копию `.env`:
   ```bash
   cd /home/user1
   ls -1t .env.backup-before-app1-deploy-* | head -1
   ```
2. Восстановить предыдущий `IMAGE_TAG` и перезапустить:
   ```bash
   sudo cp <backup_file> .env
   sudo docker compose up -d --no-deps app1
   ```

---

## 6. Проверки после деплоя (Healthcheck)

### 6.1. Проверка статуса контейнера и логов запуска

```powershell
ssh -n -i "d:\.ssh\id_ed25519" user1@87.242.100.34 "cd /home/user1 && sudo docker compose ps app1 && echo '--- last logs ---' && sudo docker compose logs --no-color --tail=50 app1"
```

**Маркеры успешного старта:**
- Контейнер `app1` имеет статус `Up (healthy)` или `Up`.
- В логах присутствует `Migrations applied!` (успешное применение миграций Alembic).
- В логах зафиксировано подключение FastStream к RabbitMQ и запуск маршрутов.
- Gunicorn/Uvicorn завершил запуск: `Application startup complete`.
- В логах зафиксирована актуализация прав устройств: `RabbitMQ device ACL sync completed`.

### 6.2. Внутренняя проверка HTTP эндпоинта

```powershell
ssh -n -i "d:\.ssh\id_ed25519" user1@87.242.100.34 "sudo docker exec app1 python -c 'from urllib.request import urlopen; r=urlopen(\"http://127.0.0.1:8000/docs\", timeout=5); print(\"internal_http_status:\", r.status); r.close()'"
```
Ожидаемый вывод: `internal_http_status: 200`.

### 6.3. Проверка через внешний Nginx шлюз с API-ключом

```powershell
curl.exe -s -k -H "X-API-Key: testkey_org1_abc" "https://dev.leo4.ru:3000/api/v1/devices/"
```
Ожидаемый вывод: HTTP 200 и JSON со списком устройств организации.

### 6.4. Проверка синхронизации прав устройств в RabbitMQ

```powershell
ssh -n -i "d:\.ssh\id_ed25519" user1@87.242.100.34 "sudo docker logs --tail=50 app1 | grep 'device ACL sync'"
```
Ожидаемый вывод: `RabbitMQ device ACL sync completed: {'created': ..., 'updated': ..., ...}`.

---

## 7. Частые ошибки и их устранение

1. **`Permission denied` к Docker socket:**
   - Выполнять команды с `sudo` либо добавить пользователя в группу `docker`.
2. **Перезапуск лишних контейнеров при деплое:**
   - Забыт флаг `--no-deps app1`. Никогда не вызывать `docker compose up -d` без явного указания `--no-deps app1`.
3. **PowerShell съедает переменные bash (`$TARGET_TAG`, `$(date)`):**
   - Использовать передачу скрипта через heredoc `@' ... '@` и `ssh ... "bash -s"`.
4. **Ошибки миграций Alembic при старте:**
   - Проверить лог контейнера: `sudo docker compose logs app1`. При конфликтах миграций проверить состояние таблицы `alembic_version` в БД.
5. **Отсутствует файл `app-service/.env`:**
   - `docker compose up -d` выдаст ошибку отсутствия файла env. Восстановить файл из бэкапа `app-service/.env.backup-*`.

---

## 8. Чек-лист для оператора / AI-агента

- [ ] Уточнён сценарий деплоя: **сборка на хосте (по умолчанию)** либо GHCR (только при явном указании).
- [ ] Проверен и сохранён бэкап `.env` / `app-service/.env`.
- [ ] Синхронизирован исходный код на целевом сервере.
- [ ] Выполнен `sudo docker compose build app1`.
- [ ] Выполнен перезапуск с изоляцией: `sudo docker compose up -d --no-deps app1`.
- [ ] Проверены логи `app1` (Alembic миграции, FastStream, uvicorn startup).
- [ ] Выполнена валидация внутренних и внешних эндпоинтов (HTTP 200).
- [ ] Пользователю предоставлен краткий отчёт о результатах проверки.

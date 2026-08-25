# Runbook: ручной деплой только `app1` / `app-service` из GHCR

Документ для AI-агентов и DevOps-операторов. Описывает аккуратный pull/recreate
только основного сервиса приложения (`app1`) на существующей VM или на другой
машине с аналогичной `docker compose`-структурой.

Связанные документы:

- [`deploy-plan.md`](deploy-plan.md) — общий план деплоя и режим Build only.
- [`deploy-plan.md` §6.2](deploy-plan.md#62-env-и-конфигурация-app1-без-локального-билда) — почему `app-service/.env` прокидывается через `env_file`.
- [`deploy-plan.md` §6.4](deploy-plan.md#64-ручной-деплой-на-vm-текущий-флоу-по-сервисам) — общий ручной флоу по сервисам.

## 0. Обязательное уточнение перед любым деплоем

Перед SSH-подключением и изменениями агент/оператор обязан явно уточнить у
заказчика режим операции:

1. **Деплой самого нового app-пакета** — подтянуть новый образ `app-service`
   из GHCR и пересоздать только `app1`.
   - Для production не использовать плавающий Docker tag `latest` как
     финальное состояние, если заказчик отдельно не просит именно `:latest`.
   - Под «самым новым latest» в обычном ручном деплое понимаем: определить
     актуальный commit default-ветки (`master`/`main`), взять immutable tag
     `sha-<short-sha>`, зафиксировать его в `.env` как `IMAGE_TAG=sha-...`,
     затем выполнить `docker compose pull app1` и `docker compose up -d --no-deps app1`.
2. **Восстановление текущего состояния** — не менять `IMAGE_TAG`, а заново
   подтянуть/пересоздать `app1` с уже закреплённым tag из `.env`.
3. **Откат на предыдущий tag** — взять tag из backup `.env` или из
   `docker compose ps app1`, записать его в `.env`, подтянуть и пересоздать
   только `app1`.

Также уточнить:

- хост, пользователя и SSH-ключ;
- каталог репозитория на VM;
- сервис: только `app1` / `app-service` или ещё `nginx`/`nginx-mutual`;
- допустимо ли запускать Alembic-миграции при старте `app1`
  (`prestart.sh` выполняет `alembic upgrade head`).

Если пользователь просит «только app», **не выполнять** `docker compose up -d`
без имени сервиса и **не пересоздавать** `pg`, `rabbitmq`, `nginx`,
`nginx-mutual`, `pgadmin`, `certbot`.

## 1. Проверенная конфигурация

Для текущего compose-файла основной сервис называется `app1`:

```yaml
services:
  app1:
    image: ghcr.io/oleglebedevru/iot-rpc-rest-app/app-service:${IMAGE_TAG:-latest}
    env_file:
      - ./app-service/.env
```

На VM рядом с `compose.yaml` должен быть файл `.env` с `IMAGE_TAG=sha-...`, а
в `./app-service/.env` должны лежать runtime-переменные приложения. Оба файла
не коммитятся в git и не должны выводиться целиком в чат/логи.

Проверенный в чате пример VM:

- SSH: `user1@176.108.247.249`
- ключ Windows: `D:\.ssh\free-tier-cloud_ru`
- каталог: `/home/user1/iot-rpc-rest-app`
- сервис: `app1`
- предыдущий tag: `sha-db3706f`
- успешно задеплоенный tag: `sha-73193e3`

## 2. Безопасная подготовка

Команды ниже предполагают Windows PowerShell на рабочей машине и bash на VM.
Пути/хосты адаптировать под целевую машину.

Проверить SSH и найти compose-файл:

```powershell
ssh user1@176.108.247.249 -i "D:\.ssh\free-tier-cloud_ru" "pwd; hostname; find ~ -maxdepth 5 \( -name compose.yaml -o -name docker-compose.yml -o -name docker-compose.yaml \) -print"
```

Проверить сервисы, image и текущий tag без вывода секретов:

```powershell
ssh user1@176.108.247.249 -i "D:\.ssh\free-tier-cloud_ru" "cd /home/user1/iot-rpc-rest-app && docker compose config --services && echo '--- app1 image ---' && docker compose config | sed -n '/^  app1:/,/^  [a-zA-Z0-9_-]*:/p' | sed -n '1,80p' && echo '--- IMAGE_TAG ---' && sed -n 's/^IMAGE_TAG=.*/&/p' .env"
```

Если пользователь на VM не состоит в группе `docker`, команды `docker compose`
выполнять через `sudo`.

## 3. Режим A — деплой самого нового app-пакета

### 3.1. Определить immutable tag

На рабочей машине в локальном checkout:

```powershell
git --no-pager fetch origin
git --no-pager ls-remote origin refs/heads/master refs/heads/main
git --no-pager rev-parse --short origin/master
```

Если default-ветка — `master`, целевой tag будет:

```text
sha-<short-sha-origin-master>
```

Например, для commit `73193e3...` tag: `sha-73193e3`.

> Почему не просто `latest`: `latest` удобен для проверки, но для production
> runbook фиксирует воспроизводимый `sha-*`, чтобы можно было однозначно
> понять, что запущено, и быстро откатиться.

### 3.2. Pull нового образа без изменения контейнера

Сначала подтянуть образ с целевым tag, не меняя `.env` и не перезапуская сервис:

```powershell
ssh user1@176.108.247.249 -i "D:\.ssh\free-tier-cloud_ru" 'set -e; cd /home/user1/iot-rpc-rest-app; NEW_IMAGE_TAG=sha-73193e3; printf "Current IMAGE_TAG: "; sed -n "s/^IMAGE_TAG=//p" .env; echo "Target IMAGE_TAG: $NEW_IMAGE_TAG"; sudo env IMAGE_TAG=$NEW_IMAGE_TAG docker compose pull app1'
```

Если pull падает с `manifest unknown`, значит tag ещё не опубликован в GHCR
или выбран не тот SHA. Не менять `.env`; сначала уточнить tag/статус GitHub
Actions.

### 3.3. Backup `.env`, фиксация tag и recreate только `app1`

После успешного pull:

```powershell
$script = @'
set -euo pipefail
cd /home/user1/iot-rpc-rest-app

NEW_IMAGE_TAG=sha-73193e3
BACKUP=.env.backup-before-app1-deploy-$(date +%Y%m%d-%H%M%S)

sudo cp .env "$BACKUP"
sudo sed -i "s/^IMAGE_TAG=.*/IMAGE_TAG=$NEW_IMAGE_TAG/" .env

echo "IMAGE_TAG updated to $NEW_IMAGE_TAG"
echo "Backup file: $BACKUP"

sudo docker compose up -d --no-deps app1
sudo docker compose ps app1
'@

$script | ssh user1@176.108.247.249 -i "D:\.ssh\free-tier-cloud_ru" "bash -s"
```

Ключевые правила:

- `--no-deps` обязателен для запроса «только app», чтобы compose не трогал
  зависимости;
- не запускать `docker compose up -d` без имени сервиса;
- не печатать `.env` целиком;
- backup `.env` хранить на VM для быстрого отката.

## 4. Режим B — восстановление текущего закреплённого app

Используется, если нужно восстановить/пересоздать `app1` без перехода на новый
tag. `IMAGE_TAG` в `.env` не меняется.

```powershell
$script = @'
set -euo pipefail
cd /home/user1/iot-rpc-rest-app

CURRENT_IMAGE_TAG=$(sed -n 's/^IMAGE_TAG=//p' .env)
test -n "$CURRENT_IMAGE_TAG"

echo "Recreate current app1 IMAGE_TAG=$CURRENT_IMAGE_TAG"
sudo docker compose pull app1
sudo docker compose up -d --no-deps app1
sudo docker compose ps app1
'@

$script | ssh user1@176.108.247.249 -i "D:\.ssh\free-tier-cloud_ru" "bash -s"
```

## 5. Режим C — rollback на предыдущий tag

Найти backup и текущий tag:

```powershell
ssh user1@176.108.247.249 -i "D:\.ssh\free-tier-cloud_ru" "cd /home/user1/iot-rpc-rest-app && ls -1t .env.backup-before-app1-deploy-* 2>/dev/null | head -5 && sed -n 's/^IMAGE_TAG=.*/&/p' .env && sudo docker compose ps app1"
```

Посмотреть только `IMAGE_TAG` в выбранном backup:

```powershell
ssh user1@176.108.247.249 -i "D:\.ssh\free-tier-cloud_ru" "cd /home/user1/iot-rpc-rest-app && sed -n 's/^IMAGE_TAG=.*/&/p' .env.backup-before-app1-deploy-YYYYMMDD-HHMMSS"
```

Откатить на нужный tag:

```powershell
$script = @'
set -euo pipefail
cd /home/user1/iot-rpc-rest-app

ROLLBACK_IMAGE_TAG=sha-db3706f
BACKUP=.env.backup-before-app1-rollback-$(date +%Y%m%d-%H%M%S)

sudo cp .env "$BACKUP"
sudo sed -i "s/^IMAGE_TAG=.*/IMAGE_TAG=$ROLLBACK_IMAGE_TAG/" .env

echo "Rollback IMAGE_TAG=$ROLLBACK_IMAGE_TAG"
echo "Backup before rollback: $BACKUP"

sudo env IMAGE_TAG=$ROLLBACK_IMAGE_TAG docker compose pull app1
sudo docker compose up -d --no-deps app1
sudo docker compose ps app1
'@

$script | ssh user1@176.108.247.249 -i "D:\.ssh\free-tier-cloud_ru" "bash -s"
```

## 6. Проверки после recreate

Минимальная проверка статуса и логов:

```powershell
ssh user1@176.108.247.249 -i "D:\.ssh\free-tier-cloud_ru" "cd /home/user1/iot-rpc-rest-app && sudo docker compose ps app1 && echo '--- last logs ---' && sudo docker compose logs --no-color --tail=120 app1"
```

Ожидаемые признаки успешного старта:

- контейнер `app1` в состоянии `Up`;
- image соответствует целевому `sha-*`;
- в логах есть `Migrations applied!`;
- gunicorn/uvicorn стартовал;
- `Application startup complete`.

Внутренняя HTTP-проверка FastAPI из контейнера:

```powershell
$script = @'
set -e
cd /home/user1/iot-rpc-rest-app
sudo docker exec app1 python -c 'from urllib.request import urlopen; r=urlopen("http://127.0.0.1:8000/docs", timeout=5); print("internal_http_status", r.status); r.close()'
sudo docker compose ps app1 --format 'table {{.Name}}\t{{.Image}}\t{{.Status}}'
'@

$script | ssh user1@176.108.247.249 -i "D:\.ssh\free-tier-cloud_ru" "bash -s"
```

Ожидаемый результат:

```text
internal_http_status 200
```

## 7. Частые ошибки

- **`Permission denied` к Docker socket** — использовать `sudo docker compose ...`
  или настроить пользователя в группе `docker` по правилам эксплуатации VM.
- **Неверный путь к SSH-ключу в Windows PowerShell** — использовать абсолютный
  путь вроде `"D:\.ssh\free-tier-cloud_ru"`, а не `d:.ssh\...`.
- **PowerShell съел `$(...)` или кавычки remote-команды** — для сложных команд
  передавать bash-script через stdin (`$script | ssh ... "bash -s"`).
- **`manifest unknown` при pull** — выбранный `sha-*` tag ещё не опубликован
  или workflow не завершился; не менять `.env`, пока pull не успешен.
- **Нет `app-service/.env` на VM** — `docker compose up -d app1` должен упасть
  до старта контейнера; восстановить runtime `.env` из безопасного хранилища.

## 8. Чек-лист для агента перед ответом пользователю

- [ ] Уточнён режим: новый app-пакет / восстановление текущего / rollback.
- [ ] Уточнены host, SSH user/key, deploy directory.
- [ ] Проверено имя сервиса `app1` через `docker compose config --services`.
- [ ] Не выведены секреты и `.env` целиком.
- [ ] Для нового деплоя сначала успешно выполнен `pull` целевого `sha-*`.
- [ ] Перед изменением `.env` создан backup.
- [ ] Выполнено `docker compose up -d --no-deps app1`, а не общий `up -d`.
- [ ] Проверены `docker compose ps app1`, последние логи и HTTP `200` внутри контейнера.
- [ ] Пользователю сообщены итоговый image/tag и путь backup-файла.

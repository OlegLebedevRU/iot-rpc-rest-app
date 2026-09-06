# Runbook: деплой инфраструктуры RabbitMQ, межсервисных сетей и комплексных обновлений

Документ для AI-агентов, DevOps-инженеров и системных администраторов. Описывает проверенную процедуру безопасного деплоя инфраструктурных изменений: конфигураций брокера сообщений RabbitMQ (`rmq/rabbitmq.conf`, `rmq/definitions.json`), общих межсервисных Docker-сетей (`iot_rabbitmq_network` в `compose.yaml`), прокси-серверов (`nginx`, `nginx-mutual`) и сервиса приложения (`app1`) на целевой VM без потери данных томов и активных сессий устройств.

Связанные документы:
- [`manual-app1-deploy-runbook.md`](manual-app1-deploy-runbook.md) — регламент деплоя только `app1` (изолированное обновление логики приложения).
- [`deploy-plan.md`](deploy-plan.md) — общая архитектура, план деплоя и дорожная карта миграции.
- [`rabbitmq-acl-recovery.md`](rabbitmq-acl-recovery.md) — регламент восстановления динамических ACL устройств и прав в брокере.
- [`tz-new-rmq-infra-for-telemetry.md`](../prompt-lib/tz-new-rmq-infra-for-telemetry.md) — спецификация интеграции шины сообщений с сервисом телеметрии `etranprocessing`.

---

## 0. Область применения и ключевые правила безопасности

Данный runbook применяется в случаях, когда деплой затрагивает не только код `app1`, но и инфраструктурный слой:
1. **Конфигурация RabbitMQ**: изменение `rmq/rabbitmq.conf` (слушатели портов, таймауты, лимиты сессий).
2. **Базовые дефиниции брокера**: добавление/изменение сервисных пользователей (например, `etran_service`), прав на vhost `/` и топиковых разрешений (`topic_permissions`) в `rmq/definitions.json`.
3. **Сетевая топология Docker Compose**: объявление или переименование bridge-сетей (например, `iot_rabbitmq_network`), подключение внешних потребителей телеметрии.
4. **Конфигурация reverse-proxy**: синхронизация `nginx` и `nginx-mutual` при изменении сетевых настроек или сертификатов.

> ⚠️ **КРИТИЧЕСКИЕ ПРАВИЛА СОХРАННОСТИ ДАННЫХ:**
> - **СТРОГО ЗАПРЕЩЕНО** выполнять `docker compose down -v` или удалять том `rabbitmq_data`. В нём хранятся динамические аккаунты устройств и постоянные сессии MQTT. База данных PostgreSQL вынесена на внешний хост `10.0.0.7:5432/iot_rpc` и не управляется локальным compose.
> - **СТРОГО ЗАПРЕЩЕНО** публиковать сервисный порт Plain MQTT `1883` наружу в интернет на хосте. Доступ к нему разрешён исключительно внутри изолированной сети Docker.
> - **СОБЛЮДАТЬ ИЗОЛЯЦИЮ СЕРВИСОВ**: перезапуск компонентов выполняется поэтапно через `docker compose up -d --no-deps <service>`.

---

## 1. Проверенный рабочий стенд и реквизиты

- **Целевой хост**: `user1@87.242.100.34`
- **SSH-ключ (Windows)**: `d:\.ssh\id_ed25519`
- **Каталог оркестратора Compose**: `/home/user1` (`/home/user1/compose.yaml`)
- **Рабочий каталог репозитория на VM**: `/home/user1/iot-rpc-rest-app`
- **Конфигурации Nginx**: `/home/user1/nginx-configs` и `/home/user1/nginx-mutual-legacy`
- **Общая Docker-сеть**: `user1_default` (bridge)
- **Порты RabbitMQ**:
  - `5672` (AMQP 0-9-1) — внутренний транспорт между `app1` и RabbitMQ;
  - `1883` (Plain MQTT) — внутренний слушатель для межсервисной телеметрии (`etranprocessing`);
  - `8883` (MQTT SSL/mTLS) — внешний защищённый шлюз для IoT-терминалов;
  - `15672` (HTTP Management) — панель управления и API RabbitMQ.

---

## 2. Успешные паттерны использования инструментов и скриптов

### 2.1. Безопасное исполнение удалённых команд через SSH

При работе из Windows PowerShell для предотвращения зависаний и искажения кавычек/спецсимволов используются следующие паттерны:

#### Паттерн А: Неинтерактивный вызов одиночной команды
```powershell
ssh -n -i "d:\.ssh\id_ed25519" -o BatchMode=yes user1@87.242.100.34 "cd /home/user1 && sudo docker compose ps"
```
- `-n`: предотвращает чтение из `stdin` (защита от фонового блокирования сессии).
- `-o BatchMode=yes`: отключает интерактивные запросы пароля, завершая команду с ошибкой при сбое ключа.

#### Паттерн Б: Передача многострочных скриптов через PowerShell Here-String
```powershell
$script = @'
set -euo pipefail
cd /home/user1
echo "=== Checking runtime status ==="
sudo docker compose ps
'@

$script | ssh -n -i "d:\.ssh\id_ed25519" -o BatchMode=yes user1@87.242.100.34 "bash -s"
```
- Гарантирует целостность переменных `$VAR`, пайплайнов и флагов `set -euo pipefail` без экранирования в PowerShell.

### 2.2. Точечная синхронизация файлов через SCP

Если изменения не закоммичены в git или требуется синхронизировать локальные конфиги/тесты:

```powershell
# Синхронизация инфраструктурных файлов
scp -i "d:\.ssh\id_ed25519" compose.yaml user1@87.242.100.34:/home/user1/iot-rpc-rest-app/compose.yaml
scp -i "d:\.ssh\id_ed25519" rmq/rabbitmq.conf user1@87.242.100.34:/home/user1/iot-rpc-rest-app/rmq/rabbitmq.conf
scp -i "d:\.ssh\id_ed25519" rmq/definitions.json user1@87.242.100.34:/home/user1/iot-rpc-rest-app/rmq/definitions.json
scp -i "d:\.ssh\id_ed25519" rmq/enabled_plugins user1@87.242.100.34:/home/user1/iot-rpc-rest-app/rmq/enabled_plugins
```

---

## 3. Пошаговый регламент деплоя (Step-by-Step Runbook)

### Этап 1. Предварительная диагностика состояния сервера

Перед внесением любых изменений фиксируем текущую топологию, тома и статус сервисов.

```powershell
$script = @'
set -euo pipefail
cd /home/user1

echo "=== 1. Проверка активных контейнеров ==="
sudo docker compose ps

echo "=== 2. Проверка томов Docker (гарантия сохранности данных) ==="
sudo docker volume ls | grep -E "rabbitmq_data"

echo "=== 3. Проверка существующих сетей ==="
sudo docker network ls
'@

$script | ssh -n -i "d:\.ssh\id_ed25519" -o BatchMode=yes user1@87.242.100.34 "bash -s"
```

---

## Этап 2. Комплексное резервное копирование конфигураций и дефиниций

Создаём резервные копии всех изменяемых файлов и экспортируем живые runtime-дефиниции RabbitMQ (включая динамические аккаунты устройств).

```powershell
$script = @'
set -euo pipefail
cd /home/user1

TIMESTAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_DIR="/home/user1/backups/backup-$TIMESTAMP"
mkdir -p "$BACKUP_DIR"

echo "=== Резервное копирование файлов в $BACKUP_DIR ==="
test -f compose.yaml && cp compose.yaml "$BACKUP_DIR/compose.yaml" || true
test -f iot-rpc-rest-app/app-service/.env && cp iot-rpc-rest-app/app-service/.env "$BACKUP_DIR/app-service.env" || true
test -f iot-rpc-rest-app/rmq/rabbitmq.conf && cp iot-rpc-rest-app/rmq/rabbitmq.conf "$BACKUP_DIR/rabbitmq.conf" || true
test -f iot-rpc-rest-app/rmq/definitions.json && cp iot-rpc-rest-app/rmq/definitions.json "$BACKUP_DIR/definitions.json" || true
test -f iot-rpc-rest-app/rmq/enabled_plugins && cp iot-rpc-rest-app/rmq/enabled_plugins "$BACKUP_DIR/enabled_plugins" || true

echo "=== Экспорт live-дефиниций RabbitMQ ==="
sudo docker compose exec -T rabbitmq rabbitmqctl export_definitions /tmp/definitions-live.json || true
if sudo docker compose exec -T rabbitmq test -f /tmp/definitions-live.json; then
    sudo docker compose cp rabbitmq:/tmp/definitions-live.json "$BACKUP_DIR/definitions-live.json"
    echo "Live definitions успешно сохранены."
fi

echo "Бэкап завершён: $BACKUP_DIR"
ls -la "$BACKUP_DIR"
'@

$script | ssh -n -i "d:\.ssh\id_ed25519" -o BatchMode=yes user1@87.242.100.34 "bash -s"
```

---

### Этап 3. Синхронизация файлов и актуализация кода на сервере

Переносим актуальные файлы конфигурации (`compose.yaml`, `rmq/rabbitmq.conf`, `rmq/definitions.json`, `rmq/enabled_plugins`) и исходный код:

```powershell
$script = @'
set -euo pipefail
cd /home/user1/iot-rpc-rest-app

echo "=== Актуализация рабочего дерева Git ==="
git fetch origin
git checkout master
git pull --ff-only
git status -s
'@

$script | ssh -n -i "d:\.ssh\id_ed25519" -o BatchMode=yes user1@87.242.100.34 "bash -s"
```

*(Если деплой выполняется напрямую с рабочей станции без коммита в `origin/master`, передайте изменённые файлы через `scp`, как показано в § 2.2).*

---

### Этап 4. Сборка и перезапуск сервиса `app1`

Выполняем локальную сборку образа приложения на хосте с помощью `uv` и перезапускаем `app1` с флагом `--no-deps`:

```powershell
$script = @'
set -euo pipefail
cd /home/user1

echo "=== Сборка образа app1 ==="
sudo docker compose build app1

echo "=== Перезапуск контейнера app1 ==="
sudo docker compose up -d --no-deps app1
sudo docker compose ps app1
'@

$script | ssh -n -i "d:\.ssh\id_ed25519" -o BatchMode=yes user1@87.242.100.34 "bash -s"
```

При старте контейнера скрипт `prestart.sh` автоматически применит миграции Alembic (`alembic upgrade head`), а приложение подключится к внешней БД и брокеру. Также автоматически запустится фоновая синхронизация прав устройств в RabbitMQ.

---

### Этап 5. Безопасный перезапуск брокера сообщений `rabbitmq`

Пересоздаём контейнер `rabbitmq` для применения новых параметров `rabbitmq.conf`, дефиниций `definitions.json` и плагинов `enabled_plugins`:

> 💡 **Важно:** Volume `rabbitmq_data` сохраняется неизменным. RabbitMQ подгрузит обновлённый конфигурационный файл слушателей и применит новые статические сущности из `definitions.json`, не затронув сохранённые в БД Mnesia динамические токены устройств.

```powershell
$script = @'
set -euo pipefail
cd /home/user1

echo "=== Перезапуск RabbitMQ ==="
sudo docker compose up -d --no-deps rabbitmq

echo "=== Ожидание готовности брокера (Healthcheck) ==="
for i in {1..30}; do
    STATUS=$(sudo docker inspect --format="{{.State.Health.Status}}" $(sudo docker compose ps -q rabbitmq) 2>/dev/null || echo "starting")
    if [ "$STATUS" = "healthy" ]; then
        echo "RabbitMQ is healthy!"
        break
    fi
    echo "Waiting for RabbitMQ healthcheck ($i/30)... status: $STATUS"
    sleep 2
done

echo "=== Применение актуальных дефиниций в runtime Mnesia ==="
sudo docker compose exec rabbitmq rabbitmqctl import_definitions /etc/rabbitmq/definitions.json 2>/dev/null || true

sudo docker compose ps rabbitmq
'@

$script | ssh -n -i "d:\.ssh\id_ed25519" -o BatchMode=yes user1@87.242.100.34 "bash -s"
```

---

### Этап 6. Обновление и перезапуск прокси (`nginx`, `nginx-mutual`)

Для того чтобы reverse-proxy контейнеры перечитали конфигурации:

```powershell
$script = @'
set -euo pipefail
cd /home/user1

echo "=== Перезапуск Nginx reverse-proxy ==="
sudo docker compose up -d --no-deps nginx
sudo docker compose ps nginx
'@

$script | ssh -n -i "d:\.ssh\id_ed25519" -o BatchMode=yes user1@87.242.100.34 "bash -s"
```

Если обновлялся legacy mTLS прокси:

```powershell
$script = @'
set -euo pipefail
cd /home/user1/nginx-mutual-legacy

echo "=== Перезапуск legacy nginx-mutual ==="
sudo docker compose up -d --no-deps nginx-mutual
sudo docker compose ps
'@

$script | ssh -n -i "d:\.ssh\id_ed25519" -o BatchMode=yes user1@87.242.100.34 "bash -s"
```

---

## 4. Верификация и диагностика работоспособности

После завершения перезапуска контейнеров необходимо выполнить полный цикл проверок.

### 4.1. Проверка слушателей протоколов RabbitMQ

Убедиться, что активны все требуемые слушатели:
- `1883` — Plain MQTT (для телеметрии);
- `8883` — MQTT over TLS (для IoT-терминалов);
- `5672` — AMQP (для ядра приложения);
- `15672` — HTTP Management.

```powershell
ssh -n -i "d:\.ssh\id_ed25519" -o BatchMode=yes user1@87.242.100.34 "sudo docker exec rabbitmq rabbitmq-diagnostics listeners"
```

Ожидаемый вывод содержит строки вида:
```text
Interface: [::], port: 15672, protocol: http, purpose: HTTP API
Interface: [::], port: 1883, protocol: mqtt, purpose: MQTT
Interface: [::], port: 8883, protocol: mqtt/ssl, purpose: MQTT TLS
Interface: [::], port: 5672, protocol: amqp, purpose: AMQP 0-9-1
```

### 4.2. Проверка пользователей и топиковых прав (`amq.topic`)

Проверяем наличие сервисного пользователя `etran_service` и корректность ACL на `amq.topic`:

```powershell
$script = @'
echo "=== Список пользователей RabbitMQ ==="
sudo docker exec rabbitmq rabbitmqctl list_users | grep -E "etran_service|admin|device"

echo "=== Права на vhost / ==="
sudo docker exec rabbitmq rabbitmqctl list_permissions -p / | grep "etran_service"

echo "=== Топиковые разрешения на exchange amq.topic ==="
sudo docker exec rabbitmq rabbitmqctl list_topic_permissions -p / | grep "etran_service"
'@

$script | ssh -n -i "d:\.ssh\id_ed25519" -o BatchMode=yes user1@87.242.100.34 "bash -s"
```

Ожидаемый результат:
- Пользователь `etran_service` присутствует в списке пользователей.
- Права на vhost `/`: `configure = ^(mqtt-subscription-.*|telemetry\..*)`, `write/read = ^(amq\.topic|mqtt-subscription-.*|telemetry\..*)`.
- Топиковые права на exchange `amq.topic`: `write = ^(dev\..*\.gauge\..*|telemetry\..*)`, `read = ^(dev\..*\.gauge\..*|telemetry\..*)`.

### 4.3. Проверка логов приложения `app1` и шедулера задач

Проверяем успешный запуск Gunicorn/Uvicorn, отсутствие ошибок AMQP и активность периодических задач (TTL/Watchdog):

```powershell
ssh -n -i "d:\.ssh\id_ed25519" -o BatchMode=yes user1@87.242.100.34 "sudo docker logs --tail=50 app1"
```

Ключевые маркеры в логах:
- `Migrations applied!` — успешный прогон Alembic.
- `Application startup complete` — FastAPI запущен.
- `Job "act_ttl" executed successfully` — шедулер задач активен.
- `RabbitMQ device ACL sync completed` — синхронизация прав устройств из БД завершена.

### 4.4. Проверка доступности REST API через Nginx

Выполняем проверку API с хоста или извне:

```powershell
curl.exe -s -k -H "X-API-Key: testkey_org1_abc" "https://dev.leo4.ru:3000/api/v1/devices/"
```
Ожидаемый код ответа: `200` и JSON-ответ.

Внутренняя проверка через контейнер:
```powershell
ssh -n -i "d:\.ssh\id_ed25519" -o BatchMode=yes user1@87.242.100.34 "sudo docker exec app1 python -c 'from urllib.request import urlopen; r=urlopen(\"http://127.0.0.1:8000/docs\", timeout=5); print(\"API Status:\", r.status)'"
```

### 4.5. Запуск набора тестов внутри контейнера

Для полной уверенности в интеграции запускаем `pytest` непосредственно в контейнере `app1`:

```powershell
ssh -n -i "d:\.ssh\id_ed25519" -o BatchMode=yes user1@87.242.100.34 "sudo docker exec app1 uv run pytest"
```
Все тесты API, сервисов, схем и интеграций должны завершаться со статусом `passed`.

---

## 5. Процедура отката (Rollback & Disaster Recovery)

Если при деплое обнаружены критические ошибки или сбои авторизации устройств, выполняется процедура быстрого отката:

### 5.1. Восстановление конфигурационных файлов из бэкапа

```powershell
$script = @'
set -euo pipefail
cd /home/user1

LATEST_BACKUP=$(ls -td /home/user1/backups/backup-* | head -1)
echo "Восстановление конфигураций из: $LATEST_BACKUP"

test -f "$LATEST_BACKUP/compose.yaml" && cp "$LATEST_BACKUP/compose.yaml" compose.yaml
test -f "$LATEST_BACKUP/rabbitmq.conf" && cp "$LATEST_BACKUP/rabbitmq.conf" iot-rpc-rest-app/rmq/rabbitmq.conf
test -f "$LATEST_BACKUP/definitions.json" && cp "$LATEST_BACKUP/definitions.json" iot-rpc-rest-app/rmq/definitions.json
test -f "$LATEST_BACKUP/enabled_plugins" && cp "$LATEST_BACKUP/enabled_plugins" iot-rpc-rest-app/rmq/enabled_plugins

echo "Перезапуск сервисов в исходном состоянии..."
sudo docker compose up -d --no-deps rabbitmq app1 nginx
'@

$script | ssh -n -i "d:\.ssh\id_ed25519" -o BatchMode=yes user1@87.242.100.34 "bash -s"
```

### 5.2. Принудительное восстановление динамических ACL устройств

Если при перезапуске брокера возникли проблемы с авторизацией существующих терминалов (ошибки `Reason Code 134` или `access refused`), вызывается эндпоинт принудительной синхронизации:

```powershell
# Изнутри контейнера app1 или через curl:
ssh -n -i "d:\.ssh\id_ed25519" -o BatchMode=yes user1@87.242.100.34 "sudo docker exec app1 curl -s -X POST 'http://127.0.0.1:8000/api/internal/v1/admin/?action=get_u' -H 'X-Internal-Service-Key: internal-service-key-dev'"
```
Это синхронизирует всех зарегистрированных в PostgreSQL устройств в Mnesia-хранилище RabbitMQ.

---

## 6. Готовый PowerShell-скрипт полного цикла деплоя

Для автоматизации проведения инфраструктурных обновлений оператор может использовать следующий готовый PowerShell-скрипт:

```powershell
<#
.SYNOPSIS
    Скрипт безопасного деплоя инфраструктуры RabbitMQ и приложения Leo4 на новом сервере.
#>

$ErrorActionPreference = "Stop"
$SSH_KEY = "d:\.ssh\id_ed25519"
$SSH_HOST = "user1@87.242.100.34"
$COMPOSE_DIR = "/home/user1"
$REPO_DIR = "/home/user1/iot-rpc-rest-app"

Write-Host "==> [1/6] Подключение и создание резервной копии..." -ForegroundColor Cyan
$backupScript = @"
set -euo pipefail
TS=\$(date +%Y%m%d-%H%M%S)
BDIR="/home/user1/backups/backup-\$TS"
mkdir -p "\$BDIR"
cp $COMPOSE_DIR/compose.yaml $REPO_DIR/rmq/rabbitmq.conf $REPO_DIR/rmq/definitions.json $REPO_DIR/rmq/enabled_plugins "\$BDIR/" 2>/dev/null || true
echo "Backup created at \$BDIR"
"@
$backupScript | ssh -n -i $SSH_KEY -o BatchMode=yes $SSH_HOST "bash -s"

Write-Host "==> [2/6] Синхронизация файлов на сервер..." -ForegroundColor Cyan
scp -i $SSH_KEY rmq/rabbitmq.conf "${SSH_HOST}:${REPO_DIR}/rmq/rabbitmq.conf"
scp -i $SSH_KEY rmq/definitions.json "${SSH_HOST}:${REPO_DIR}/rmq/definitions.json"
scp -i $SSH_KEY rmq/enabled_plugins "${SSH_HOST}:${REPO_DIR}/rmq/enabled_plugins"

Write-Host "==> [3/6] Сборка и перезапуск app1..." -ForegroundColor Cyan
$deployAppScript = @"
set -euo pipefail
cd $COMPOSE_DIR
sudo docker compose build app1
sudo docker compose up -d --no-deps app1
"@
$deployAppScript | ssh -n -i $SSH_KEY -o BatchMode=yes $SSH_HOST "bash -s"

Write-Host "==> [4/6] Перезапуск RabbitMQ и Nginx..." -ForegroundColor Cyan
$deployInfraScript = @"
set -euo pipefail
cd $COMPOSE_DIR
sudo docker compose up -d --no-deps rabbitmq
sudo docker compose up -d --no-deps nginx
"@
$deployInfraScript | ssh -n -i $SSH_KEY -o BatchMode=yes $SSH_HOST "bash -s"

Write-Host "==> [5/6] Верификация слушателей и статуса сервисов..." -ForegroundColor Cyan
$verifyScript = @"
set -euo pipefail
echo "--- Docker Containers ---"
cd $COMPOSE_DIR && sudo docker compose ps
echo "--- RabbitMQ Listeners ---"
sudo docker exec rabbitmq rabbitmq-diagnostics listeners
echo "--- Checking Internal App Status ---"
sudo docker exec app1 python -c 'from urllib.request import urlopen; r=urlopen("http://127.0.0.1:8000/docs", timeout=5); print("API Response Code:", r.status)'
"@
$verifyScript | ssh -n -i $SSH_KEY -o BatchMode=yes $SSH_HOST "bash -s"

Write-Host "==> [6/6] Запуск тестов в контейнере..." -ForegroundColor Cyan
ssh -n -i $SSH_KEY -o BatchMode=yes $SSH_HOST "sudo docker exec app1 uv run pytest"

Write-Host "==> Деплой успешно завершён и верифицирован!" -ForegroundColor Green
```

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
> - **СТРОГО ЗАПРЕЩЕНО** выполнять `docker compose down -v` или удалять тома `iot-rpc-rest-app_rabbitmq_data` и `iot-rpc-rest-app_pgdata`. В них хранятся динамические аккаунты устройств, постоянные сессии MQTT и БД PostgreSQL.
> - **СТРОГО ЗАПРЕЩЕНО** публиковать сервисный порт Plain MQTT `1883` наружу в интернет на хосте. Доступ к нему разрешён исключительно внутри изолированной сети Docker `iot_rabbitmq_network`.
> - **СОБЛЮДАТЬ ИЗОЛЯЦИЮ СЕРВИСОВ**: перезапуск компонентов выполняется поэтапно через `docker compose up -d --no-deps <service>` во избежание неконтролируемого каскадного перезапуска базы данных `pg`.

---

## 1. Проверенный рабочий стенд и реквизиты

- **Целевой хост**: `user1@176.108.247.249`
- **SSH-ключ (Windows)**: `D:\.ssh\free-tier-cloud_ru`
- **Рабочий каталог на VM**: `/home/user1/iot-rpc-rest-app`
- **Общая Docker-сеть**: `iot_rabbitmq_network` (bridge)
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
ssh -n -i "D:\.ssh\free-tier-cloud_ru" -o BatchMode=yes user1@176.108.247.249 "cd /home/user1/iot-rpc-rest-app && sudo docker compose ps"
```
- `-n`: предотвращает чтение из `stdin` (защита от фонового блокирования сессии).
- `-o BatchMode=yes`: отключает интерактивные запросы пароля, завершая команду с ошибкой при сбое ключа.

#### Паттерн Б: Передача многострочных скриптов через PowerShell Here-String
```powershell
$script = @'
set -euo pipefail
cd /home/user1/iot-rpc-rest-app
echo "=== Checking runtime status ==="
sudo docker compose ps
sudo docker network ls | grep iot_rabbitmq_network || true
'@

$script | ssh -n -i "D:\.ssh\free-tier-cloud_ru" -o BatchMode=yes user1@176.108.247.249 "bash -s"
```
- Гарантирует целостность переменных `$VAR`, пайплайнов и флагов `set -euo pipefail` без экранирования в PowerShell.

### 2.2. Точечная синхронизация файлов через SCP

Если изменения не закоммичены в git или требуется синхронизировать локальные конфиги/тесты:

```powershell
# Синхронизация инфраструктурных файлов
scp -i "D:\.ssh\free-tier-cloud_ru" compose.yaml user1@176.108.247.249:/home/user1/iot-rpc-rest-app/compose.yaml
scp -i "D:\.ssh\free-tier-cloud_ru" rmq/rabbitmq.conf user1@176.108.247.249:/home/user1/iot-rpc-rest-app/rmq/rabbitmq.conf
scp -i "D:\.ssh\free-tier-cloud_ru" rmq/definitions.json user1@176.108.247.249:/home/user1/iot-rpc-rest-app/rmq/definitions.json
```

---

## 3. Пошаговый регламент деплоя (Step-by-Step Runbook)

### Этап 1. Предварительная диагностика состояния сервера

Перед внесением любых изменений фиксируем текущую топологию, тома и статус сервисов.

```powershell
$script = @'
set -euo pipefail
cd /home/user1/iot-rpc-rest-app

echo "=== 1. Проверка активных контейнеров ==="
sudo docker compose ps

echo "=== 2. Проверка томов Docker (гарантия сохранности данных) ==="
sudo docker volume ls | grep -E "rabbitmq_data|pgdata"

echo "=== 3. Проверка существующих сетей ==="
sudo docker network ls
'@

$script | ssh -n -i "D:\.ssh\free-tier-cloud_ru" -o BatchMode=yes user1@176.108.247.249 "bash -s"
```

---

### Этап 2. Комплексное резервное копирование конфигураций и дефиниций

Создаём резервные копии всех изменяемых файлов и экспортируем живые runtime-дефиниции RabbitMQ (включая динамические аккаунты устройств).

```powershell
$script = @'
set -euo pipefail
cd /home/user1/iot-rpc-rest-app

TIMESTAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_DIR="/home/user1/iot-rpc-rest-app/backups/backup-$TIMESTAMP"
mkdir -p "$BACKUP_DIR"

echo "=== Резервное копирование файлов в $BACKUP_DIR ==="
test -f .env && cp .env "$BACKUP_DIR/.env" || true
test -f app-service/.env && cp app-service/.env "$BACKUP_DIR/app-service.env" || true
test -f compose.yaml && cp compose.yaml "$BACKUP_DIR/compose.yaml" || true
test -f rmq/rabbitmq.conf && cp rmq/rabbitmq.conf "$BACKUP_DIR/rabbitmq.conf" || true
test -f rmq/definitions.json && cp rmq/definitions.json "$BACKUP_DIR/definitions.json" || true

echo "=== Экспорт live-дефиниций RabbitMQ ==="
sudo docker compose exec -T rabbitmq rabbitmqctl export_definitions /tmp/definitions-live.json || true
if sudo docker compose exec -T rabbitmq test -f /tmp/definitions-live.json; then
    sudo docker compose cp rabbitmq:/tmp/definitions-live.json "$BACKUP_DIR/definitions-live.json"
    echo "Live definitions успешно сохранены."
fi

echo "Бэкап завершён: $BACKUP_DIR"
ls -la "$BACKUP_DIR"
'@

$script | ssh -n -i "D:\.ssh\free-tier-cloud_ru" -o BatchMode=yes user1@176.108.247.249 "bash -s"
```

---

### Этап 3. Синхронизация файлов и актуализация кода на сервере

Переносим актуальные файлы конфигурации (`compose.yaml`, `rmq/rabbitmq.conf`, `rmq/definitions.json`) и исходный код:

```powershell
$script = @'
set -euo pipefail
cd /home/user1/iot-rpc-rest-app

echo "=== Актуализация рабочего дерева Git ==="
git fetch origin
git status -s
'@

$script | ssh -n -i "D:\.ssh\free-tier-cloud_ru" -o BatchMode=yes user1@176.108.247.249 "bash -s"
```

*(Если деплой выполняется напрямую с рабочей станции без коммита в `origin/master`, передайте изменённые файлы через `scp`, как показано в § 2.2).*

---

### Этап 4. Сборка и перезапуск сервиса `app1`

Выполняем локальную сборку образа приложения на хосте с помощью `uv` и перезапускаем `app1` с флагом `--no-deps`.

```powershell
$script = @'
set -euo pipefail
cd /home/user1/iot-rpc-rest-app

echo "=== Сборка образа app1 ==="
sudo docker compose build app1

echo "=== Перезапуск контейнера app1 (с созданием/подключением к iot_rabbitmq_network) ==="
sudo docker compose up -d --no-deps app1
sudo docker compose ps app1
'@

$script | ssh -n -i "D:\.ssh\free-tier-cloud_ru" -o BatchMode=yes user1@176.108.247.249 "bash -s"
```

При старте контейнера скрипт `prestart.sh` автоматически применит миграции Alembic (`alembic upgrade head`), а приложение подключится к БД и брокеру.

---

### Этап 5. Безопасный перезапуск брокера сообщений `rabbitmq`

Пересоздаём контейнер `rabbitmq` для применения новых параметров `rabbitmq.conf`, дефиниций `definitions.json` и подключения к сети `iot_rabbitmq_network`.

> 💡 **Важно:** Volume `rabbitmq_data` сохраняется неизменным. RabbitMQ подгрузит обновлённый конфигурационный файл слушателей и применит новые статические сущности из `definitions.json`, не затронув сохранённые в БД Mnesia динамические токены устройств.

```powershell
$script = @'
set -euo pipefail
cd /home/user1/iot-rpc-rest-app

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

sudo docker compose ps rabbitmq
'@

$script | ssh -n -i "D:\.ssh\free-tier-cloud_ru" -o BatchMode=yes user1@176.108.247.249 "bash -s"
```

---

### Этап 6. Обновление сетевой связности прокси (`nginx`, `nginx-mutual`)

Для того чтобы reverse-proxy контейнеры получили правильный DNS-роутинг в новой сети `iot_rabbitmq_network`, перезапускаем их:

```powershell
$script = @'
set -euo pipefail
cd /home/user1/iot-rpc-rest-app

echo "=== Перезапуск Nginx reverse-proxy контейнеров ==="
sudo docker compose up -d --no-deps nginx nginx-mutual
sudo docker compose ps nginx nginx-mutual
'@

$script | ssh -n -i "D:\.ssh\free-tier-cloud_ru" -o BatchMode=yes user1@176.108.247.249 "bash -s"
```

---

## 4. Верификация и диагностика работоспособности

После завершения перезапуска контейнеров необходимо выполнить полный цикл проверок.

### 4.1. Проверка слушателей протоколов RabbitMQ

Убедиться, что активны все 4 требуемых слушателя:
- `1883` — Plain MQTT (для телеметрии);
- `8883` — MQTT over TLS (для IoT-терминалов);
- `5672` — AMQP (для ядра приложения);
- `15672` — HTTP Management.

```powershell
ssh -n -i "D:\.ssh\free-tier-cloud_ru" -o BatchMode=yes user1@176.108.247.249 "sudo docker compose -f /home/user1/iot-rpc-rest-app/compose.yaml exec rabbitmq rabbitmq-diagnostics listeners"
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
cd /home/user1/iot-rpc-rest-app
echo "=== Список пользователей RabbitMQ ==="
sudo docker compose exec rabbitmq rabbitmqctl list_users | grep -E "etran_service|admin"

echo "=== Права на vhost / ==="
sudo docker compose exec rabbitmq rabbitmqctl list_permissions -p / | grep "etran_service"

echo "=== Топиковые разрешения на exchange amq.topic ==="
sudo docker compose exec rabbitmq rabbitmqctl list_topic_permissions -p / | grep "etran_service"
'@

$script | ssh -n -i "D:\.ssh\free-tier-cloud_ru" -o BatchMode=yes user1@176.108.247.249 "bash -s"
```

Ожидаемый результат:
- Пользователь `etran_service` присутствует в списке пользователей.
- Права на запись/чтение в vhost `/`: `^(amq\.topic|telemetry\..*)`.
- Топиковые права на exchange `amq.topic`: `write = ^dev\..*\.gauge\..*`, `read = ^dev\..*\.gauge\..*`.

### 4.3. Проверка логов приложения `app1` и шедулера задач

Проверяем успешный запуск Gunicorn/Uvicorn, отсутствие ошибок AMQP и активность периодических задач (TTL/Watchdog):

```powershell
ssh -n -i "D:\.ssh\free-tier-cloud_ru" -o BatchMode=yes user1@176.108.247.249 "cd /home/user1/iot-rpc-rest-app && sudo docker compose logs --tail=50 app1"
```

Ключевые маркеры в логах:
- `Migrations applied!` — успешный прогон Alembic.
- `Application startup complete` — FastAPI запущен.
- `Job "act_ttl" executed successfully` — шедулер задач активен.
- `RabbitMQ device ACL sync completed` — синхронизация прав устройств из БД завершена.

### 4.4. Проверка доступности REST API через Nginx

Выполняем тестовый HTTP-запрос к эндпоинту документации OpenAPI:

```powershell
ssh -n -i "D:\.ssh\free-tier-cloud_ru" -o BatchMode=yes user1@176.108.247.249 "curl -k -s -o /dev/null -w '%{http_code}\n' https://127.0.0.1/docs"
```
Ожидаемый код ответа: `200`.

### 4.5. Запуск набора тестов внутри контейнера

Для полной уверенности в интеграции запускаем `pytest` непосредственно в контейнере `app1`:

```powershell
ssh -n -i "D:\.ssh\free-tier-cloud_ru" -o BatchMode=yes user1@176.108.247.249 "sudo docker compose -f /home/user1/iot-rpc-rest-app/compose.yaml exec app1 pytest"
```
Все тесты API, сервисов, схем и интеграций должны завершаться со статусом `passed`.

---

## 5. Процедура отката (Rollback & Disaster Recovery)

Если при деплое обнаружены критические ошибки или сбои авторизации устройств, выполняется процедура быстрого отката:

### 5.1. Восстановление конфигурационных файлов из бэкапа

```powershell
$script = @'
set -euo pipefail
cd /home/user1/iot-rpc-rest-app

LATEST_BACKUP=$(ls -td /home/user1/iot-rpc-rest-app/backups/backup-* | head -1)
echo "Восстановление конфигураций из: $LATEST_BACKUP"

test -f "$LATEST_BACKUP/compose.yaml" && cp "$LATEST_BACKUP/compose.yaml" compose.yaml
test -f "$LATEST_BACKUP/rabbitmq.conf" && cp "$LATEST_BACKUP/rabbitmq.conf" rmq/rabbitmq.conf
test -f "$LATEST_BACKUP/definitions.json" && cp "$LATEST_BACKUP/definitions.json" rmq/definitions.json

echo "Перезапуск сервисов в исходном состоянии..."
sudo docker compose up -d --no-deps rabbitmq app1 nginx nginx-mutual
'@

$script | ssh -n -i "D:\.ssh\free-tier-cloud_ru" -o BatchMode=yes user1@176.108.247.249 "bash -s"
```

### 5.2. Принудительное восстановление динамических ACL устройств

Если при перезапуске брокера возникли проблемы с авторизацией существующих терминалов (ошибки `Reason Code 134` или `access refused`), вызывается эндпоинт принудительной синхронизации:

```powershell
# Изнутри сервера или через curl
ssh -n -i "D:\.ssh\free-tier-cloud_ru" -o BatchMode=yes user1@176.108.247.249 "curl -k -X POST 'https://127.0.0.1/api/v1/admin/?action=get_u'"
```
Это синхронизирует всех зарегистрированных в PostgreSQL устройств в Mnesia-хранилище RabbitMQ.

---

## 6. Готовый PowerShell-скрипт полного цикла деплоя

Для автоматизации регулярного проведения таких обновлений оператор может использовать следующий готовый PowerShell-скрипт:

```powershell
<#
.SYNOPSIS
    Скрипт безопасного деплоя инфраструктуры RabbitMQ и приложения Leo4.
#>

$ErrorActionPreference = "Stop"
$SSH_KEY = "D:\.ssh\free-tier-cloud_ru"
$SSH_HOST = "user1@176.108.247.249"
$REMOTE_DIR = "/home/user1/iot-rpc-rest-app"

Write-Host "==> [1/6] Подключение и создание резервной копии..." -ForegroundColor Cyan
$backupScript = @"
set -euo pipefail
cd $REMOTE_DIR
TS=\$(date +%Y%m%d-%H%M%S)
BDIR="$REMOTE_DIR/backups/backup-\$TS"
mkdir -p "\$BDIR"
cp compose.yaml rmq/rabbitmq.conf rmq/definitions.json "\$BDIR/" 2>/dev/null || true
echo "Backup created at \$BDIR"
"@
$backupScript | ssh -n -i $SSH_KEY -o BatchMode=yes $SSH_HOST "bash -s"

Write-Host "==> [2/6] Синхронизация файлов на сервер..." -ForegroundColor Cyan
scp -i $SSH_KEY compose.yaml "${SSH_HOST}:${REMOTE_DIR}/compose.yaml"
scp -i $SSH_KEY rmq/rabbitmq.conf "${SSH_HOST}:${REMOTE_DIR}/rmq/rabbitmq.conf"
scp -i $SSH_KEY rmq/definitions.json "${SSH_HOST}:${REMOTE_DIR}/rmq/definitions.json"

Write-Host "==> [3/6] Сборка и перезапуск app1..." -ForegroundColor Cyan
$deployAppScript = @"
set -euo pipefail
cd $REMOTE_DIR
sudo docker compose build app1
sudo docker compose up -d --no-deps app1
"@
$deployAppScript | ssh -n -i $SSH_KEY -o BatchMode=yes $SSH_HOST "bash -s"

Write-Host "==> [4/6] Перезапуск RabbitMQ и Nginx..." -ForegroundColor Cyan
$deployInfraScript = @"
set -euo pipefail
cd $REMOTE_DIR
sudo docker compose up -d --no-deps rabbitmq
sudo docker compose up -d --no-deps nginx nginx-mutual
"@
$deployInfraScript | ssh -n -i $SSH_KEY -o BatchMode=yes $SSH_HOST "bash -s"

Write-Host "==> [5/6] Верификация слушателей и статуса сервисов..." -ForegroundColor Cyan
$verifyScript = @"
set -euo pipefail
cd $REMOTE_DIR
echo "--- Docker Containers ---"
sudo docker compose ps
echo "--- RabbitMQ Listeners ---"
sudo docker compose exec rabbitmq rabbitmq-diagnostics listeners
echo "--- Checking REST API ---"
curl -k -s -o /dev/null -w "API Response Code: %{http_code}\n" https://127.0.0.1/docs
"@
$verifyScript | ssh -n -i $SSH_KEY -o BatchMode=yes $SSH_HOST "bash -s"

Write-Host "==> [6/6] Запуск тестов в контейнере..." -ForegroundColor Cyan
ssh -n -i $SSH_KEY -o BatchMode=yes $SSH_HOST "sudo docker compose -f $REMOTE_DIR/compose.yaml exec app1 pytest"

Write-Host "==> Деплой успешно завершён и верифицирован!" -ForegroundColor Green
```

# План оптимизации деплоя и миграции на GitHub Packages

Документ — результат исследования инфраструктурных деклараций репозитория
(`compose.yaml`, `docker-files/**/Dockerfile`, `docker-files/rmq/compose.yaml`,
`pyproject.toml`, `app-service/prestart.sh`, `app-service/appup`) и сводный
план перехода к целевой архитектуре, в которой:

- **PostgreSQL** выносится из контейнера на **Managed PostgreSQL в cloud.ru**;
- **nginx + rabbitmq + app1 + pgadmin** разворачиваются на отдельной VM
  (compute) cloud.ru как набор Docker-контейнеров;
- сборка образов выполняется один раз в CI и публикуется в **GitHub Packages
  (GHCR)**, а на VM выполняется только `docker pull` + `docker compose up -d`.

---

## 1. Текущее состояние (as-is)

### 1.1. Сервисы в `compose.yaml`

| Сервис          | Образ / билд                                | Сеть                               | Порты публикуемые                  | Назначение                                                                 |
|-----------------|---------------------------------------------|------------------------------------|------------------------------------|----------------------------------------------------------------------------|
| `app1`          | build `docker-files/app-service/Dockerfile` | `rabbitmq_network`, `pg_network`   | —                                  | FastAPI/FastStream приложение, поднимается через `prestart.sh`+`appup`     |
| `rabbitmq`      | `rabbitmq:4-management`                     | `rabbitmq_network`                 | `5672`, `8883`                     | AMQP + MQTT-плагин, конфиг и `definitions.json` через bind-mount           |
| `pg`            | `postgres`                                  | `pg_network`                       | `5432`                             | PostgreSQL с `pgdata` volume                                               |
| `pgadmin`       | `dpage/pgadmin4`                            | `pg_network`                       | —                                  | UI к Postgres                                                              |
| `nginx`         | build `docker-files/nginx-jwt/Dockerfile`   | `rabbitmq_network`, `pg_network`   | `80`, `443`                        | Внешний reverse-proxy + JWT-модуль, внешние сертификаты                    |
| `nginx-mutual`  | build `docker-files/nginx-mutual/Dockerfile`| `rabbitmq_network`, `pg_network`   | `4443`                             | Внутренний mTLS reverse-proxy для устройств                                |
| `certbot`       | `certbot/certbot:latest`                    | —                                  | —                                  | Выпуск/продление LE-сертификатов через webroot                             |
| `avahi`         | `ydkn/avahi`                                | `host`                             | —                                  | Опциональный mDNS для локального деплоя                                    |

Volumes: `pgdata`, `rabbitmq_data`. Bind-mounts:
`./logs`, `./rmq/*`, `./crt/*`, `./nginx-configs/dev_leo4_ru/*`, `./certbot/*`,
`./nginx/html`, `./avahi-services`.

### 1.2. Dockerfile’ы

- **`docker-files/app-service/Dockerfile`** — `python:3.14-slim` + `uv` из
  `ghcr.io/astral-sh/uv:latest`, ставит зависимости из `uv.lock`, копирует
  `app-service/`, ставит `chmod +x` для `prestart.sh` и `appup`,
  `ENTRYPOINT ["./prestart.sh"]` (выполняет `alembic upgrade head`),
  `CMD ["./appup"]`.
- **`docker-files/nginx-jwt/Dockerfile`** — `debian:bookworm-slim`, ставит
  nginx mainline `1.29.4*` из репозитория nginx.org, выкачивает бинарный
  модуль `ngx-http-auth-jwt-module 2.4.0` с GitHub Releases, конфиг nginx
  пишется heredoc’ом в Dockerfile.
- **`docker-files/nginx-mutual/Dockerfile`** — `debian:bookworm-slim` + nginx
  из stock-репозитория, копирует `crt/*` и `nginx-configs/.../internal_ssl.conf`.
- **`docker-files/rmq/compose.yaml`** — отдельный compose только для RabbitMQ
  (по сути дубликат сервиса `rabbitmq` из корневого compose — кандидат на
  удаление либо синхронизацию).

### 1.3. Слабые места текущего DevOps

1. **Сборка происходит на целевой машине** (`build:` в compose) — каждый
   деплой = `apt-get update`, скачивание модулей, сборка слоёв; долго,
   нестабильно (зависит от внешних зеркал nginx.org/GitHub Releases),
   занимает CPU/диск прод-VM.
2. **Нет тегирования и отката**: образы строятся «по месту», нет
   immutable-артефакта, привязанного к git-SHA.
3. **Секреты в открытом виде**: пароли БД и RabbitMQ зашиты в `compose.yaml`
   и `definitions.json`, сертификаты лежат в `./crt/` рядом с кодом.
4. **PostgreSQL в одном контейнере с приложением** — нет независимого
   бэкапа/HA/мониторинга, том `pgdata` делит судьбу с VM.
5. **Дублирование compose-файлов** (`compose.yaml` vs `docker-files/rmq/compose.yaml`).
6. **Нет CI/CD**: нет `.github/workflows/`, нет линта/тестов/сканов на PR.
7. **Сети `rabbitmq_network` и `pg_network`** соединяют всё со всем — после
   выноса PG `pg_network` для `nginx`/`rabbitmq` не нужен.
8. **`avahi` с `network_mode: host`** — несовместим со многими облачными
   compute-средами, нужно отключать в проде.

---

## 2. Целевая архитектура (to-be)

```
                ┌────────────────────────────────────────────┐
                │                cloud.ru                    │
                │                                            │
   Internet ──▶ │  ┌──────────────────────┐                  │
                │  │  VM: app-host        │                  │
                │  │   (Docker + Compose) │                  │
                │  │                      │ private network  │
                │  │  nginx ──┐           │ ───────────────▶ │  ┌──────────────────────────┐
                │  │  nginx-  │ app1 ──┐  │                  │  │ Managed PostgreSQL       │
                │  │  mutual  │        │  │                  │  │ (cloud.ru DBaaS)         │
                │  │          ├ rabbit │  │                  │  │  - бэкапы, HA, метрики   │
                │  │          │  mq    │  │                  │  └──────────────────────────┘
                │  │  pgadmin─┘        │  │                  │
                │  └──────────────────────┘                  │
                └────────────────────────────────────────────┘
                          ▲
                          │  docker pull ghcr.io/<org>/<svc>:<sha>
                          │
                ┌─────────┴──────────┐
                │  GitHub Actions    │
                │  + GHCR (Packages) │
                └────────────────────┘
```

Ключевые изменения:

- `pg` удаляется из `compose.yaml`, вместо него — переменная
  `APP_CONFIG__DB__URL=postgresql+asyncpg://<user>:<pass>@<managed-host>:6432/<db>?ssl=require`,
  значение приходит из переменных окружения / `.env` на VM.
- `pg_network` исчезает; `pgadmin` остаётся в `rabbitmq_network` (или в
  отдельной internal-сети) и ходит в managed PG напрямую.
- Сети переименовываются в нейтральное `app_net` / `edge_net`.
- В `compose.yaml` секция `build:` заменяется на `image: ghcr.io/<org>/<repo>/<service>:<tag>`.
- `alembic upgrade head` (из `prestart.sh`) теперь применяется к managed PG —
  у пользователя БД должны быть права на DDL, либо миграции выносятся в
  отдельный CI-job, выполняющийся под админ-ролью.

---

## 3. PostgreSQL → Managed Service cloud.ru

### 3.1. Что нужно сделать в облаке

1. Создать инстанс **Managed PostgreSQL** в cloud.ru (рекомендуется версия,
   совместимая с используемыми типами/extensions; проверить
   `apscheduler[sqlalchemy]` — он требует только стандартных типов).
2. Создать БД `postgres` (или новую, например `iot_rpc`) и пользователя
   приложения (`app_user`) с правами `CONNECT`, `USAGE`, `CREATE` на схему.
3. Включить **TLS-only** подключения, скачать корневой сертификат cloud.ru.
4. Поместить инстанс в ту же VPC/сеть, что и compute-VM, либо настроить
   приватный IP/peering. Публичный IP у БД — выключен.
5. Настроить **бэкапы** (PITR) и алерты на CPU/диск/replication lag.

### 3.2. Что меняется в репозитории

- Удалить сервис `pg` из `compose.yaml` и volume `pgdata`.
- Удалить `pg_network` либо переименовать.
- В `compose.yaml` для `app1` и `pgadmin` прокинуть переменные окружения:
  ```
  APP_CONFIG__DB__URL=postgresql+asyncpg://app_user:${PG_PASSWORD}@${PG_HOST}:6432/iot_rpc?ssl=require
  APP_CONFIG__DB__SSLROOTCERT=/crt/cloudru-root.crt
  ```
- Добавить bind-mount корневого сертификата cloud.ru в контейнер `app1`
  (`./crt/cloudru-root.crt:/crt/cloudru-root.crt:ro`).
- В `app-service/config` проверить, что URL читается из окружения
  (используется `pydantic-settings`, префикс `APP_CONFIG__` — ок).
- Миграции: оставить `alembic upgrade head` в `prestart.sh`, но дать
  app-пользователю права на DDL (или выполнить миграции один раз вручную /
  отдельным CI-job под админ-ролью).

### 3.3. Откат / coexistence

Чтобы не ломать локальную разработку, оставить опциональный профиль:

```
services:
  pg:
    profiles: ["local-db"]
    image: postgres
    ...
```

Локально: `docker compose --profile local-db up`.
В проде: профиль не активируется, используется managed PG.

---

## 4. Переход на GitHub Packages (GHCR)

### 4.1. Стоит ли это делать (да, и вот почему)

| Критерий                       | Build на VM (сейчас)                        | Pull из GHCR (план)                                |
|--------------------------------|---------------------------------------------|----------------------------------------------------|
| Время деплоя                   | минуты (apt-get + сборка модулей)           | секунды (pull тонких слоёв)                        |
| Воспроизводимость              | плавающая (зависит от зеркал nginx.org)     | immutable digest, привязка к git-SHA               |
| Откат                          | `git checkout` + ребилд                     | `docker pull ghcr.io/...:<prev-sha>` мгновенно     |
| Нагрузка на прод-VM            | высокая (CPU/диск/сеть на сборку)           | минимальная                                        |
| Кэш                            | локальный, теряется при пересоздании VM     | shared cache в Actions + слои в registry           |
| Безопасность                   | секреты сборки на проде                     | сборка в изолированном runner’е                    |
| Сканирование уязвимостей       | нет                                         | trivy/grype в pipeline на каждый push              |
| Совместная сборка нескольких VM | каждая собирает заново                     | один артефакт на все                               |

**Вывод:** для трёх собственных образов (`app-service`, `nginx-jwt`,
`nginx-mutual`) переход на GHCR — однозначно эффективнее прямой сборки на
целевой машине. Сторонние образы (`rabbitmq:4-management`,
`dpage/pgadmin4`, `certbot/certbot`) тянутся напрямую с Docker Hub — их
дублировать в GHCR нужно только если цель — отвязаться от Docker Hub
rate-limit или зафиксировать digest (рекомендуется делать
`image: rabbitmq:4-management@sha256:...`).

### 4.2. Что публикуется

- `ghcr.io/<org>/iot-rpc-rest-app/app-service:<tag>`
- `ghcr.io/<org>/iot-rpc-rest-app/nginx-jwt:<tag>`
- `ghcr.io/<org>/iot-rpc-rest-app/nginx-mutual:<tag>`

Теги:
- `sha-<git-sha-short>` — для каждого пуша в `main` (используется в проде);
- `pr-<num>` — для PR (для smoke-тестов);
- `latest` — алиас на последний `main` (только для удобства, в compose
  использовать SHA-теги);
- `vX.Y.Z` — на git-tag (релизы).

### 4.3. Конфигурация Packages

- Видимость пакетов: **private** (если код внутренний) либо **public**
  (если ок раздавать образы); права читать выдаются compute-VM через
  PAT/`GITHUB_TOKEN` deploy-ключ.
- Включить **retention policy**: оставлять последние N untagged + все
  тегированные `vX.Y.Z`.
- Включить **vulnerability scanning** через Dependabot / Trivy action.

---

## 5. Сводный документ по деплою

### 5.1. Артефакты и репозитории

| Артефакт                                  | Где живёт                  | Как обновляется                                  |
|-------------------------------------------|----------------------------|--------------------------------------------------|
| Исходники приложения и Dockerfile         | этот репозиторий           | PR → `main`                                      |
| Образы (3 шт.)                            | GHCR (`ghcr.io/<org>/...`) | CI на push в `main` / git-tag                    |
| `compose.yaml` для прода                  | этот репозиторий, ветка `main` или отдельный `deploy/` | копируется на VM при деплое      |
| `.env` с секретами (PG, JWT, RMQ)         | только на VM (не в git)    | вручную при провижене + GitHub Environments      |
| Сертификаты `crt/`                        | секрет-хранилище cloud.ru / Vault, монтируются на VM | вне git                                  |
| Managed PostgreSQL                         | cloud.ru DBaaS             | terraform/UI                                     |
| Compute-VM                                 | cloud.ru IaaS              | terraform/UI + cloud-init                        |

### 5.2. Структура репозитория после изменений (предложение)

```
.
├── compose.yaml                # dev (с локальным pg по профилю)
├── deploy/
│   ├── compose.prod.yaml       # прод (image: ghcr.io/...)
│   ├── .env.example            # все переменные окружения (без значений)
│   └── README.md               # как накатить на VM
├── docker-files/...
├── .github/workflows/
│   ├── ci.yaml                 # lint + tests
│   ├── build-and-push.yaml     # сборка → GHCR
│   └── deploy.yaml             # деплой на VM
└── docs/deploy-plan.md         # этот файл
```

### 5.3. Переменные окружения (минимум)

```
# DB (managed)
APP_CONFIG__DB__URL=postgresql+asyncpg://app_user:***@pg-host:6432/iot_rpc?ssl=require
APP_CONFIG__DB__ECHO=0

# RabbitMQ (внутри compose)
APP_CONFIG__FASTSTREAM__URL=amqp://user:***@rabbitmq:5672//
RABBITMQ_DEFAULT_USER=user
RABBITMQ_DEFAULT_PASS=***

# pgadmin
PGADMIN_DEFAULT_EMAIL=admin@example.com
PGADMIN_DEFAULT_PASSWORD=***

# образы
IMAGE_TAG=sha-abcdef0
GHCR_OWNER=<org>
```

---

## 6. Промежуточный вариант «Build only» (без изменения инфраструктуры)

Цель — получить **первое реальное преимущество от CI** (быстрая,
воспроизводимая сборка образов в Actions с кэшированием и публикацией в
GitHub Packages), **не трогая** при этом текущую инфраструктуру:

- Managed PostgreSQL **не создаётся**, `pg` остаётся контейнером в
  `compose.yaml` как сейчас.
- Новые сервисы в cloud.ru **не заводятся**, VM/сети/сертификаты — те же.
- На VM подъём контейнеров остаётся **ручным, по одному сервису**, как и
  сейчас, — меняется только источник образа: вместо `docker compose build`
  делаем `docker compose pull` из GHCR.
- Никакого авто-CD, SSH-ключей в Actions, self-hosted runner’ов,
  Watchtower и т. п. — это всё откладывается до Вариантов A–D раздела 7.

Этот шаг — безопасный «прокси» к целевой архитектуре: он валидирует
сборочный pipeline и GHCR на боевых образах, не меняя поведение
прод-машины.

### 6.1. Что меняется в репозитории

1. **`.github/workflows/build-and-push.yaml`** — единственный новый
   workflow. Триггеры:
   - `push` в `main` (для основного потока);
   - `workflow_dispatch` (ручной перезапуск под выбранную ветку/SHA);
   - опционально `pull_request` — только `build` без `push`, чтобы
     ловить поломку сборки на ревью.

   Содержание job’ов (matrix по 3 образам — `app-service`, `nginx-jwt`,
   `nginx-mutual`):
   - `actions/checkout@v4`;
   - `docker/setup-buildx-action@v3` — buildx с поддержкой gha-кэша;
   - `docker/login-action@v3` к `ghcr.io` (`GITHUB_TOKEN`, permissions
     `packages: write`, `contents: read`);
   - `docker/metadata-action@v5` — теги `sha-<short>`, `latest` (только
     для `main`), `vX.Y.Z` (на git-tag);
   - `docker/build-push-action@v6`:
     - `context` и `file` для каждого Dockerfile,
     - `push: true` (для `pull_request` — `false`),
     - `cache-from: type=gha,scope=<svc>`,
     - `cache-to: type=gha,mode=max,scope=<svc>` —
       это и есть «Cashes», которые упомянуты в задаче: слои nginx-модуля,
       `apt-get`, `uv sync` будут кэшироваться между прогонами Actions.

2. **`compose.yaml`** — минимально-инвазивная правка для трёх собственных
   сервисов (`app1`, `nginx`, `nginx-mutual`): к существующей секции
   `build:` **добавляется** `image:` с тегом GHCR, например:
   ```
   app1:
     image: ghcr.io/<org>/iot-rpc-rest-app/app-service:${IMAGE_TAG:-latest}
     build:
       context: .
       dockerfile: docker-files/app-service/Dockerfile
     ...
   ```
   Поведение Docker Compose:
   - `docker compose build app1` — соберёт локально (старый ручной
     сценарий не ломается);
   - `docker compose pull app1` — скачает из GHCR (новый сценарий);
   - `docker compose up -d app1` без предварительного `pull/build` —
     возьмёт уже имеющийся локально образ с этим тегом.

   Сервисы без собственной сборки (`rabbitmq`, `pg`, `pgadmin`,
   `certbot`, `avahi`) **не трогаются**.

3. **`.env` на VM** (или `export` в shell) — добавляется одна переменная:
   ```
   IMAGE_TAG=sha-abcdef0
   ```
   По умолчанию (если не задана) compose возьмёт `:latest`. Для
   воспроизводимости в проде рекомендуется явно фиксировать SHA-тег.

4. **`docs/deploy-plan.md`** — этот раздел.

Чего **не** меняем на этом шаге:
- секции `pg`, `pgdata`, `pg_network` остаются как есть;
- `definitions.json`, пароли в `compose.yaml`, `./crt/*` — без изменений
  (вынос в секреты — следующий шаг);
- структура каталогов (`deploy/compose.prod.yaml` пока **не** создаётся);
- `docker-files/rmq/compose.yaml` не синхронизируется и не удаляется.

### 6.2. `.env` и конфигурация `app1` без локального билда

Это побочный, но **обязательный** шаг для «Build only»: без него `app1`
не поднимется из готового образа.

**Как это работает сейчас (as-is, неявно):**

- Конфиг приложения читается через `pydantic-settings`
  (`app-service/core/config.py`):
  ```
  model_config = SettingsConfigDict(
      env_file=(".env.template", ".env"),
      env_prefix="APP_CONFIG__",
      env_nested_delimiter="__",
  )
  ```
  Пути относительные → ищутся относительно CWD процесса, а это `/app`
  (из `WORKDIR /app`). То есть приложение ждёт файл по пути
  **`/app/.env` внутри контейнера**.
- В `Dockerfile` (`docker-files/app-service/Dockerfile`):
  ```
  COPY app-service /app
  ```
  При `docker compose build` на VM в образ копируется **всё содержимое**
  каталога `app-service/`, включая лежащий рядом `app-service/.env` (он
  сейчас существует на VM и используется). По сути `.env`
  **запекается в образ**.
- В `compose.yaml` у `app1` сейчас **нет** ни `env_file:`, ни
  `environment:`, ни bind-mount’а `.env` (только `./logs:/var/log/app`).
  Compose сам по себе **не** монтирует `./app-service/.env` в контейнер
  и **не** делает `env_file` неявно: автоматический `./.env` рядом с
  `compose.yaml` используется только для подстановки `${VAR}` в сам
  yaml, в контейнер он не попадает.

**Что произойдёт в варианте «Build only» без правок:** образ собирается
в Actions из чистого checkout, где файла `app-service/.env` нет (он не в
git). В образе будет только `/app/.env.template` (значения-заглушки),
реального `/app/.env` не будет, переменные окружения тоже никто не
прокинет → `app1` либо упадёт на обязательных полях (`db.url`,
`faststream.url`), либо стартанёт с заглушками, что хуже.

**Минимальная неконфликтующая правка `compose.yaml`** для `app1`:

```
app1:
  image: ghcr.io/<org>/iot-rpc-rest-app/app-service:${IMAGE_TAG:-latest}
  build:
    context: .
    dockerfile: docker-files/app-service/Dockerfile
  env_file:
    - ./app-service/.env
  # остальное без изменений
```

Почему это **не конфликтует** ни со старым, ни с новым сценарием:

- При локальном `docker compose build app1` файл, как и раньше,
  попадёт в образ через `COPY app-service /app`, плюс те же значения
  будут переданы в контейнер как переменные окружения через `env_file`.
  Переменные окружения в `pydantic-settings` имеют приоритет над
  значениями из `env_file=` внутри `SettingsConfigDict`, поэтому
  результат идентичный — никаких новых значений, просто другой канал
  доставки тех же.
- При `docker compose pull app1` (Build only) образ из GHCR не содержит
  `/app/.env`, но `env_file: ./app-service/.env` прокинет те же
  переменные в окружение контейнера → `pydantic-settings` подхватит их
  напрямую из ENV. `/app/.env.template` останется как fallback значения
  по умолчанию, как и раньше.
- Если `app-service/.env` на VM почему-то отсутствует, compose упадёт с
  понятной ошибкой `env file ... not found` ещё до старта контейнера —
  это лучше, чем тихо стартовать с заглушками.

**Расположение файла на VM не меняется:** остаётся
`/<repo>/app-service/.env` (там, где он лежит сейчас и где его ждёт
текущий ручной `docker compose build`). В git его по-прежнему **не
коммитим** — `.env.template` достаточно как образец.

**Чего этот шаг осознанно не делает:**

- не выносит секреты в Docker/GitHub secrets — это следующий шаг;
- не убирает `COPY app-service /app` из Dockerfile (так старый сценарий
  с локальной сборкой остаётся 1-в-1 как сейчас, и `.env` так же
  «запекается» — это плата за минимальность изменения);
- не трогает `nginx`, `nginx-mutual` и сторонние сервисы — у них своих
  `.env` нет.

### 6.3. Конфигурация GitHub Packages

- Видимость пакетов на старте — **public** (проще: `docker pull` с VM
  работает без логина) **или** **private** + один PAT с `read:packages`
  на VM (`docker login ghcr.io -u <bot> --password-stdin`).
  Рекомендуется сразу **private** + PAT, чтобы потом не «разворачивать»
  обратно.
- Retention: оставлять последние ~20 untagged + все тегированные
  (настраивается в Settings → Packages → конкретный package).
- Никаких GitHub Environments, reviewers, secrets кроме `GITHUB_TOKEN`
  и (опционально) `GHCR_READ_PAT` для VM — пока не нужно.

### 6.4. Ручной деплой на VM (новый флоу, по сервисам)

Подключение по SSH к существующей VM, в каталоге репозитория
(`/opt/iot-rpc-rest-app` или где он лежит сейчас):

**Предусловие (одноразовое):** на VM должен лежать
`./app-service/.env` с боевыми значениями (как сейчас) — он
прокидывается в `app1` через `env_file:` (см. §6.2). Если файла нет,
`docker compose up -d app1` упадёт с `env file ... not found` ещё до
старта контейнера.

```bash
# 1. Подтянуть актуальные compose.yaml / конфиги / миграции
git pull

# 2. (один раз) залогиниться в GHCR, если пакеты private
echo "$GHCR_READ_PAT" | docker login ghcr.io -u <bot-user> --password-stdin

# 3. Зафиксировать тег образов на этот деплой (короткий git SHA из main)
export IMAGE_TAG=sha-abcdef0

# 4. По одному сервису — pull + up (как сейчас делается build + up)
docker compose pull app1
docker compose up -d app1

docker compose pull nginx
docker compose up -d nginx

docker compose pull nginx-mutual
docker compose up -d nginx-mutual

# 5. Проверки и чистка
docker compose ps
docker image prune -f
```

Для сторонних сервисов (`rabbitmq`, `pg`, `pgadmin`, `certbot`,
`avahi`) — всё как сейчас: `docker compose up -d <svc>` по необходимости,
без `build`.

### 6.5. Сравнение со старым ручным флоу

| Шаг                                  | Сейчас (ручная сборка)                | Build only (этот раздел)             |
|--------------------------------------|---------------------------------------|--------------------------------------|
| Получение кода/конфигов на VM        | `git pull`                            | `git pull` (без изменений)           |
| Сборка образа                        | `docker compose build <svc>` на VM    | в Actions, кэш `type=gha`            |
| Получение образа на VM               | — (собирается локально)               | `docker compose pull <svc>`          |
| Подъём контейнера                    | `docker compose up -d <svc>`          | `docker compose up -d <svc>`         |
| Кто инициирует деплой                | человек на VM                         | человек на VM (CI только собирает)   |
| Откат                                | `git checkout` + ребилд               | `IMAGE_TAG=sha-<prev>` + `pull/up`   |
| Время на VM                          | минуты (apt/uv/модули nginx)          | секунды (тонкие слои pull)           |
| Поведение `docker compose build`     | работает                              | **продолжает работать** (поле `build:` сохранено) |

### 6.6. Выгоды и ограничения промежуточного варианта

**Что мы получаем:**

- сборка перестаёт грузить прод-VM (CPU/диск/сеть);
- образы становятся immutable-артефактами с привязкой к git-SHA →
  предсказуемый откат;
- появляется кэш слоёв (`type=gha`) — повторные сборки в Actions
  становятся быстрыми;
- проверена интеграция с GHCR на боевых образах перед более
  серьёзными шагами (Managed PG, авто-CD).

**Что осознанно остаётся «как сейчас»:**

- `pg` всё ещё в Docker, бэкап/HA не улучшаются;
- секреты по-прежнему в `compose.yaml` / `definitions.json`;
- деплой по-прежнему ручной и пошаговый — это **намеренно**: исключаем
  риск «сломать прод одним зелёным workflow»;
- сторонние образы (`rabbitmq`, `postgres`, `pgadmin4`, `certbot`,
  `ydkn/avahi`) тянутся с Docker Hub как раньше — никакого зеркалирования
  в GHCR на этом шаге.

### 6.7. Чеклист «Build only сделано»

- [ ] `.github/workflows/build-and-push.yaml` собирает 3 образа и пушит
      в GHCR с тегами `sha-<sha>` и `latest` (для `main`).
- [ ] В `compose.yaml` у `app1`, `nginx`, `nginx-mutual` добавлено поле
      `image: ghcr.io/.../<svc>:${IMAGE_TAG:-latest}` рядом с `build:`.
- [ ] У `app1` в `compose.yaml` добавлен `env_file: ./app-service/.env`
      (см. §6.2); файл `app-service/.env` присутствует на VM и не
      закоммичен в git.
- [ ] На VM выполнен разовый `docker login ghcr.io` (если private).
- [ ] Прогнан ручной флоу `git pull` → `docker compose pull <svc>` →
      `docker compose up -d <svc>` по каждому из трёх сервисов.
- [ ] Проверено, что старый сценарий (`docker compose build <svc>` +
      `up -d <svc>`) по-прежнему работает на случай fallback.
- [ ] Документирован в `docs/deploy-plan.md` (этот раздел) и при
      необходимости — короткой памяткой в `README` репозитория.

После того как этот шаг отработан и стабилизирован, можно переходить к
разделу 7 (полная автоматизация деплоя) и к выносу PG в managed-сервис
(раздел 3).

---

## 7. Варианты максимальной автоматизации деплоя

Ниже — три варианта от самого простого к самому «взрослому». Можно
комбинировать (например, начать с (A), переехать на (B) при росте парка
машин).

### Вариант A. GitHub Actions + SSH push (рекомендуется как стартовый)

**Workflow’ы:**

1. `ci.yaml` — на каждый PR: `uv sync`, `pytest`, `black --check`,
   `docker build` без push (чтобы не публиковать недопроверенное), Trivy
   scan локально собранных образов.
2. `build-and-push.yaml` — на push в `main` и git-tag:
   - `docker/setup-buildx-action`
   - `docker/login-action` к `ghcr.io` (`GITHUB_TOKEN` с правом
     `packages: write`)
   - matrix по 3 образам: `app-service`, `nginx-jwt`, `nginx-mutual`
   - `docker/build-push-action` с `cache-from/to: type=gha` и тегами
     `sha-<sha>`, `latest` (и `vX.Y.Z` на тег)
3. `deploy.yaml` — `workflow_run` после успешного `build-and-push`
   (или ручной `workflow_dispatch` с выбором тега, или автотриггер на
   `main`):
   - использует **GitHub Environment** `production` с required reviewers
     (защита от случайного деплоя);
   - `appleboy/ssh-action` или нативный `ssh -i $KEY` на VM:
     ```
     cd /opt/iot-rpc-rest-app
     export IMAGE_TAG=sha-${{ github.sha }}
     echo "$GHCR_TOKEN" | docker login ghcr.io -u <bot> --password-stdin
     docker compose -f compose.prod.yaml pull
     docker compose -f compose.prod.yaml up -d
     docker image prune -f
     ```
   - секреты (`SSH_KEY`, `GHCR_TOKEN`, `VM_HOST`) — в `Environments → production`.

**Плюсы:** просто, бесплатно, не требует агента на VM.
**Минусы:** SSH-ключ в Actions; одна VM = одна цель; нет «pull-модели».

### Вариант B. Self-hosted GitHub Actions runner на прод-VM

На VM ставится `actions/runner` (под отдельным юзером, в systemd),
регистрируется на репозиторий с label `prod`. Workflow `deploy.yaml`
содержит `runs-on: [self-hosted, prod]` и делает локально:

```
docker compose -f compose.prod.yaml pull
docker compose -f compose.prod.yaml up -d
```

**Плюсы:**
- никаких SSH-ключей в облаке;
- runner сам ходит в GitHub (исходящие 443) — в прод-VM можно вообще
  закрыть входящий SSH;
- легко расширяется на несколько VM (добавить ещё runner с тем же label).

**Минусы:** runner = новый сервис, который надо обновлять; даёт CI-доступ
на прод (нужен ограниченный юзер + sudo-правила только на `docker compose`).

### Вариант C. Pull-модель: Watchtower / Diun + private GHCR

На VM крутится `containrrr/watchtower`, настроенный на private GHCR
(`REPO_USER`+`REPO_PASS` = bot+PAT), интервал, например, 60 сек. CI просто
пушит новый тег `latest` (или используется `app1:main`), Watchtower сам
обнаруживает новый digest и перезапускает контейнеры.

**Плюсы:** ноль кастомного кода деплоя, GitHub ничего не знает про VM.
**Минусы:** меньше контроля (нет approve-флоу, нет порядка миграций),
сложнее координировать `alembic upgrade` с рестартом app1, нет «откатить
на конкретный SHA» по кнопке.

### Вариант D. Ansible / Terraform + GitHub Actions (для нескольких VM)

- **Terraform** провижит cloud.ru: VPC, Managed PG, compute-VM, security
  groups, DNS, объектное хранилище под бэкапы.
- **Ansible-playbook** (`deploy.yaml` в Actions вызывает `ansible-playbook`):
  - устанавливает Docker, добавляет deploy-юзера;
  - кладёт `compose.prod.yaml` и `.env` (значения из Ansible Vault или
    GitHub Secrets);
  - монтирует сертификаты из секрет-хранилища;
  - выполняет `docker login ghcr.io` + `docker compose pull/up -d`;
  - идемпотентно — можно безопасно перезапускать.

**Плюсы:** масштабируется на пул машин, единая декларация инфры,
полностью воспроизводимо (disaster recovery = `terraform apply` +
`ansible-playbook`).
**Минусы:** требует подготовки и поддержки IaC-репо.

### Сравнение вариантов

| Вариант             | Сложность | Кол-во VM | Нужен агент на VM | Approve-флоу | Откат                       |
|---------------------|-----------|-----------|--------------------|--------------|-----------------------------|
| A. SSH из Actions   | низкая    | 1–2       | нет                | да (Env)     | дискретный, по тегу         |
| B. self-hosted runner | средняя | 1–N       | да (runner)        | да (Env)     | дискретный, по тегу         |
| C. Watchtower       | низкая    | 1–N       | да (watchtower)    | нет          | смена `latest`-тега         |
| D. Ansible+Terraform| высокая   | N         | нет (push) / опц.  | да           | повторный `ansible-playbook`|

**Рекомендация:** старт с **A**, миграция в **B** при появлении второй
машины или необходимости закрыть входящий SSH; **D** — когда инфра
расширится до нескольких сред (stage/prod) или нескольких регионов.

---

## 8. Пошаговый план миграции

1. **CI-фундамент** (PR в этот репозиторий):
   - добавить `.github/workflows/ci.yaml` (uv sync, pytest, black);
   - добавить `.github/workflows/build-and-push.yaml` с публикацией трёх
     образов в GHCR по тегу `sha-<sha>` и `latest`;
   - проверить, что образы собираются и появляются в GHCR.
2. **Подготовка `deploy/compose.prod.yaml`**:
   - убрать `build:`, заменить на `image: ghcr.io/<org>/iot-rpc-rest-app/<svc>:${IMAGE_TAG}`;
   - убрать сервис `pg` и volume `pgdata`;
   - перенести все секреты в `${VAR}` и описать в `deploy/.env.example`;
   - убрать `avahi` из прод-профиля (или оставить, если VM поддерживает host-network);
   - синхронизировать `docker-files/rmq/compose.yaml` или удалить как устаревший.
3. **cloud.ru, инфраструктура**:
   - создать Managed PostgreSQL, БД, пользователя, выдать TLS-сертификат;
   - создать compute-VM (Ubuntu LTS), поставить Docker + compose plugin;
   - открыть только 80/443/4443 наружу, всё остальное — внутри VPC.
4. **Первичный деплой вручную**:
   - залить на VM `deploy/compose.prod.yaml` и `.env`;
   - `docker login ghcr.io`, `docker compose -f compose.prod.yaml up -d`;
   - убедиться, что `alembic upgrade head` отработал на managed PG.
5. **Автоматизация (Вариант A)**:
   - добавить `.github/workflows/deploy.yaml` с GitHub Environment
     `production` и required reviewers;
   - проверить деплой через `workflow_dispatch`;
   - после успеха включить автотриггер по `push` в `main`.
6. **Бэкапы и наблюдаемость**:
   - бэкапы PG — встроенные cloud.ru;
   - бэкап `rabbitmq_data` — периодический snapshot диска VM или
     `rabbitmqctl export_definitions` в объектное хранилище;
   - логи `app1` в `./logs` — пробросить во встроенную систему логов
     cloud.ru или в Loki/ELK;
   - healthchecks compose уже есть для `pg`/`rabbitmq` — добавить для `app1`
     и `nginx`.
7. **Безопасность**:
   - убрать дефолтные пароли (`pgpass`, `root`, `admin`) из репозитория;
   - сертификаты из `./crt/` исключить из git (если ещё в нём), хранить
     в секрет-хранилище;
   - включить Trivy/grype на каждый build, Dependabot для `pyproject.toml`
     и actions; включить secret scanning.

---

## 9. Чеклист «сделано»

- [ ] Managed PostgreSQL в cloud.ru поднят, доступен из VPC, TLS-only.
- [ ] Compute-VM в cloud.ru, Docker установлен, входящий — только 80/443/4443.
- [ ] Все три собственных образа публикуются в GHCR с тегом `sha-*`.
- [ ] `deploy/compose.prod.yaml` использует `image:` из GHCR, без `build:`.
- [ ] `pg` и `pgdata` удалены из прод-compose; `app1`/`pgadmin` ходят в managed PG.
- [ ] Секреты вынесены в `.env` на VM / GitHub Environments, в git нет паролей.
- [ ] CI: lint + tests + build + push + (опц.) Trivy зелёные.
- [ ] CD: `deploy.yaml` с required reviewers, успешный прогон end-to-end.
- [ ] Бэкапы PG и RMQ настроены, проверено восстановление.
- [ ] Документация (`deploy/README.md`) описывает «как накатить с нуля».

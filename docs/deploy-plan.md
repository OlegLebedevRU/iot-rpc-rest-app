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
| `app1`          | `ghcr.io/oleglebedevru/iot-rpc-rest-app/app-service:${IMAGE_TAG:-latest}` + build fallback `docker-files/app-service/Dockerfile` | `rabbitmq_network`, `pg_network` | — | FastAPI/FastStream приложение, поднимается через `prestart.sh`+`appup`, env из `./app-service/.env` |
| `rabbitmq`      | `rabbitmq:4-management`                     | `rabbitmq_network`                 | `5672`, `8883`                     | AMQP + MQTT-плагин, конфиг и `definitions.json` через bind-mount           |
| `pg`            | `postgres`                                  | `pg_network`                       | `5432`                             | PostgreSQL с `pgdata` volume                                               |
| `pgadmin`       | `dpage/pgadmin4`                            | `pg_network`                       | —                                  | UI к Postgres                                                              |
| `nginx`         | `ghcr.io/oleglebedevru/iot-rpc-rest-app/nginx-jwt:${IMAGE_TAG:-latest}` + build fallback `docker-files/nginx-jwt/Dockerfile` | `rabbitmq_network`, `pg_network` | `80`, `443`, `1443`, `1444` | Внешний reverse-proxy + JWT-модуль, внешние сертификаты через bind-mount |
| `nginx-mutual`  | `ghcr.io/oleglebedevru/iot-rpc-rest-app/nginx-mutual:${IMAGE_TAG:-latest}` + build fallback `docker-files/nginx-mutual/Dockerfile` | `rabbitmq_network`, `pg_network` | `4443` | Внутренний mTLS reverse-proxy для устройств, legacy-сертификаты через bind-mount |
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
  nginx mainline `1.31.1*` из репозитория nginx.org, выкачивает бинарный
  модуль `ngx-http-auth-jwt-module 2.5.0` (`libjwt-1.18.4`, сборка под
  nginx `1.31.1`) с GitHub Releases, создаёт совместимый symlink
  `libjwt.so.2` → `libjwt.so.0`, конфиг nginx пишется heredoc’ом в
  Dockerfile и валидируется через `nginx -t`. Legacy OpenSSL/SECLEVEL=0
  в этом образе не включаются: контур для legacy-сертификатов вынесен в
  отдельный `nginx-mutual`.
- **`docker-files/nginx-mutual/Dockerfile`** — `debian:bookworm-slim` + nginx
  из stock-репозитория, включает legacy provider OpenSSL и `SECLEVEL=0`,
  копирует публичный `docker-files/nginx-mutual/ca_legacy.crt` и
  `nginx-configs/.../internal_ssl.conf`; секретные сертификаты из `./crt/`
  в образ не копируются и монтируются в рантайме.
- **`docker-files/rmq/compose.yaml`** — отдельный compose только для RabbitMQ
  (по сути дубликат сервиса `rabbitmq` из корневого compose — кандидат на
  удаление либо синхронизацию).

### 1.3. Исторически устранённые и оставшиеся слабые места DevOps

1. **Фактический сценарий деплоя**: основным и наиболее надёжным методом деплоя
   является локальная сборка на целевой машине через `docker compose build app1`
   с последующим перезапуском `docker compose up -d --no-deps app1`. Сборка и
   деплой готовых пакетов через GitHub Packages (GHCR) сохранены как альтернативный
   вариант (применяемый только при наличии прямого указания).
2. **Тегирование и откат**: собственные образы поддерживают версионирование
   через Git-коммиты (для локальной сборки) и immutable-артефакты в GHCR с
   тегами `sha-*`, branch, `latest` (при использовании registry).
3. **Секреты в открытом виде**: пароли БД и RabbitMQ зашиты в `compose.yaml`
   и `definitions.json`, сертификаты лежат в `./crt/` рядом с кодом.
4. **PostgreSQL в одном контейнере с приложением** — нет независимого
   бэкапа/HA/мониторинга, том `pgdata` делит судьбу с VM.
5. **Дублирование compose-файлов** (`compose.yaml` vs `docker-files/rmq/compose.yaml`).
6. **CI/CD покрыт частично**: `.github/workflows/build-and-push.yaml` уже
   собирает и публикует три собственных образа в GHCR, но отдельные
   workflow для lint/test/security scan и автоматического CD ещё не добавлены.
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
                          │  docker pull ghcr.io/oleglebedevru/iot-rpc-rest-app/<svc>:<sha>
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
- В production-compose секция `build:` заменяется на
  `image: ghcr.io/oleglebedevru/iot-rpc-rest-app/<service>:<tag>`; в
  текущем корневом `compose.yaml` для обратной совместимости уже оставлены
  оба поля: `image:` для pull из GHCR и `build:` как fallback локальной сборки.
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

## 4. GitHub Packages (GHCR): фактическое состояние

### 4.1. Стоит ли это делать (да, и вот почему)

| Критерий                       | Build на VM (fallback)                      | Pull из GHCR (сейчас)                              |
|--------------------------------|---------------------------------------------|----------------------------------------------------|
| Время деплоя                   | минуты (apt-get + сборка модулей)           | секунды (pull тонких слоёв)                        |
| Воспроизводимость              | плавающая (зависит от зеркал nginx.org)     | immutable digest, привязка к git-SHA               |
| Откат                          | `git checkout` + ребилд                     | `docker pull ghcr.io/...:<prev-sha>` мгновенно     |
| Нагрузка на прод-VM            | высокая (CPU/диск/сеть на сборку)           | минимальная                                        |
| Кэш                            | локальный, теряется при пересоздании VM     | shared cache в Actions + слои в registry           |
| Безопасность                   | секреты сборки на проде                     | сборка в изолированном runner’е                    |
| Сканирование уязвимостей       | нет                                         | trivy/grype в pipeline на каждый push              |
| Совместная сборка нескольких VM | каждая собирает заново                     | один артефакт на все                               |

**Фактический статус:** для трёх собственных образов (`app-service`,
`nginx-jwt`, `nginx-mutual`) переход на GHCR уже выполнен. Образы
публикуются workflow `.github/workflows/build-and-push.yaml` в public
GitHub Packages namespace `ghcr.io/oleglebedevru/iot-rpc-rest-app`, а
последние ручные деплои на VM выполняются через `docker compose pull` +
`docker compose up -d`. Локальная сборка на VM сохранена как fallback за
счёт оставленных секций `build:` в `compose.yaml`.

Сторонние образы (`rabbitmq:4-management`,
`dpage/pgadmin4`, `certbot/certbot`) тянутся напрямую с Docker Hub — их
дублировать в GHCR нужно только если цель — отвязаться от Docker Hub
rate-limit или зафиксировать digest (рекомендуется делать
`image: rabbitmq:4-management@sha256:...`).

### 4.2. Что публикуется

- `ghcr.io/oleglebedevru/iot-rpc-rest-app/app-service:<tag>`
- `ghcr.io/oleglebedevru/iot-rpc-rest-app/nginx-jwt:<tag>`
- `ghcr.io/oleglebedevru/iot-rpc-rest-app/nginx-mutual:<tag>`

Теги:
- `sha-<git-sha-short>` — для каждого push/tag/manual build
  (рекомендуемый тег для воспроизводимого деплоя);
- имя ветки (`master`, `main` и т. п.) — генерируется
  `docker/metadata-action` для branch builds;
- `latest` — алиас на последнюю default-ветку (только для удобства, в compose
  использовать SHA-теги);
- `vX.Y.Z` и `vX.Y` — на semver git-tag `v*.*.*` (релизы).

Для `pull_request` workflow выполняет только build-проверку (`push: false`),
поэтому PR-образы в GHCR не публикуются.

### 4.3. Конфигурация Packages

- Видимость пакетов: **public**. VM может выполнять `docker compose pull`
  без `docker login ghcr.io`. Если в будущем пакеты будут переведены в
  private, на VM понадобится PAT с `read:packages`.
- Включить **retention policy**: оставлять последние N untagged + все
  тегированные `vX.Y.Z`.
- Включить **vulnerability scanning** через Dependabot / Trivy action.

---

## 5. Сводный документ по деплою

### 5.1. Артефакты и репозитории

| Артефакт                                  | Где живёт                  | Как обновляется                                  |
|-------------------------------------------|----------------------------|--------------------------------------------------|
| Исходники приложения и Dockerfile         | этот репозиторий           | PR → `master` / `main`                           |
| Образы (3 шт.)                            | GHCR (`ghcr.io/oleglebedevru/iot-rpc-rest-app/...`) | CI на push в `master`/`main`, git-tag и ручной запуск |
| `compose.yaml` для прода                  | этот репозиторий, ветка `master` или отдельный `deploy/` | копируется/обновляется на VM при деплое |
| `.env` с секретами (PG, JWT, RMQ)         | только на VM (не в git)    | вручную при провижене + GitHub Environments      |
| Сертификаты `crt/`                        | секрет-хранилище cloud.ru / Vault, монтируются на VM | вне git                                  |
| Managed PostgreSQL                         | cloud.ru DBaaS             | terraform/UI                                     |
| Compute-VM                                 | cloud.ru IaaS              | terraform/UI + cloud-init                        |

RabbitMQ device users/ACL are runtime state derived from PostgreSQL. If the
RabbitMQ data volume is lost or replaced, `app-service` re-applies device users,
permissions and topic-permissions on startup. Operational recovery details are
documented in [`docs/rabbitmq-acl-recovery.md`](rabbitmq-acl-recovery.md).

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
```

---

## 6. Промежуточный вариант «Build only» — внедрённый текущий режим

Цель этого шага была — получить **первое реальное преимущество от CI**
(быстрая, воспроизводимая сборка образов в Actions с кэшированием и
публикацией в GitHub Packages), **не трогая** при этом текущую
инфраструктуру.

**Фактический статус:** шаг внедрён. Три собственных образа уже хранятся
в public GHCR namespace `ghcr.io/oleglebedevru/iot-rpc-rest-app`, а
последние деплои выполняются с VM через `docker compose pull` из GHCR.

- Managed PostgreSQL **не создаётся**, `pg` остаётся контейнером в
  `compose.yaml` как сейчас.
- Новые сервисы в cloud.ru **не заводятся**, VM/сети/сертификаты — те же.
- На VM подъём контейнеров остаётся **ручным, по одному сервису**, как и
  сейчас, — источник образа уже изменён: вместо `docker compose build`
  используется `docker compose pull` из GHCR.
- Никакого авто-CD, SSH-ключей в Actions, self-hosted runner’ов,
  Watchtower и т. п. — это всё откладывается до Вариантов A–D раздела 7.

Этот шаг — безопасный «прокси» к целевой архитектуре: он уже валидирует
сборочный pipeline и GHCR на боевых образах, не меняя инфраструктуру
прод-машины.

### 6.1. Что меняется в репозитории

1. **`.github/workflows/build-and-push.yaml`** — текущий workflow сборки
   и публикации образов. Триггеры:
   - `push` в `master` и `main`;
   - git tags `v*.*.*`;
   - `workflow_dispatch` (ручной перезапуск под выбранную ветку/SHA);
   - `pull_request` в `master`/`main` — только `build` без `push`, чтобы
     ловить поломку сборки на ревью.

   Содержание job’ов (matrix по 3 образам — `app-service`, `nginx-jwt`,
   `nginx-mutual`):
   - `actions/checkout@v4`;
   - `docker/setup-buildx-action@v3` — buildx с поддержкой gha-кэша;
   - `docker/login-action@v3` к `ghcr.io` (`GITHUB_TOKEN`, permissions
     `packages: write`, `contents: read`);
   - `docker/metadata-action@v5` — теги `sha-<short>`, имя ветки,
     `latest` (только для default branch), `vX.Y.Z` и `vX.Y` (на semver
     git-tag);
   - `docker/build-push-action@v6`:
     - `context` и `file` для каждого Dockerfile,
     - `push: true` (для `pull_request` — `false`),
     - `cache-from: type=gha,scope=<svc>`,
     - `cache-to: type=gha,mode=max,scope=<svc>` —
       это и есть кэш слоёв: слои nginx-модуля,
       `apt-get`, `uv sync` будут кэшироваться между прогонами Actions.

2. **`compose.yaml`** — минимально-инвазивная правка для трёх собственных
   сервисов (`app1`, `nginx`, `nginx-mutual`): к существующей секции
   `build:` **добавлено** `image:` с тегом GHCR, например:
   ```
   app1:
     image: ghcr.io/oleglebedevru/iot-rpc-rest-app/app-service:${IMAGE_TAG:-latest}
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

3. **`.env` на VM** (или `export` в shell) — используется переменная:
   ```
   IMAGE_TAG=sha-abcdef0
   ```
   По умолчанию (если не задана) compose возьмёт `:latest`. Для
   воспроизводимости в проде рекомендуется явно фиксировать SHA-тег.

4. **`docs/deploy-plan.md`** — этот раздел поддерживается как описание
   текущего режима и следующих шагов.

Чего **не** меняем на этом шаге:
- секции `pg`, `pgdata`, `pg_network` остаются как есть;
- `definitions.json`, пароли в `compose.yaml`, `./crt/*` — без изменений
  (вынос в секреты — следующий шаг);
- структура каталогов (`deploy/compose.prod.yaml` пока **не** создаётся);
- `docker-files/rmq/compose.yaml` не синхронизируется и не удаляется.

### 6.2. `.env` и конфигурация `app1` без локального билда

Это побочный, но **обязательный** шаг для «Build only»: без него `app1`
не поднимется из готового образа.

**Как это работало до правки Build only (as-is, неявно):**

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
- В `compose.yaml` у `app1` тогда **не было** ни `env_file:`, ни
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

**Внесённая минимальная неконфликтующая правка `compose.yaml`** для `app1`:

```
app1:
  image: ghcr.io/oleglebedevru/iot-rpc-rest-app/app-service:${IMAGE_TAG:-latest}
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

### 6.2.1. Сертификаты `nginx-mutual` через bind mount (обязательное условие)

`nginx-jwt` исторически тянет секретные сертификаты в контейнер
bind-mount’ом из `./crt/` (см. секцию `nginx` в `compose.yaml`), поэтому
его образ собирается в Actions без проблем — в build-context сертификаты
не нужны.

`nginx-mutual` же раньше копировал секретные файлы прямо в образ:

```
COPY crt/legacy_cert_dev_leo4_ru.crt /crt/legacy_cert_dev_leo4_ru.crt
COPY crt/key_0000.pem /crt/server_key.pem
```

В ручном сценарии «build на VM» это работало, потому что каталог
`./crt/` существует на прод-VM. В CI (Actions, чистый checkout) каталога
`crt/` в репозитории нет → `docker buildx build` падает с

```
ERROR: failed to compute cache key: "/crt/key_0000.pem": not found
```

Чтобы «Build only» вообще заработал, `nginx-mutual` приводится к той же
схеме, что и `nginx-jwt` — bind mount сертификатов в рантайме:

1. **`docker-files/nginx-mutual/Dockerfile`**:
   - убраны `COPY crt/legacy_cert_dev_leo4_ru.crt …` и
     `COPY crt/key_0000.pem …`;
   - оставлен `RUN mkdir -p /crt /usr/lib/ssl` (точка монтирования);
   - оставлен `COPY docker-files/nginx-mutual/ca_legacy.crt …` —
     этот файл лежит в репозитории и секретом не является;
   - убран `RUN nginx -t` на этапе сборки: `ssl_certificate` /
     `ssl_certificate_key` указывают на файлы из bind-mount’а, которых
     при build’е в Actions нет. Валидация конфига всё равно произойдёт
     при старте контейнера на VM, где сертификаты уже примонтированы.
2. **`compose.yaml`**, секция `nginx-mutual` — добавлены `volumes:`
   ровно с теми путями, которые ждёт `internal_ssl.conf`:
   ```
   volumes:
     - ./crt/legacy_cert_dev_leo4_ru.crt:/crt/legacy_cert_dev_leo4_ru.crt:ro
     - ./crt/key_0000.pem:/crt/server_key.pem:ro
   ```

Файлы на VM лежат там же, где сейчас (`./crt/legacy_cert_dev_leo4_ru.crt`,
`./crt/key_0000.pem`), в git они по-прежнему не коммитятся. После этой
правки CI workflow `build-and-push` собирает все три образа без обращения
к `./crt/`, а на VM поведение `nginx-mutual` остаётся идентичным —
сертификаты просто доставляются другим каналом (mount вместо COPY).

### 6.3. Конфигурация GitHub Packages

- Видимость пакетов сейчас — **public**. `docker pull` / `docker compose pull`
  с VM работает без `docker login ghcr.io`.
- Если в будущем пакеты переводятся в **private**, на VM понадобится один
  PAT с `read:packages` (`docker login ghcr.io -u <bot> --password-stdin`).
- Retention: оставлять последние ~20 untagged + все тегированные
  (настраивается в Settings → Packages → конкретный package).
- Для текущего Build only режима не нужны GitHub Environments, reviewers,
  SSH-секреты или `GHCR_READ_PAT`: `GITHUB_TOKEN` используется только в
  Actions для публикации public-пакетов.

### 6.4. Ручной деплой на VM (фактический флоу по сервисам)

Для проведения ручных деплоев на целевой VM сформированы два специализированных пошаговых регламента:
1. **Деплой только логики приложения (`app1`)**:
   [`manual-app1-deploy-runbook.md`](manual-app1-deploy-runbook.md) — регламент для задач уровня приложения (сборка на хосте, GHCR по требованию, backup `.env`, rollback, изоляция БД и брокера).
2. **Деплой инфраструктуры брокера RabbitMQ, межсервисных сетей и прокси**:
   [`manual-infra-and-rmq-deploy-runbook.md`](manual-infra-and-rmq-deploy-runbook.md) — регламент для изменений `rmq/rabbitmq.conf` (слушатели портов, plain MQTT 1883), `rmq/definitions.json` (сервисные пользователи, топиковые ACL `amq.topic`), общих Docker-сетей (`iot_rabbitmq_network`), прокси `nginx`/`nginx-mutual`, с сохранением томов данных (`rabbitmq_data`, `pgdata`) и сессий устройств.

Подключение по SSH к целевой VM, в каталог репозитория (`/home/user1/iot-rpc-rest-app`):

**Предусловие:** на VM должен лежать `./app-service/.env` с боевыми значениями — он
прокидывается в `app1` через `env_file:` (см. §6.2). Если файла нет,
`docker compose up -d app1` упадёт с ошибкой до старта контейнера.

#### Основной сценарий (локальная сборка на хосте):

```bash
# 1. Подтянуть актуальный код / миграции / конфиги
git fetch origin && git checkout <target_branch_or_commit>

# 2. Собрать образ сервиса напрямую на VM
sudo docker compose build app1

# 3. Безопасно перезапустить только сервис приложения без зависимостей
sudo docker compose up -d --no-deps app1

# 4. Проверить статус и логи
sudo docker compose ps app1
sudo docker compose logs --tail=100 app1
```

#### Альтернативный сценарий (GHCR — только при прямом указании):

```bash
# 1. Зафиксировать тег образа (короткий git SHA из master/main)
export IMAGE_TAG=sha-abcdef0

# 2. Pull + up целевого сервиса
sudo env IMAGE_TAG=$IMAGE_TAG docker compose pull app1
sudo env IMAGE_TAG=$IMAGE_TAG docker compose up -d --no-deps app1
```

Для сторонних сервисов (`rabbitmq`, `pg`, `pgadmin`, `certbot`,
`avahi`) — `docker compose up -d <svc>` по необходимости, без `build`.

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
- интеграция с GHCR проверена на боевых образах и последних ручных
  деплоях перед более серьёзными шагами (Managed PG, авто-CD).

**Что осознанно остаётся «как сейчас»:**

- `pg` всё ещё в Docker, бэкап/HA не улучшаются;
- секреты по-прежнему в `compose.yaml` / `definitions.json`;
- деплой по-прежнему ручной и пошаговый — это **намеренно**: исключаем
  риск «сломать прод одним зелёным workflow»;
- сторонние образы (`rabbitmq`, `postgres`, `pgadmin4`, `certbot`,
  `ydkn/avahi`) тянутся с Docker Hub как раньше — никакого зеркалирования
  в GHCR на этом шаге.

### 6.7. Чеклист «Build only сделано»

- [x] `.github/workflows/build-and-push.yaml` собирает 3 образа и пушит
      в public GHCR с тегами `sha-<sha>`, branch-тегами, `latest` для
      default branch и semver-тегами.
- [x] В `compose.yaml` у `app1`, `nginx`, `nginx-mutual` добавлено поле
      `image: ghcr.io/oleglebedevru/iot-rpc-rest-app/<svc>:${IMAGE_TAG:-latest}`
      рядом с `build:`.
- [x] У `app1` в `compose.yaml` добавлен `env_file: ./app-service/.env`
      (см. §6.2); файл `app-service/.env` присутствует на VM и не
      закоммичен в git.
- [x] У `nginx-mutual` секретные сертификаты вынесены из Dockerfile в
      bind-mount `./crt/...:/crt/...:ro` (см. §6.2.1) — без этого
      workflow `build-and-push` падает на сборке `nginx-mutual`.
- [x] GHCR packages public: разовый `docker login ghcr.io` на VM не нужен
      для текущего режима.
- [x] Прогнан ручной флоу `git pull` → `docker compose pull <svc>` →
      `docker compose up -d <svc>` по каждому из трёх сервисов.
- [ ] Проверено, что старый сценарий (`docker compose build <svc>` +
      `up -d <svc>`) по-прежнему работает на случай fallback.
- [x] Документирован в `docs/deploy-plan.md` (этот раздел) и при
      необходимости — короткой памяткой в `README` репозитория.

Так как этот шаг уже отработан на последних деплоях, следующий
практический этап — раздел 7 (полная автоматизация деплоя) и/или вынос
PG в managed-сервис (раздел 3).

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
2. `build-and-push.yaml` — уже существует; работает на push в
   `master`/`main`, PR, `workflow_dispatch` и git-tag `v*.*.*`:
   - `docker/setup-buildx-action`
   - `docker/login-action` к `ghcr.io` (`GITHUB_TOKEN` с правом
     `packages: write`)
   - matrix по 3 образам: `app-service`, `nginx-jwt`, `nginx-mutual`
   - `docker/build-push-action` с `cache-from/to: type=gha` и тегами
     `sha-<sha>`, branch, `latest`, `vX.Y.Z`/`vX.Y` на semver tag.
3. `deploy.yaml` — `workflow_run` после успешного `build-and-push`
   (или ручной `workflow_dispatch` с выбором тега, или автотриггер на
   `master`/`main`):
   - использует **GitHub Environment** `production` с required reviewers
     (защита от случайного деплоя);
   - `appleboy/ssh-action` или нативный `ssh -i $KEY` на VM:
     ```
     cd /opt/iot-rpc-rest-app
     export IMAGE_TAG=sha-${{ github.sha }}
     # GHCR packages сейчас public; login нужен только если пакеты станут private.
     # echo "$GHCR_TOKEN" | docker login ghcr.io -u <bot> --password-stdin
     docker compose -f compose.prod.yaml pull
     docker compose -f compose.prod.yaml up -d
     docker image prune -f
     ```
   - секреты (`SSH_KEY`, `VM_HOST`; `GHCR_TOKEN` только если packages private)
     — в `Environments → production`.

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

### Вариант C. Pull-модель: Watchtower / Diun + GHCR

На VM крутится `containrrr/watchtower` или Diun. Для текущих public GHCR
packages логин не нужен; если packages станут private, добавляются
`REPO_USER`+`REPO_PASS` = bot+PAT. CI пушит новый тег `latest` (или
используется branch tag вроде `master`), Watchtower сам обнаруживает новый
digest и перезапускает контейнеры.

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
  - выполняет `docker compose pull/up -d` (и `docker login ghcr.io`, только
    если packages переведены в private);
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

1. **CI-фундамент** (частично выполнено):
   - добавить `.github/workflows/ci.yaml` (uv sync, pytest, black);
   - [x] добавить `.github/workflows/build-and-push.yaml` с публикацией
     трёх образов в public GHCR по тегам `sha-<sha>`, branch, `latest`,
     semver;
   - [x] проверить, что образы собираются, появляются в GHCR и используются
     последними ручными деплоями.
2. **Подготовка `deploy/compose.prod.yaml`**:
   - убрать `build:`, заменить на `image: ghcr.io/oleglebedevru/iot-rpc-rest-app/<svc>:${IMAGE_TAG}`;
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
   - для текущих public GHCR packages `docker login ghcr.io` не нужен;
     выполнить `docker compose -f compose.prod.yaml pull` и
     `docker compose -f compose.prod.yaml up -d`;
   - убедиться, что `alembic upgrade head` отработал на managed PG.
5. **Автоматизация (Вариант A)**:
   - добавить `.github/workflows/deploy.yaml` с GitHub Environment
     `production` и required reviewers;
   - проверить деплой через `workflow_dispatch`;
   - после успеха включить автотриггер по `push` в `master`/`main`.
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
- [x] Основной флоу ручного деплоя выполняется через сборку на хосте (`docker compose build app1` + `docker compose up -d --no-deps app1`).
- [x] Деплой из GHCR (`docker compose pull app1`) доступен и задокументирован как альтернативный вариант (при наличии прямого указания).
- [x] Все три собственных образа публикуются в public GHCR `ghcr.io/oleglebedevru/iot-rpc-rest-app/*` с тегом `sha-*`.
- [ ] `deploy/compose.prod.yaml` использует `image:` из GHCR, без `build:`.
- [ ] `pg` и `pgdata` удалены из прод-compose; `app1`/`pgadmin` ходят в managed PG.
- [ ] Секреты вынесены в `.env` на VM / GitHub Environments, в git нет паролей.
- [ ] CI: lint + tests + build + push + (опц.) Trivy зелёные.
- [ ] CD: `deploy.yaml` с required reviewers, успешный прогон end-to-end.
- [ ] Бэкапы PG и RMQ настроены, проверено восстановление.
- [ ] Документация (`deploy/README.md`) описывает «как накатить с нуля».

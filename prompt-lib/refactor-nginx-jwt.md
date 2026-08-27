Скорректированное Техническое задание для проекта iot-rpc-rest-app
ТЗ: Переход на авторизацию по ApiKey через БД, провиженинг ключей, миграция из .env и перевод Nginx на nginx:alpine
1. Архитектурная концепция
Роль Nginx (nginx:alpine):
Nginx освобождается от любой кастомной авторизации (JWT C-модуль полностью удаляется).
Nginx становится прозрачным SSL Reverse Proxy:
Принимает HTTPS-трафик на портах 80 и 443, обслуживает Certbot Let's Encrypt.
Проксирует /api/v1/* на app1:8000, прозрачно пробрасывая клиентские заголовки (X-API-Key, Authorization, Content-Type, Upgrade, Connection).
Обслуживает mTLS-шлюзы для email на портах 1443 и 1444.
Роль бэкенда (app1) и БД:
Авторизация внешних систем по X-API-Key переносится на уровень бэкенда (app1) и таблицы БД org_api_keys (связь с Org 1:1).
Добавляется сервисный эндпоинт провиженинга API-ключей (POST /api/v1/provisioning/api-keys) для синхронизации со стороны etranprocessing.
Сохраняется поддержка доверенных веб-заголовков Nginx (X-Role, orgId) для интерфейса MenuBuilder.
                    Внешние интеграции / API Клиенты (с X-API-Key)
                                          │
                                          │ HTTPS :443
                                          ▼
       ┌──────────────────────────────────────────────────────────────────┐
       │             iot-rpc.nginx (официальный nginx:alpine)             │
       │                                                                  │
       │  - Прозрачный Reverse Proxy для /api/v1/* -> app1:8000           │
       │  - Let's Encrypt / Certbot                                       │
       │  - Email mTLS (1443 / 1444)                                      │
       │  - УДАЛЕНО: lk-leo4 статика, Yandex Cloud прокси, C-модуль JWT   │
       └──────────────────────────────────┬───────────────────────────────┘
                                          │
                                          │ HTTP (:8000) с заголовком X-API-Key
                                          ▼
       ┌──────────────────────────────────────────────────────────────────┐
       │                   app1 (FastAPI IoT Core)                        │
       │                                                                  │
       │  1. api_depends.py: валидация X-API-Key по БД (org_api_keys)     │
       │  2. При успехе: привязка запроса к org_id организации            │
       │  3. Эндпоинт POST /api/v1/provisioning/api-keys                  │
       └──────────────────────────────────┬───────────────────────────────┘
                                          │
                                          ▼
       ┌──────────────────────────────────────────────────────────────────┐
       │                       PostgreSQL (БД iot-rpc)                    │
       │  - Таблица orgs (организации)                                    │
       │  - [NEW] Таблица org_api_keys (org_id PK/FK, api_key UNIQUE)     │
       └──────────────────────────────────────────────────────────────────┘
2. Модель данных в БД (1:1 с Организацией)
2.1. SQLAlchemy модель (core/models/org_api_key.py)
from datetime import datetime
from typing import Optional
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from core.models.base import Base

class OrgApiKey(Base):
    __tablename__ = "org_api_keys"

    org_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("orgs.id", ondelete="CASCADE"),
        primary_key=True,
        unique=True,
        doc="ID организации (1:1)",
    )
    api_key: Mapped[str] = mapped_column(
        String(128),
        unique=True,
        index=True,
        nullable=False,
        doc="Уникальный API-ключ для внешних интеграций",
    )
    name: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        doc="Описание / Название партнёра или сервиса",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
        nullable=False,
        doc="Флаг активности ключа",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    org: Mapped["Org"] = relationship("Org", back_populates="api_key_record")
2.2. Alembic-миграция и перенос существующих ключей из .env
Создать миграцию Alembic: alembic revision --autogenerate -m "add_org_api_keys_table_and_seed".
В миграции предусмотреть автоматический перенос существующих ключей из .env:
Считать ключи из settings.api_keys / .env (если они были настроены в конфигурации).
Выполнить INSERT для соответствующих организаций:
# Внутри upgrade()
op.create_table(
    "org_api_keys",
    sa.Column("org_id", sa.Integer(), nullable=False),
    sa.Column("api_key", sa.String(length=128), nullable=False),
    sa.Column("name", sa.String(length=255), nullable=True),
    sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], ondelete="CASCADE"),
    sa.PrimaryKeyConstraint("org_id"),
)
op.create_index(op.f("ix_org_api_keys_api_key"), "org_api_keys", ["api_key"], unique=True)
3. Доработка бэкенда (app-service)
3.1. Валидация X-API-Key в api/api_v1/api_depends.py
Доработать зависимость get_org_id_dependency:

# 1. Проверяем заголовок X-API-Key / Authorization: ApiKey <key>
api_key = request.headers.get("X-API-Key") or request.headers.get("x-api-key")
if api_key:
    # Поиск активного ключа в БД org_api_keys
    stmt = select(OrgApiKey.org_id).where(
        OrgApiKey.api_key == api_key,
        OrgApiKey.is_active == True
    )
    result = await session.scalar(stmt)
    if result is not None:
        return result  # Возвращаем авторизованный org_id
    else:
        log.warning("Authentication failed: invalid or inactive API key")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or inactive API Key",
        )

# 2. Если API-ключа нет -> fallback на доверенные веб-заголовки от Nginx (MenuBuilder superuser/user)
3.2. Эндпоинты провиженинга API-ключей (api/api_v1/provisioning.py)
Добавить роуты по аналогии с провиженингом терминалов:

POST /api/v1/provisioning/api-keys (Upsert ключа организации):
Тело запроса (OrgApiKeyProvisionRequest):
{
  "org_id": 1,
  "api_key": "leo4_sec_98f12a...",
  "name": "Основной ключ партнера",
  "is_active": true
}
Защита: verify_service_auth по X-Internal-Service-Key (для вызовов из etranprocessing).
Логика: Выполняет INSERT ... ON CONFLICT (org_id) DO UPDATE SET api_key=..., is_active=..., updated_at=now().
DELETE /api/v1/provisioning/api-keys/{org_id} (Отзыв ключа).
GET /api/v1/provisioning/api-keys/{org_id} (Проверка статуса ключа).
4. Безопасное обновление compose.yaml и Nginx (Zero Downtime)
4.1. Новый compose.yaml
  nginx:
    image: nginx:alpine
    container_name: iot-rpc-rest-app-nginx-1
    restart: always
    ports:
      - "80:80"
      - "443:443"
      - "1443:1443"
      - "1444:1444"
    volumes:
      - ./nginx-configs/dev_leo4_ru/default.conf:/etc/nginx/conf.d/default.conf:ro
      - ./nginx-configs/dev_leo4_ru/terem_email_mtls.conf:/etc/nginx/conf.d/terem_email_mtls.conf:ro
      - ./nginx-configs/dev_leo4_ru/snippets/terem_email_proxy.inc:/etc/nginx/conf.d/terem_email_proxy.inc:ro
      - ./certbot/www:/var/www/certbot/:ro
      - ./certbot/conf/:/etc/nginx/ssl/:ro
      - ./crt/iot_leo4_ca.crt:/crt/ca_certificate.pem:ro
      - ./crt/cert_0000.pem:/crt/server_certificate.pem:ro
      - ./crt/key_0000.pem:/crt/server_key.pem:ro
    networks:
      - rabbitmq_network
      - pg_network
    depends_on:
      - app1
Удалено:

Секция build: (нет кастомного Dockerfile).
Монтирование статики lk-leo4 (./nginx/html:/var/share/nginx/html).
Удалён файл docker-files/nginx-jwt/Dockerfile.
4.2. Конфигурация Nginx (nginx-configs/dev_leo4_ru/default.conf)
server {
    listen 80;
    listen [::]:80;
    server_name dev.leo4.ru;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name dev.leo4.ru;

    ssl_certificate /etc/nginx/ssl/live/dev.leo4.ru/fullchain.pem;
    ssl_certificate_key /etc/nginx/ssl/live/dev.leo4.ru/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # Прозрачное проксирование всех API вызовов в app1
    location /api/v1/ {
        proxy_pass http://app1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # WebSocket для интерактивной диагностики
    location /api/v1/diagnostics/ {
        proxy_pass http://app1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }

    # Документация OpenAPI / Swagger
    location ~ ^/(docs|openapi.json|redoc) {
        proxy_pass http://app1:8000;
        proxy_set_header Host $host;
    }
}
5. Пошаговый порядок развертывания на сервере
Шаг 1 (БД и миграции):
Обновить код app-service на сервере.
Запустить Alembic-миграцию: sudo docker exec app1 alembic upgrade head
Шаг 2 (Переключение Nginx):
Обновить compose.yaml и default.conf.
Выполнить мягкий перезапуск Nginx:
sudo docker compose pull nginx
sudo docker compose up -d --no-deps --force-recreate nginx
Шаг 3 (Верификация):
Проверить запрос с валидным API-ключом: curl -k -i -H "X-API-Key: <key>" https://dev.leo4.ru/api/v1/devices/ ➔ HTTP 200 OK.
Проверить запрос без ключа / с неверным ключом: curl -k -i https://dev.leo4.ru/api/v1/devices/ ➔ HTTP 401 Unauthorized.
Проверить роут провиженинга: curl -k -X POST https://dev.leo4.ru/api/v1/provisioning/api-keys -H "X-Internal-Service-Key: <secret>" -d '{"org_id": 1, "api_key": "test_key"}'.
Проверить работу email mTLS на порту 1443.
ТЗ полностью скорректировано, учитывает хранение ключей в БД (1:1), провиженинг, Alembic-миграцию и безопасное обновление Docker Compose. Можно передавать задачу агенту в репозиторий iot-rpc-rest-app!
# 🛡️ Internal API v1 · Межсервисный контракт

> Control plane доверенных сервисов экосистемы. Базовый путь backend: `/api/internal/v1`.

[← Документация](README.md) · [Публичный REST API](rest-api.md) · [События](2-events-api-format-description.md)

## 🧭 Граница интерфейсов

| Интерфейс | Назначение | Авторизация |
| :--- | :--- | :--- |
| `/api/v1/*` | Публичные задачи, события, устройства, gauges и webhooks | Ключ организации |
| `/api/internal/v1/*` | Tenant операции, provisioning, billing, diagnostics и удалённые сеансы | Доверенная межсервисная identity и контекст |

Пример внутреннего URL: `http://app1:8000/api/internal/v1/device-tasks/`. Internal routers скрыты из публичной OpenAPI-схемы.

Доступность извне, блокировка internal paths и очистка доверенных headers — обязанности внешнего gateway. Его конфигурация управляется отдельно; Nginx-файлы репозитория не подтверждают фактическую конфигурацию периметра.

## 🔑 Credentials и tenant

| Заголовок | Назначение |
| :--- | :--- |
| `X-Internal-Service-Key` | Настроенный секрет сервиса; альтернатива — `Authorization: Bearer <secret>` |
| `X-Org-Id` | Effective tenant для tenant-запросов |
| `X-Role` | Доверенная роль superuser/admin/user |
| `Content-Type` | application/json для JSON body |

HTTP dependency поддерживает X-Service-Key и fallback статических ключей конфигурации. Когда вообще не настроены internal secret и static API keys, присутствует локальный режим без проверки credentials с предупреждением. Рабочая интеграция должна иметь настроенный secret.

Для superuser/admin непустой `org_id` query имеет приоритет над header. Для обычного caller header имеет приоритет, query используется только при его отсутствии. Gateway сам формирует контекст и ограничивает пользовательские overrides. Event API требует положительный effective org.

WebSocket endpoints имеют собственные проверки роли, org, lease и ownership; правила HTTP dependency не заменяют их.

## 🗂️ Ресурсы

| Группа | Возможности / контракт |
| :--- | :--- |
| Devices / tasks / events / gauges / webhooks | Tenant-варианты основных [REST ресурсов](rest-api.md) |
| Provisioning / device provisioning | Регистрация, привязка терминалов, org/API-ключи |
| Billing / administrator | Служебные и административные операции |
| Diagnostics | [Logs/console WS](remote-diagnostics-protocol.md) |
| Remote input / sessions | [Lease, ввод, stream/view lifecycle](remote-input-protocol.md) |
| File manager | [L4FM v2](file-manager-v2.md) |
| Archive | Архивные операции |

Полный состав — [internal routers](../app-service/api/internal_v1/__init__.py). Task CRUD использует те же TaskCreate и result schemas. Не отправляйте устаревшее `params` вместо `payload`.

```http
POST /api/internal/v1/device-tasks/
X-Internal-Service-Key: <configured-service-secret>
X-Org-Id: 12
Content-Type: application/json
```

```json
{
  "ext_task_id": "open-cell-5",
  "device_id": 773,
  "method_code": 51,
  "priority": 1,
  "ttl": 5,
  "payload": {"dt": [{"cl": 5}]}
}
```

## 📨 Независимый поиск пользовательской истории

`GET /api/internal/v1/device-events/search` читает только события 900–999, не меняет offsets и не требует online или console lease.

| Query | Правило |
| :--- | :--- |
| `device_id` | Обязательный положительный ID одного устройства |
| `correlation_id` | UUID 8-4-4-4-12; сравнение с `300[0]["448"]` без учёта регистра |
| `events_include` | Повторяемый параметр, только 900–999; отсутствие — весь диапазон |
| `after_event_id` | Положительный server ID; выборка id > cursor |
| `created_from / created_to` | Время с TZ; created_at >= from и < to |
| `limit` | 1–100, default 50 |

Ответ содержит items (DevEventOut), next_after_event_id, has_more. Порядок id ASC; пустой ответ сохраняет заданный cursor либо null. UUID — фильтр, не разрешение.

Все event reads требуют совпадения tenant записи и текущей привязки устройства. Перенос A → B не раскрывает историю A организации B. История до tenant migration с org_id=NULL скрыта; автоматического backfill нет.

Невалидные query дают 422, отсутствующий tenant — 400, неверные HTTP credentials — 403. Чужое устройство/история дают пустую выдачу. Cursor не гарантирует порядок commit параллельных транзакций или exactly-once. Для сверки операции допустим повторный поиск по UUID с дедупликацией server ID; отсутствие события не запускает команду заново.

MenuBuilder/MCP reader формирует tenant после проверки caller и не передаёт пользовательский override или superuser-контекст для обычного чтения.

**Реализация:** [HTTP auth](../app-service/api/internal_v1/internal_depends.py) · [event router](../app-service/api/internal_v1/device_events.py) · [repository](../app-service/core/crud/dev_events_repo.py) · [history handoff](user-event-history-iot-handoff.md). Сверено с master на 09.10.2026.

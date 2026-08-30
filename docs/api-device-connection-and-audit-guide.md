# API Reference: Device Connection, Collision Status & Audit Log

## 1. Обзор структуры `connection`

Объект `connection` в ответах API (`GET /api/v1/devices/`) содержит актуальный материализованный снимок транспортного и сервисного состояния связи терминала с платформой.

### Базовые поля объекта `connection`

| Поле | Тип | Описание |
|---|---|---|
| `device_id` | `int` | Идентификатор устройства в системе |
| `client_id` | `str` | Серийный номер (`SN`) устройства / Common Name сертификата |
| `connected_at` | `datetime (ISO 8601)` | Время открытия физического TCP/TLS сокета на брокере |
| `checked_at` | `datetime (ISO 8601)` | Время последнего обновления или сверки статуса в БД |
| `last_checked_result` | `bool` | Физический статус открытого сокета (`true` — подключен, `false` — отключен) |
| `app_connect` | `bool \| null` | Статус сервиса приложения по LWT-каналу `dev/<SN>/app` (`null` — LWT не поддерживается) |
| `svc_connect` | `bool \| null` | Статус системного демона по LWT-каналу `dev/<SN>/svc` |
| `is_app_available` | `bool \| null` | Вычисляемая готовность приложения: `(last_checked_result and app_connect and not is_blocked)` |
| `is_svc_available` | `bool \| null` | Вычисляемая готовность сервиса: `(last_checked_result and svc_connect and not is_blocked)` |
| `details` | `object \| null` | Детализированная телеметрия сокета из брокера (`peer_host`, `peer_port`, `ssl_cipher`, `peer_cert_validity`) |

---

## 2. Поля безопасности и фиксации нарушений

При выявлении аномалий безопасности объект `connection` обогащается следующими полями:

| Поле | Тип | Описание |
|---|---|---|
| `is_blocked` | `bool` | Флаг блокировки устройства (`true` — доступ заблокирован из-за коллизии) |
| `violation_type` | `str \| null` | Тип нарушения: `DEVICE_CLONE` (клон накопителя) или `SN_COLLISION` (дубликат сертификата) |
| `violation_details` | `object \| null` | Метаданные инцидента (структура приведена ниже) |
| `recent_audit_events` | `list[DeviceAuditEvent] \| null` | Топ-5 последних событий жизненного цикла (присутствует **только** при запросе конкретного `device_id`) |

### Детальная структура объекта `violation_details`

| Поле | Тип | Описание | Пример |
|---|---|---|---|
| `violation_type` | `str` | Тип зафиксированного нарушения | `"SN_COLLISION"` |
| `reason` | `str` | Человекочитаемое описание причины инцидента | `"Multiple conflicting TLS certificates active for the same SN"` |
| `detected_at` | `datetime (ISO 8601)` | Метка времени обнаружения инцидента и срабатывания защиты | `"2026-08-30T09:56:11.931003+00:00"` |
| `flapping_count` | `int` | Суммарное количество зафиксированных попыток переподключения/коллизий | `30` |
| `cert_validities` | `list[str]` | Список сроков действия конфликтующих сертификатов | `["2026-06-02T12:34:07Z - 2027-06-02T12:34:07Z", "2026-08-07T06:42:22Z - 2027-08-07T06:42:22Z"]` |
| `conflicting_hosts` | `list[str]` | Список конфликтующих IP-адресов/хостов источников (в формате сетевого стека RabbitMQ / Erlang) | `["{0,0,0,0,0,65535,21485,65262}", "{0,0,0,0,0,65535,23538,54545}"]` |

> **Примечание по IP-адресам (`peer_host`, `conflicting_hosts`)**:
> Брокер RabbitMQ представляет IP-адреса сокетов в формате кортежей Erlang IPv4-mapped IPv6 (`{0,0,0,0,0,65535,word7,word8}`).
> Например: `{0,0,0,0,0,65535,21485,65262}` $\to$ `21485=0x53ED (83.237)`, `65262=0xFEE6 (254.238)` $\to$ `83.237.254.238`.
> Готовая нормализованная строка IP и порта последней попытки подключения доступна в поле `details.name` (например, `"83.237.254.238:53420 -> 172.18.0.2:8883"`).

### Детальная структура элементов `recent_audit_events`

| Поле | Тип | Описание |
|---|---|---|
| `id` | `int` | Уникальный глобальный идентификатор записи аудита в `tb_device_audit_logs` |
| `device_id` | `int` | Идентификатор устройства |
| `org_id` | `int` | Идентификатор организации владельца |
| `event_type` | `str` | Код события: `PROVISIONED`, `SN_COLLISION`, `DEVICE_CLONE`, `BLOCKED`, `UNBLOCKED` |
| `actor` | `str \| null` | Источник/инициатор события: `"system/detector"`, `"api/provisioning"`, `"api_key:..."` |
| `details` | `object \| null` | Снимок контекстных данных события (параметры коллизии или метаданные провиженинга) |
| `created_at` | `datetime (ISO 8601)` | Метка времени фиксации события в UTC |

---

## 3. Примеры ответов API

### Пример 1: Выдача в общем списке `GET /api/v1/devices/` (с зафиксированным клоном)

В общем списке возвращается компактная материализация без раздувания объема трафика:

```json
[
  {
    "id": 147,
    "device_id": 6209,
    "sn": "a4b0006209c67756d020626",
    "connection": {
      "device_id": 6209,
      "client_id": "a4b0006209c67756d020626",
      "connected_at": "2026-08-30T08:33:07.448000Z",
      "checked_at": "2026-08-30T08:33:07.470000Z",
      "last_checked_result": false,
      "app_connect": null,
      "svc_connect": null,
      "is_app_available": null,
      "is_svc_available": null,
      "is_blocked": true,
      "violation_type": "DEVICE_CLONE",
      "violation_details": {
        "detected_at": "2026-08-30T08:33:07.470000Z",
        "violation_type": "DEVICE_CLONE",
        "conflicting_hosts": ["83.237.254.238", "91.242.213.17"],
        "cert_validities": ["2026-08-07T06:42:22Z - 2027-08-07T06:42:22Z"],
        "flapping_count": 5,
        "host_switches": 4,
        "reason": "Rapid IP hopping across distinct hosts with identical credentials"
      },
      "recent_audit_events": null
    },
    "device_gauges": [],
    "device_tags": []
  }
]
```

### Пример 2: Детальный запрос терминала `GET /api/v1/devices/?device_id=6209` (с зафиксированным `SN_COLLISION`)

При фильтре по конкретному терминалу возвращается расширенная история (топ-5 событий аудита):

```json
[
  {
    "id": 147,
    "device_id": 6209,
    "sn": "a4b0006209c67756d020626",
    "device_gauges": [
      {
        "device_id": 6209,
        "type": "44",
        "updated_at": "2026-08-30T09:48:36.690091Z",
        "gauges": {
          "101": 6,
          "102": "2026-08-30T09:48:37Z",
          "200": 44,
          "300": [
            {
              "310": "2.365.6539.622",
              "314": "00:e0:3a:10:16:64",
              "323": "172.26.219.213",
              "324": "a4b0006209c67756d020626"
            }
          ]
        }
      }
    ],
    "connection": {
      "device_id": 6209,
      "client_id": "a4b0006209c67756d020626",
      "connected_at": "2026-08-30T09:51:50.229000Z",
      "checked_at": "2026-08-30T09:56:11.933290Z",
      "last_checked_result": false,
      "app_connect": null,
      "svc_connect": null,
      "is_app_available": null,
      "is_svc_available": null,
      "is_blocked": true,
      "violation_type": "SN_COLLISION",
      "violation_details": {
        "reason": "Multiple conflicting TLS certificates active for the same SN",
        "detected_at": "2026-08-30T09:56:11.931003+00:00",
        "flapping_count": 30,
        "violation_type": "SN_COLLISION",
        "cert_validities": [
          "2026-06-02T12:34:07Z - 2027-06-02T12:34:07Z",
          "2026-08-07T06:42:22Z - 2027-08-07T06:42:22Z"
        ],
        "conflicting_hosts": [
          "{0,0,0,0,0,65535,21485,65262}",
          "{0,0,0,0,0,65535,23538,54545}"
        ]
      },
      "recent_audit_events": [
        {
          "id": 1,
          "device_id": 6209,
          "org_id": 339,
          "event_type": "SN_COLLISION",
          "actor": "system/detector",
          "details": {
            "reason": "Multiple conflicting TLS certificates active for the same SN",
            "detected_at": "2026-08-30T09:52:00.324125+00:00",
            "flapping_count": 2,
            "violation_type": "SN_COLLISION",
            "cert_validities": [
              "2026-06-02T12:34:07Z - 2027-06-02T12:34:07Z",
              "2026-08-07T06:42:22Z - 2027-08-07T06:42:22Z"
            ],
            "conflicting_hosts": [
              "{0,0,0,0,0,65535,21485,65262}",
              "{0,0,0,0,0,65535,23538,54545}"
            ]
          },
          "created_at": "2026-08-30T09:52:00.325020Z"
        }
      ],
      "details": {
        "ssl": true,
        "name": "83.237.254.238:53420 -> 172.18.0.2:8883",
        "user": "a4b0006209c67756d020626",
        "protocol": "{'MQTT',{5,0}}",
        "recv_oct": 1819,
        "send_oct": 3127,
        "conn_name": null,
        "peer_host": "{0,0,0,0,0,65535,21485,65262}",
        "peer_port": 53420,
        "ssl_cipher": "aes_256_gcm",
        "connected_at": 1788083510229,
        "ssl_protocol": "tlsv1.2",
        "peer_cert_subject": "C=RU,OU=0006209,O=Leo4,CN=a4b0006209c67756d020626",
        "peer_cert_validity": "2026-08-07T06:42:22Z - 2027-08-07T06:42:22Z"
      }
    },
    "device_tags": []
  }
]
```

---

## 4. Действия потребителя при получении статуса `is_blocked = true`

1. Проверить значение `violation_type`:
   - `DEVICE_CLONE`: обнаружены клоны жесткого диска. Требуется физически отключить дублирующие терминалы и выпустить новые уникальные сертификаты.
   - `SN_COLLISION`: обнаружен старый терминал со старым сертификатом. Требуется отключить старый терминал.
2. Провести перепровиженинг устройства через `POST /api/v1/internal/provisioning/terminals`. Это автоматически снимет блокировку и сбросит флаги нарушений.

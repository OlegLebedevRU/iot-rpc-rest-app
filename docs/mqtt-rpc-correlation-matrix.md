# 🧬 RPC · Матрица корреляции

[← Документация](README.md) · [RPC-протокол](mqtt-rpc-protocol.md) · [Форматы UUID](correlation-data-guide.md)

## 📡 Сообщения

| Сообщение | UUID | Дополнительные идентификаторы |
| :--- | :--- | :--- |
| TSK | UUID задачи, созданный сервером | `header.ext_task_id`, `header.device_id` |
| ACK | UUID полученного TSK | — |
| REQ · Trigger | UUID полученного TSK | — |
| REQ · Polling | Нулевой UUID | Необязательный `rpc_methods` |
| RSP · Задача | UUID выбранной задачи | `id` в JSON совпадает; параметры в `payload` |
| RSP · NOP | Нулевой UUID | `method_code=0` |
| RES | UUID задачи из RSP | `result_uid`, `ext_id` |
| CMT | UUID задачи | `result_id`, `ext_id`; `result_uid`, если распознан на входе |
| EVT | UUID публикации события | `dev_event_id`; внешняя связь в payload при необходимости |
| EVA | Корреляция EVT, если доступна | `event_type_code`, `dev_event_id` |

Нулевой UUID: `00000000-0000-0000-0000-000000000000`. Для нового клиента transport UUID обязателен. Сервер дублирует исходящую корреляцию в native field и User Property `correlationData`.

## 🔄 Повторы

Retry задачи сохраняет task UUID. Retry логического результата сохраняет также `result_uid`, status, ext_id и содержимое. Retry события сохраняет время устройства, event ID и UUID публикации. Создание нового UUID результата при каждом retry препятствует распознаванию дубликата.

`LOCK` допускает повторную доставку, поэтому клиент хранит состояние исполнения по task UUID. CMT подтверждает сохранение результата; повторная отправка RES не должна повторно запускать действие.

## 🧪 Исключение: Channel Probe

Маркированная ветка `iot_probe=1` использует fresh ненулевые UUID N для REQ/RSP и M для EVT/EVA; M отличается от N. `request_nonce` связывает этапы. Таблица обычного polling к ней не применяется. [Полный контракт](channel-probe.md).

Сверено с [decoder](../app-service/core/topologys/fs_depends.py) и [публикацией](../app-service/core/services/device_task_processing.py), `master`, 09.10.2026.

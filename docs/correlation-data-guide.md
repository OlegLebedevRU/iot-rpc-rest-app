# 🧬 Correlation Data · Сквозные идентификаторы

> Для RPC UUID задачи связывает TSK, ACK, REQ, RSP, RES и CMT. Для события создаётся отдельный UUID публикации.

[← Документация](README.md) · [RPC](mqtt-rpc-protocol.md) · [Матрица сообщений](mqtt-rpc-correlation-matrix.md)

## 🧭 Правила нового клиента

| Сценарий | Значение |
| :--- | :--- |
| Адресная задача | UUID, назначенный IoT и полученный в TSK/RSP |
| Polling REQ | `00000000-0000-0000-0000-000000000000` |
| RES и его повтор | UUID задачи из RSP; дополнительно стабильный `result_uid` |
| EVT и его повтор | Собственный ненулевой UUID публикации |
| Probe | Fresh UUID по отдельному [контракту](channel-probe.md) |

Для native MQTT 5 Correlation Data используйте байты **UTF-8 текста UUID** в формате `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`. Нулевой UUID допустим для polling и NOP, но не для сохранения RPC-результата.

Поддерживается User Property `correlationData` с тем же текстом UUID. Исходящие TSK/RSP/CMT и EVA с доступной корреляцией дублируют её в native AMQP property и header `correlationData`. Если передаёте оба поля, значения должны совпадать.

## 📦 Пример polling

```text
Topic: dev/<SN>/req
Payload: пустой
Native Correlation Data: UTF-8("00000000-0000-0000-0000-000000000000")
QoS: 1
Retain: false
```

Полученный RSP с задачей содержит **UUID выбранной задачи**, а не нулевой UUID запроса. На NOP приходит нулевая корреляция. Для адресного REQ сервер также может ответить NOP с нулевой корреляцией, если задача недоступна.

## 🛟 Совместимость серверного decoder

Текущая реализация выбирает первое успешно разобранное значение:

1. Headers `correlationData`, затем `CorrelationData`.
2. Header `x-correlation-id`.
3. UUID-поля JSON верхнего уровня: `correlationData`, `CorrelationData`, `correlation_data`, `corr_data`, `corr_id`, `id`, `command_id`, `target_task_id`.
4. Native AMQP `msg.correlation_id`.

Decoder принимает UUID-строки, включая поддерживаемые Python UUID представления, и 16-байтовые binary значения. Эти fallback существуют для совместимости; новый клиент должен передавать однозначную transport correlation. Невалидная корреляция не становится нулевым UUID автоматически: обычные REQ/RES без неё отбрасываются.

## 🏷️ Не путайте идентификаторы

| Поле | Что идентифицирует |
| :--- | :--- |
| Task `id` / RPC correlation | Задачу IoT |
| REST `ext_task_id` | Внешнюю задачу приложения |
| RES `ext_id` | Числовой ID результата на устройстве |
| RES `result_uid` | Логический результат, стабильный при retry |
| CMT `result_id` | Сохранённую запись результата в IoT |
| EVT `dev_event_id` / JSON `101` | Событие на устройстве |
| REST event `id` | Запись истории сервера |
| Event tag `409`, `448`, `449.operation_id` | Связь события с исходным RPC или внешней операцией |

Transport UUID события не заменяет внешний `448` и operation ID `449`. Несколько публикаций могут относиться к одной операции. Корреляция связывает данные, но не предоставляет доступ к ним.

**Реализация:** [decoder](../app-service/core/topologys/fs_depends.py) · [публикация](../app-service/core/services/device_task_processing.py). Сверено с `master` на 09.10.2026.

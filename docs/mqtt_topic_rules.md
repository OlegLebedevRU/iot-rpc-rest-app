# 🗺️ MQTT · Карта топиков

> `dev/<SN>/<action>` — от устройства; `srv/<SN>/<action>` — к устройству. SN соответствует CN сертификата.

[← Документация](README.md) · [RPC](mqtt-rpc-protocol.md) · [События](event-protocol-mqtt.md)

## 📡 Основной обмен

| От устройства | К устройству | Назначение |
| :--- | :--- | :--- |
| `dev/<SN>/req` | `srv/<SN>/rsp` | Выборка задачи и передача полного конверта параметров |
| `dev/<SN>/ack` | `srv/<SN>/tsk` | ACK анонса; ACK необязателен, TSK публикуется сервером |
| `dev/<SN>/res` | `srv/<SN>/cmt` | Результат и подтверждение его сохранения |
| `dev/<SN>/evt` | `srv/<SN>/eva` | Событие и прикладное подтверждение при подходящих headers |

MQTT topic `dev/a3b1234567c10221d290825/req` соответствует AMQP routing key `dev.a3b1234567c10221d290825.req`. Не добавляйте начальный `/`. Используйте фактический SN сертификата и согласованные ACL, а не фиксированную длину из примера.

## 🛠️ Обслуживание и управление

| Топик | Назначение | Контракт |
| :--- | :--- | :--- |
| `dev/<SN>/out` | Volatile вывод логов, stdout/stderr диагностики | [Remote Diagnostics](remote-diagnostics-protocol.md) |
| `srv/<SN>/ctl` | Команды удалённого ввода и control plane | [Remote Input](remote-input-protocol.md) |
| `dev/<SN>/ctl` | Presence и ACK/NACK агента | [Remote Input](remote-input-protocol.md) |
| `srv/<SN>/fmc` | L4FM v2: навигация и подтверждённая остановка | [Файловый менеджер](file-manager-v2.md) |
| `dev/<SN>/fmr` | Ограниченный по размеру коррелированный ответ L4FM | [Файловый менеджер](file-manager-v2.md) |

`out` — поток без истории DeviceEvent. Управление диагностикой остаётся в RPC. `ctl` имеет собственные lease/TTL/ACK правила; presence может быть retained, команды сервера — без retain. `fmc/fmr` — отдельное исключение для L4FM v2, без retain: файлы и S3 URL через эти топики не передаются.

## 🔐 Идентичность и ограничения

Используйте только топики своего SN. Идентичность задаётся сертификатом и маршрутизацией брокера; SN в payload не заменяет transport identity. MQTT client ID совпадает с SN.

У разных planes разные гарантии доставки, сроки и корреляция. Не переносите правила `ctl` или `fmc/fmr` на RPC. Суффиксы `app/svc` не описывают публичный RPC-контракт.

[Channel Probe](channel-probe.md) работает на существующих `req/rsp/evt/eva` с обязательным marker `iot_probe=1`; новые топики для него не вводятся.

**Реализация:** [конфигурация](../app-service/core/config.py) · [подписчики](../app-service/core/topologys/fs_queues.py) · [публикация RPC](../app-service/core/services/device_task_processing.py). Сверено с `master` на 09.10.2026.

# Управление камерой siplite

Контракт `siplite-camera/1.0.0`, 23.10.2026. Нормативное расширение для новой
канонической OpenIPC firmware. Наличие документа не означает поддержку текущей
firmware/app1. Machine package:
[contracts/siplite-camera-v1](../contracts/siplite-camera-v1/README.md).

## Владельцы и транзакция

IoT владеет RPC, gauge84/tag450 и правами; siplite — контроллером камеры и
стабильным local API; OpenIPC — camera API/board mapping; l4media — negotiated
media admission; MenuBuilder — пользователем и оркестрацией.

Заказчик подтвердил: новые camera операции завершаются **RES плюс gauge84**,
без новых evt. Gauge84 использует существующий evt transport, но новых event
type codes/EVA/webhook транзакций не вводится. Исполнение siplite ↔ IP-камера;
STM32 не затрагивается, power164 остаётся ESP32/TCA6408A.

| Направление | Канал | Версия | QoS/retain | Повторы | Deadline | Результат |
|---|---|---|---|---|---|---|
| BFF→IoT→siplite | REST task→srv/SN/rsp | существующий envelope, camera1.0.0 | устройство QoS1, retain=false | task/correlation UUID | TTL и timeout | RES, затем CMT хранения |
| siplite→IoT | dev/SN/evt, type84/tag450 | существующий gauge с camera extension | QoS1/retain=false | snapshot_id/operation_id | fresh observation | gauge storage отдельно от RES |
| tool→siplite | /local/rpc и /local/camera | local v1, camera1.0.0 | N/A | operation_id/hardware_id | monotonic budget |202 + polling; offline доступен |
| BFF→l4media | /api/v2/media/* | negotiated camera1.0.0, wire2 | N/A | immutable epoch/descriptor | authoritative lease | HTTP/health, затем decode отдельно |

Основная firmware MQTT type **main_app** явно подтверждена заказчиком.
Сохранять dev/SN/app и app_online/app_offline; svc_desk не копировать.

## Реестр методов

160 чтение/capabilities; 161 schema-validated nested patch; 162 day/night;
163 medium/hd с прежней семантикой; 164 fixed camera power. Новые методы:

| Код | Имя | Операции |
|---|---|---|
|165|CMD_IP_CAMERA_DISCOVERY|scan/cancel, физический port-2 в switch и ports|
|166|CMD_IP_CAMERA_CONNECTION|bind/set_credentials/clear_credentials/unbind|
|167|CMD_IP_CAMERA_ILLUMINATION|set/probe/confirm/cancel для white/ir/global_enable|

Точные shape/required/enum задаёт camera-rpc.schema.json; old methods и новые
envelopes отправляются только после camera capability negotiation. Пределы,
local API, crypto и совместимость — package README. Остальные не затронутые
этой редакцией методы/старые клиенты сохраняют свои контракты.

В161 разрешены video0.codec/size/fps/bitrate/gopSize/rcMode и image.* новой
firmware, плюс nightMode.lightMonitor. Удалить продуктовый size whitelist из
новой ветки: геометрию/FPS/bitrate проверять по schema/sources, затем actual SPS
и negotiated server/browser. Пустой size, fps0, bitrate0 означают native auto
только если это подтверждено схемой. Общее envelope ограничение не заменяет
аппаратные диапазоны. Legacy isp.* и legacy-set новой ветке не нужны.

## Discovery и credentials

165 учит/читает KSZ FDB, связывает MAC↔IP↔physical port2, использует leases/ARP
и bounded network probe. Static192.168.1.10 проверяется и при DHCP uplink;
другую подсеть исследовать без изменения постоянного uplink/DHCP/switch mode.
Нельзя отправлять credentials кандидату без подтверждения port2. Известный
MAC имеет приоритет; первая подходящая камера выбирается только без binding.
Потеря существующей камеры не разрешает её молча подменить другой.

166 bind требует candidate_mac и свежий discovery_generation, set_credentials
требует sealed envelope; clear_credentials/unbind не принимают credentials.
Под CAS/guard проверить generation, текущую identity и revision. Пароль
не возвращается; наблюдения содержат has_credentials/auth_source/auth status.
Custom profile имеет приоритет над штатным;401 не запускает перебор паролей.
Секретный RPC выполняется с encryption-before-task-storage по package README,
без plaintext fallback через generic49. Политика private NVS и migration едина
для cloud и local API. Local plaintext допускается только в закрытой LAN session.

## Подсветка

167 принимает роль и candidate_id из подтверждённого профиля платы, а не сырой
GPIO/address/mask/URL. Подсказки GPIO0_4 white, GPIO6_4 IR, GPIO8_1 global enable
сначала проверяются по wiring, owners, mux и API. Отсутствующий whiteLightPin
нельзя выдумать в siplite; необходим native/companion API с readback.

Probe — device-owned off/on/off максимум3000ms на одном разрешённом кандидате;
после него baseline восстанавливается независимо от UI. Общая commissioning
сессия не более60000ms и не продлевается polling. Каждая команда имеет собственную
operation_id, а commissioning_id связывает probe/confirm/cancel. Confirm принимает физическую
observation для этой же активной сессии, сохраняет профиль только после
повторного согласованного результата. Cancel восстанавливает baseline и
завершает сессию; повтор не повторяет воздействие. Unknown владельцы/mux
останавливают пробу; IR-cut pair API не является произвольным LED writer.
Global enable проверяется отдельно от IR/white; PWM разрешён только при
подтверждённом channel/pad/driver. Потеря связи/readback даёт outcome_unknown.

## Наблюдение и устойчивость

Gauge root schema_version сохраняется1. В объекте конкретной камеры добавить
camera_contract_revision=siplite-camera/1.0.0, безопасные discovery/auth/actual
track/illumination сведения из local-camera.schema.json, без hardware_id local
wrapper и секретов. Existing snapshot_id/operation_id/revision и базовые поля
не заменять. App1 обновляет readers до включения нового firmware writer.

Schema body буферизуется в PSRAM; начальный budget512KiB, probe10s, read20s,
write/readback30s в общем deadline. Это camera memory budget, не permission
увеличить RPC/HTTP media JSON без контроля. Schema parsing не должно создавать
полный giant JSON tree во внутренней RAM. Измерять largest internal block и
PSRAM peak при SIP/RTP; не повторять ambiguous write/toggle.

Видео ingest только RTP push или RTSP pull; H.265 основной, Auto может выбрать
H.264 до START по подтверждённой несовместимости. READY, RTP freshness и decode
раздельны. Runtime failure не перезапускает поток и не меняет codec. Новая
попытка требует ручного START/новой epoch. Дополнительные сеты отложены.

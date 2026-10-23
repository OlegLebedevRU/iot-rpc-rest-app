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
нельзя выдумать в siplite. Разрешён только штатный native API с проверяемым
readback/recovery; установка companion на камеру запрещена. В принятом TASK-10
профиль импортирован как unverified: physical drive/probe/PWM=false.
RPC167 не воздействует на кандидатные пины; host model не подтверждает wiring.

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


## Реализация app1: negotiated reader/control

Новые REST task DTO включаются явно: верхнее поле
`camera_contract_revision: "siplite-camera/1.0.0"`. Оно используется только
при admission и не добавляется в существующий MQTT envelope. Без opt-in
RPC160..164 сохраняют прежнюю валидацию/таймауты;165..167 не принимаются.
Новая ветка использует точную immutable machine schema,8192 UTF-8 bytes,
depth12, строгие JSON types и unknown-field rejection. Read default20000ms,
write/discovery30000ms, power164 остаётся10000ms/max15000ms.

Устройство должно быть online по `app_connect`, не заблокировано и иметь
сохранённый gauge84 с camera revision и возрастом не более60s. Повтор того же
snapshot_id не освежает `updated_at`. Мутации дополнительно проверяют методы,
config revision, writable fields/ranges и port_verified/MAC/discovery generation.
Активный publisher блокирует изменения, требующие stop/apply/new START.
Viewer не получает право записи. Физические set/probe/confirm167 при текущем
stock-only профиле недоступны.

RPC165..167 используют inner operation UUID как **реальный task.id** и MQTT
correlation UUID. `ext_task_id` остаётся внешним ярлыком. Существующий task row —
постоянная квитанция: точный replay возвращает исходный id/created_at без новой
публикации; иной payload/метод/device/TTL/priority с тем же UUID даёт409.
Создание сериализовано PostgreSQL advisory lock. RES должен содержать тот же
operation_id, укладываться в4096 bytes и отдельно пройти обычный result commit.
Совпадение RES не означает сохранение gauge; проверять snapshot_id через gauges API.

Cloud166 принимает только sealed envelope, не расшифровывает и не меняет его.
Проверяются SN, operation UUID, canonical base64/размеры и deadline ≤60s;
DB task deadline ограничен envelope expiry. В истории/логах/ошибках/results
редактируется **весь** sealed_credentials. RPC49/50 не предоставляют обход
для user/password/private profile в cfg_cam. Невалидный HTTP input не отражается
в error body. Новый vault/key lifecycle в IoT не вводится.

Существующий IoT Device хранит SN, а certificate inventory — serial/expiry,
но это не trusted public PEM/key lookup. Endpoint выдачи актуального публичного
сертификата с проверкой CA/SN/validity/revocation должен использовать существующий
provisioning/PKI. Его подключение принадлежит BFF/владельцу PKI. Gauge public key
не является authority. Отсутствие готового BFF lookup не блокирует видео или
IoT forwarding уже корректно запечатанного envelope.

### HTTP projection и camera producer

Для существующего `GET /api/internal/v1/remote-input/devices/{sn}/video-capabilities`
передать `X-L4-Camera-Contract: siplite-camera/1.0.0`. Ответ содержит
`camera_contract_revision`, безопасный `camera`, `main_app_online`, `fresh` и
`producer_adapter={ready,reason,source_type,source_id,control_version,control_mode,recovery_policy}`.
`negotiated_v2=false`, `video_capabilities=null`: Windows MFT/binding не выдумывается.
Без заголовка сохраняется desktop projection; неизвестная revision даёт422.

Publisher использует существующую stream lease с точной org/user/session authority.
`GET .../lease/{id}/video-lease` возвращает её deadline. Negotiated
`POST .../lease/{id}/stream/start` принимает **media_start** из принятой camera schema:
`contract_version`, session/operation/publisher/lease IDs, authoritative
`lease_expires_at` в seconds и concrete camera descriptor. BFF выбирает Auto
по свежему пересечению camera/relay/server/browser до media prepare; explicit H265
не подменяется. IoT проверяет descriptor против сохранённого actual_track,
фиксирует epoch в Redis и адаптирует её к фактически исследованному siplite CTL v1:
`mode=usb-camera`, `source_id=cam:ip000001`, profile=default. Media descriptor
сохраняет `source_type=camera` и честные raster/codec/level. Topics и main_app не меняются.

Negotiated `GET .../video-state` возвращает camera identity/descriptor/state;
`POST .../video-stop` принимает **media_stop** с полной epoch identity.
Чтение extended state без заголовка даёт422. Renew использует серверный lease
deadline и точный stream_instance_id; устаревшие stop/renew/events не меняют новую epoch.
Cleanup проверяет lease под Redis WATCH, включая гонку renew/expiry, и отправляет
ограниченный stop своей эпохи. Неудача публикации/ACK завершает попытку с scoped
compensation; автоматических START/codec fallback нет.

`confirmation=command_ack` подтверждает только ответ relay. `actual_descriptor=null`
пока нет отдельного post-START доказательства; ACK не маркируется agent_ready,
RTP freshness или browser decode. Media health и framesDecoded проверяются отдельно.
Класс CameraMediaAdapter проверяет принятые HTTP shapes, negotiated header,
service auth, immutable descriptor/identity/route generation и scoped compensation.
Он не пересылает camera credentials или plaintext в l4media.

Начальный deploy — readers/control с `APP_CONFIG__CAMERA__WRITERS_ENABLED=false`
по умолчанию. Включать новый START/мутации только после готовности TASK-60 firmware
и соответствующего server-ready gate. Старый camera/desktop путь не изменён.
Фактический native reference при разработке: l4_video_ctl.c принимает CTL v1,
а main MQTT app публикует app_online/app_offline; desktop CTL v2 ему не приписывается.

Scoped CI выполняется на действующем builder: `python3 deploy/check_siplite_camera.py`.
Он запускает locked dependencies, immutable verifier, camera/RPC/desktop regressions
и scoped Ruff/Black. Выпуск дополнительно запускает полный pytest через
`deploy/registry_app1.py`; GitHub hosted Actions не является обязательным transport.

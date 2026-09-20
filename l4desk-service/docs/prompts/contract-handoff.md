# Единый журнал передачи контрактов L4Desk

**Назначение:** единственный источник фактически зафиксированных межагентных контрактов каскада.  
**Режим:** append-only после секции «Принятые handoff-блоки».  
**Начальное состояние:** `READY_FOR_00A`.  
**Версия формата:** `1.0.0`.

Ни архитектурный документ, ни исходный код соседнего проекта, ни deployed endpoint, ни память агента не заменяют запись в этом журнале. Если требуемого принятого блока нет, агент не предполагает контракт и возвращает `BLOCKED_CONTRACT`.

## 1. Однозначное чтение входного контракта

Для каждого `required_handoff_id`, указанного в локальном промпте, агент обязан:

1. Искать точную пару HTML-маркеров:
   - `<!-- HANDOFF:<required_handoff_id>:BEGIN -->`;
   - `<!-- HANDOFF:<required_handoff_id>:END -->`.
2. Требовать ровно одну пару маркеров. Ноль или более одной пары означает `BLOCKED_CONTRACT`.
3. Разбирать только YAML-блок между маркерами; окружающий текст не является контрактом.
4. Проверять одновременно:
   - `handoff_id` точно совпадает с искомым;
   - `status` равен `ACCEPTED`;
   - `consumers` содержит текущий `prompt_id` либо точное значение `ALL_FOLLOWING`;
   - `contract_version` не пуст;
   - `contract_kinds` — непустой список разрешённых значений;
   - `artifact_paths` и `artifact_sha256` имеют одинаковое ненулевое число элементов, если `contract_kinds` не состоит только из `SEQUENCE_GATE`;
   - отсутствуют `TBD`, `TODO`, `UNKNOWN`, незаполненные обязательные поля;
   - `accepted_at_utc`, `producer_commit`, `producer_report_path` заполнены;
   - `deployment_status` соответствует требованию локального prompt;
   - блок не отозван более поздним `REVOCATION` и не заменён несовместимой записью `supersedes`.
5. Зафиксировать `handoff_id`, `contract_version` и digest артефактов в отчёте до начала реализации.
6. Не объединять конфликтующие версии самостоятельно. При конфликте остановиться.

`artifact_paths` — пути или immutable URL, доступные агенту без просмотра исходного кода чужого проекта. Digest считается по байтам опубликованного артефакта. Текст `contract_payload` может содержать краткую нормативную семантику, но крупные OpenAPI/JSON Schema/golden fixtures передаются отдельными immutable artifacts.

## 2. Кто пишет журнал

- Runtime-агент с `scope_project`, отличным от `l4desk-service`, **не редактирует этот файл**. Он помещает полностью заполненный candidate-блок в отчёт своего проекта.
- Контроллер каскада независимо проверяет отчёт, commit, push, deploy и smoke, затем добавляет candidate-блок в конец этого файла одной append-only операцией.
- Агент `l4desk-service` может сам добавить свой блок, потому что файл находится в его единственном scope.
- Принятый блок не исправляется на месте. Ошибка оформляется новым `REVOCATION`, затем новым handoff с новым идентификатором/версией и явным `supersedes`.
- До фактического появления принятого блока следующий агент не запускается.

## 3. Канонический формат принятого handoff

````text
<!-- HANDOFF:H-L4D-XX-v1:BEGIN -->
```yaml
handoff_id: H-L4D-XX-v1
status: ACCEPTED
contract_kinds:
  - API
  - EVENT
producer_prompt_id: L4D-XX-SCOPE
producer_scope_project: exact-project-name
producer_report_path: immutable/path/or/url/to/report.md
producer_branch: l4desk/l4d-xx-scope
producer_commit: full-commit-sha
accepted_at_utc: 2026-09-17T12:00:00Z
contract_version: exact-semver-or-revision
schema_revision: exact-revision-or-N/A
artifact_version: exact-version-or-N/A
artifact_paths:
  - immutable/path/or/url/to/artifact
artifact_sha256:
  - lowercase-sha256
compatibility:
  backward_compatible_with:
    - exact-version
  breaking_changes: false
  notes: exact-normative-notes
deployment_status: DEPLOYED | PUBLISHED | DOCS_PUBLISHED
deployed_environment: production | artifact-registry | documentation
feature_flags:
  exact_flag: disabled | shadow | enabled
contract_payload:
  identifiers: exact identifiers or N/A
  operations_events: exact operations/events or N/A
  errors: exact error model or N/A
  invariants: exact normative invariants
supersedes: []
known_risks: []
consumers:
  - L4D-NEXT-PROMPT
next_prompt_id: L4D-NEXT-PROMPT
```
<!-- HANDOFF:H-L4D-XX-v1:END -->
````

В реальном блоке внешняя ограда Markdown вокруг YAML не добавляется: между HTML-маркерами размещается один fenced `yaml` block. Маркеры и `handoff_id` должны совпадать посимвольно.

## 4. Формат отзыва

````text
<!-- REVOCATION:H-L4D-XX-v1:BEGIN -->
```yaml
handoff_id: H-L4D-XX-v1
status: REVOKED
revoked_at_utc: 2026-09-17T13:00:00Z
reason: точная причина
replacement_handoff_id: H-L4D-XX-v2 | NONE
controller_commit: full-commit-sha
```
<!-- REVOCATION:H-L4D-XX-v1:END -->
````

Отозванный handoff запрещено использовать, даже если replacement ещё не принят.

## 5. Правила candidate-блока агента

Candidate обязан быть готов к дословной вставке и содержать только факты завершённой работы. Агенту запрещено:

- ставить `ACCEPTED` до зелёных проверок, push, deploy/publish и smoke;
- указывать несуществующий artifact path или вычислять digest «на глаз»;
- передавать секреты;
- описывать незавершённую семантику словами «будет», `TBD` или `TODO`;
- расширять `consumers` без необходимости;
- менять входной контракт внутри выходного блока.

Если контракт не создаётся, шаг всё равно выпускает handoff с `contract_kinds: [SEQUENCE_GATE]` либо `[REPORT]` и immutable отчётом с digest, чтобы следующий prompt мог доказать соблюдение последовательности.

## 6. Bootstrap

Каскад ещё не запускался. Единственный prompt, разрешённый без входного handoff: `L4D-00A-TOOLS`. После его принятия каждый следующий prompt обязан иметь как минимум handoff непосредственно предыдущего шага.

## 7. Принятые handoff-блоки

Новые блоки добавляются только ниже этой строки в порядке каскада. На момент создания журнала принятых runtime-контрактов нет.

<!-- HANDOFF:H-L4D-00A-TOOLS-v1:BEGIN -->
```yaml
handoff_id: H-L4D-00A-TOOLS-v1
status: ACCEPTED
contract_kinds:
  - FIXTURES
producer_prompt_id: L4D-00A-TOOLS
producer_scope_project: tools
producer_report_path: tools/docs/l4desk/handoffs/L4D-00A-TOOLS-report.md
producer_branch: l4desk/l4d-00a-tools
producer_commit: cff9ddfb4a023eb10e01cab84fe918847849a943
accepted_at_utc: 2026-09-17T17:10:00Z
contract_version: 1.7.7
schema_revision: N/A
artifact_version: 1.7.7
artifact_paths:
  - tools/docs/l4desk/fixtures/rpc_7000_stream_control.json
  - tools/docs/l4desk/fixtures/rpc_7001_exec.json
  - tools/docs/l4desk/fixtures/rpc_7002_cancel.json
  - tools/docs/l4desk/fixtures/mqtt_presence_lifecycle.json
  - tools/docs/l4desk/fixtures/l4rtp_wire_protocol.json
  - tools/docs/l4desk/fixtures/baseline_capabilities.json
  - https://l4tools-generic.ar.cloud.ru/l4tools/1.7.7/l4setup.exe
artifact_sha256:
  - dba8ff769f12239765c2317b96a8fa2e8f60cdccbc0de00113b9d4ce7e54b9b8
  - 4007bbf50a5280abfaf747f7c8a28344a4f61e2ac4f2a60a0c80aec5018578bf
  - 2965f6e24d8c88b82b08b6dec892c271750a91f1a89f82cc8eb1b19fa8779d22
  - f6a59507fc9cbed6c2f4bf707360affedb6344cac01b7f49b12d8cf3cff08e28
  - eb8500895d8f679cd0baa59e150c8b94e8a78d8eca5b7c9f086654c066c35277
  - 375412eaa61e31e72b2ea5f002862a1d1f02becdd4626a71af31d9400df560cb
  - 874f5444d2d4cc9bdee39e7c25a1265a2dd98f388aca49ef205ffb764531cd88
compatibility:
  backward_compatible_with:
    - 1.7.6
    - 1.7.7
  breaking_changes: false
  notes: Опубликованный baseline агента l4tools 1.7.7. Поддержка Windows NT 6.1+ (Win7 SP1, Win10, Win11), TLS 1.2 SChannel.
deployment_status: PUBLISHED
deployed_environment: artifact-registry
feature_flags:
  l4con_cmd_exec: enabled
  l4desk_desktop_stream: enabled
contract_payload:
  identifiers: SN (ASCII, 9-10 символов), stream_instance_id, command_id, session_id, taskId
  operations_events: Метод 7000 (CMD_DIAG_STREAM_CONTROL - inventory_get, stream_start, stream_stop, lease_renew, mouse_click, key_event, shortcut_action), Метод 7001 (CMD_DIAG_EXEC - cmd/powershell execution, выгрузка чанков в dev/{SN}/out и итоговый ответ в dev/{SN}/res), Метод 7002 (CMD_DIAG_CANCEL), LWT presence dev/{SN}/svc (extra_service) и dev/{SN}/app (main_app)
  errors: stream start rejected/already_running, desktop_locked, session_unavailable, input_rejected, exec ttl_sec timeout, sas ctrl_alt_del hardware intercept
  invariants: Ровно 1 активный видеопоток на терминал; автоматическое завершение по expires_at_ms; mTLS авторизация по CN={SN}; протокол L4RTP/1
supersedes: []
known_risks:
  - Прямой ввод Ctrl+Alt+Del через key_event перехватывается ядром Windows (требуется shortcut_action)
  - Пользовательский ввод отклоняется при заблокированной сессии Windows
  - Для Windows 7 SP1 требуется обновление безопасности с поддержкой TLS 1.2 (KB3140245)
consumers:
  - L4D-00B-IOT
  - L4D-00G-DOCS
next_prompt_id: L4D-00B-IOT
```
<!-- HANDOFF:H-L4D-00A-TOOLS-v1:END -->

<!-- HANDOFF:H-L4D-00B-IOT-v1:BEGIN -->
```yaml
handoff_id: H-L4D-00B-IOT-v1
status: ACCEPTED
contract_kinds:
  - REPORT
  - SEQUENCE_GATE
producer_prompt_id: L4D-00B-IOT
producer_scope_project: iot-rpc-rest-app
producer_report_path: docs/l4desk/handoffs/L4D-00B-IOT-report.md
producer_branch: l4desk/l4d-00b-iot
producer_commit: de431c15ca0064a9c2cbd3d9233d0b9921d85cff
accepted_at_utc: 2026-09-17T17:56:00Z
contract_version: 0.2.1
schema_revision: 2026_08_30_0003
artifact_version: 0.2.1
artifact_paths:
  - docs/l4desk/handoffs/L4D-00B-IOT-report.md
  - app-service/tests/core/test_l4d_00b_baseline_fixtures.py
artifact_sha256:
  - 136a65867165f6e33f55ef9c48054cd1020fb5d8f296bc4e62437032e0ceb7d8
  - a6a936fd972bdd6d04fe02290b8b14d852f0b8d1588cc479c0958a90c2e0b142
compatibility:
  backward_compatible_with:
    - 1.7.7
  breaking_changes: false
  notes: Совместимо с Agent fixtures 1.7.7 (все 333 теста iot-rpc-rest-app успешны, включая 12 тестов baseline fixtures). Подтверждена маршрутизация RabbitMQ srv.<SN>.{tsk,rsp,cmt,eva,ctl} и dev.<SN>.{req,ack,res,evt,out,ctl,app,svc}.
deployment_status: DEPLOYED
deployed_environment: production
feature_flags:
  alpha_billing: enabled
contract_payload:
  identifiers: SN (ASCII), taskId (UUID), clientId, session_id (UUID), command_id (UUID), lease_id (UUID)
  operations_events: RPC 7000 (CMD_DIAG_STREAM_CONTROL), 7001 (CMD_DIAG_EXEC), 7002 (CMD_DIAG_CANCEL), ctl low-latency input (pointer_move, mouse_click, key_event, shortcut_action), LWT app (app_online/app_offline), LWT svc (svc_online/svc_offline)
  errors: Стандартная модель ошибок REST API (400/401/403/404/409), MQTT NACK, task cancellation reason
  invariants: Инвариант единого воркера (WEB_CONCURRENCY=1 из-за in-memory lease/presence); не более 1 активного lease на терминал; app1 задеплоен на хосте 87.242.100.34 (Up 3 days, git commit 2488395)
supersedes: []
known_risks:
  - Состояние LeaseRegistry и pending-команд хранится в памяти процесса и требует WEB_CONCURRENCY=1 до внедрения распределённых блокировок
  - Отсутствует персистентный стрим событий с курсорами (будет реализован в L4D-02-IOT)
  - Взаимное исключение сессий консоли и видео на уровне всего сервиса ещё не объединено (будет реализовано в L4D-07-IOT)
consumers:
  - L4D-00C-PB
  - L4D-00G-DOCS
next_prompt_id: L4D-00C-PB
```
<!-- HANDOFF:H-L4D-00B-IOT-v1:END -->

<!-- HANDOFF:H-L4D-00C-PB-v1:BEGIN -->
```yaml
handoff_id: H-L4D-00C-PB-v1
status: ACCEPTED
contract_kinds:
  - REPORT
  - SEQUENCE_GATE
producer_prompt_id: L4D-00C-PB
producer_scope_project: ProcessingBackend
producer_report_path: ProcessingBackend/docs/l4desk/handoffs/L4D-00C-PB-report.md
producer_branch: l4desk/l4d-00c-pb
producer_commit: 3cec17844193e7b0cf094f2018380afe6bb14498
accepted_at_utc: 2026-09-17T18:25:00Z
contract_version: 1.0.0
schema_revision: "026"
artifact_version: 0.1.0
artifact_paths:
  - ProcessingBackend/docs/l4desk/handoffs/L4D-00C-PB-report.md
artifact_sha256:
  - 55aa7353f518edb6af1beec73622496139bbb70e5e8d84ccd4ad887a510b42cc
compatibility:
  backward_compatible_with:
    - N/A
  breaking_changes: false
  notes: Baseline audit and inventory of ProcessingBackend certificate contour, terminal auth, Alembic migration chain (head 026), and runtime state. Deployed commit on host 87.242.100.34: 5de0e6a39d89caae3fe0da517435f3708dfba2f7. No code or schema changes introduced.
deployment_status: DEPLOYED
deployed_environment: production
feature_flags:
  auto_set_cert_serial_on_licensebilling: enabled
  cert_discovery_audit: enabled
contract_payload:
  identifiers:
    sn: terminal serial number (string, e.g. a4b0000773c12345d210826)
    device_id: legacy device number (integer, e.g. 773)
    org_id: tenant organization ID (integer)
    terminal_id: internal primary key in terminals table (integer)
    cert_serial: active X.509 certificate hex serial (string)
    pin: 6-digit one-time enrollment code (string)
  operations_events:
    - GET/POST /api/certificates/?function=check&pin={pin}
    - POST /api/certificates/?function=setup (with PKCS#10 CSR body)
    - POST /api/devices/map_legacy_crt/
    - GET/POST /api/licensebilling
    - mcp-pin-server tools: generate_pin, revoke_pin, list_pins, get_terminal_cert_history, get_terminal_cert_discovery
  errors:
    certificates_api: XML Windows-1251 (<Response><Result>Error</Result><code>{1|2|4}</code><Description>{msg}</Description></Response>)
    licensebilling: XML UTF-8 (<Response><Result>ERROR</Result><Description>{msg}</Description></Response>), HTTP 401 on unrecognized/mismatched terminal
    map_legacy_crt: JSON HTTP 400/401/500
  invariants:
    - ProcessingBackend sole authority for database schema migrations (Alembic head 026)
    - Strict validation for iot.leo4.ru CA: sn == cn AND cert_serial == db_cert_serial
    - Legacy CA auto-binds cert_serial into terminal_cert_history upon first valid auth
    - PIN is single-use, transitioning from pending to used upon successful CSR signing
    - All issued certificates recorded in terminal_cert_history; all ingress cert sightings tracked in terminal_cert_discovery
supersedes: []
known_risks:
  - CSR signature is not cryptographically verified prior to forwarding to CA function
  - Concurrency gap in setup handler without row-level lock (SELECT ... FOR UPDATE) on pending PIN
  - Inability to safely retry setup if network drops after PIN status marked as used
consumers:
  - L4D-00D-MEDIA
  - L4D-00G-DOCS
next_prompt_id: L4D-00D-MEDIA
```
<!-- HANDOFF:H-L4D-00C-PB-v1:END -->

<!-- HANDOFF:H-L4D-00D-MEDIA-v1:BEGIN -->
```yaml
handoff_id: H-L4D-00D-MEDIA-v1
status: ACCEPTED
contract_kinds:
  - REPORT
  - SEQUENCE_GATE
producer_prompt_id: L4D-00D-MEDIA
producer_scope_project: l4media
producer_report_path: l4media/docs/l4desk/handoffs/L4D-00D-MEDIA-report.md
producer_branch: l4desk/l4d-00d-media
producer_commit: 47c9b3788aca3673effce91f372c0ebd66096069
accepted_at_utc: 2026-09-17T18:45:00Z
contract_version: 1.0.0
schema_revision: N/A
artifact_version: 1.0.0
artifact_paths:
  - l4media/docs/l4desk/handoffs/L4D-00D-MEDIA-report.md
artifact_sha256:
  - e038e84838a27ea87ca389568215ae9c45886781eb3c262e18605d59273461b4
compatibility:
  backward_compatible_with:
    - N/A
  breaking_changes: false
  notes: Baseline audit and inventory of l4media media contour: mTLS ingress, Janus WebRTC gateway, routes/mountpoints, stream lifecycle, health/stop endpoints, resource limits and unit budgets. No runtime code or configuration changes introduced.
deployment_status: DEPLOYED
deployed_environment: production
feature_flags: {}
contract_payload:
  identifiers:
    sn: terminal serial number (ASCII string, e.g. a4b0000773c12345d210826)
    mountpoint_id: Janus streaming mountpoint ID (integer, numeric ID e.g. 1001)
    rtp_port: dedicated UDP destination port for Janus RTP forwarder (integer, e.g. 5004, 5006)
    session_epoch: monotonic epoch counter per TCP connection in l4media-ingress (integer)
    stream_instance_id: UUID of video streaming session in tools / MenuBuilder (string)
  operations_events:
    - TCP :8443 (mTLS via Nginx stream proxy) -> TCP :9000 (l4media-ingress framing & demux)
    - L4RTP/1 framing (4-byte big-endian length prefix + RTP payload)
    - HTTP GET /health on :9100 (l4media-ingress health status & routes count)
    - HTTP GET /stats on :9100 (l4media-ingress active sessions, uptime, connection metrics)
    - HTTP GET /routes on :9100 (l4media-ingress list active SN -> Janus mountpoint route mappings)
    - HTTP POST /routes on :9100 (l4media-ingress dynamic route registration)
    - HTTP DELETE /routes?sn={sn} on :9100 (l4media-ingress dynamic route deletion)
    - HTTP GET /janus/info on :8088 (Janus WebRTC Gateway server information)
    - HTTP POST /admin on :8088 (Janus Admin API - create/destroy mountpoints)
    - HTTP POST /janus on :8088 (Janus Session/Plugin API - WebRTC SDP offer/answer)
  errors:
    ingress_http: 400 Bad Request (missing/invalid sn or route payload), 404 Route Not Found, 409 Route Already Exists, 500 Internal Error
    ingress_framing: TCP disconnect on invalid preamble/packet size > 65536, teardown on idle timeout (10s)
    nginx_mtls: SSL handshake failure, connection reset if client certificate not verified by iot_leo4_ca.crt
  invariants:
    - Mutual TLS required at outer ingress edge (:8443) with client cert verification against iot_leo4_ca.crt
    - TLS cipher profile @SECLEVEL=1 with AES-GCM + CBC/RSA fallback for Win7/SChannel clients
    - One active stream per terminal SN; dynamic route creation requires SN-mountpoint mapping
    - Idle timeout disconnect after 10 seconds of no RTP packets on established ingress stream
    - Janus WebRTC UDP port range constrained to 20000-20100/udp
    - Unit budgets: 1 core CPU, 768 MB RAM for entire media subsystem (128M nginx, 128M ingress, 512M janus), video bitrate 500-750 kbps, 15 fps 720p
supersedes: []
known_risks:
  - Dynamic route registration in l4media-ingress is in-memory only (lost on container restart)
  - Routes reload (/routes?action=reload or SIGHUP) depends on static routes.conf file
  - Shared media container memory budget has 0B swap on production host (OOM risk if Janus exceeds 512M under high concurrent sessions)
  - No persistent recording or technical detail archival implemented yet (addressed in future L4D-08A and L4D-15C)
consumers:
  - L4D-00E-MB
  - L4D-00G-DOCS
next_prompt_id: L4D-00E-MB
```
<!-- HANDOFF:H-L4D-00D-MEDIA-v1:END -->

<!-- HANDOFF:H-L4D-00E-MB-v1:BEGIN -->
```yaml
handoff_id: H-L4D-00E-MB-v1
status: ACCEPTED
contract_kinds:
  - REPORT
  - SEQUENCE_GATE
producer_prompt_id: L4D-00E-MB
producer_scope_project: MenuBuilder
producer_report_path: MenuBuilder/docs/l4desk/handoffs/L4D-00E-MB-report.md
producer_branch: l4desk/l4d-00e-mb
producer_commit: dabccacf7d9d7227d898af6f4f50e12ca9bf3f99
accepted_at_utc: 2026-09-17T19:35:00Z
contract_version: 0.1.0
schema_revision: N/A
artifact_version: 0.1.0
artifact_paths:
  - MenuBuilder/docs/l4desk/handoffs/L4D-00E-MB-report.md
  - MenuBuilder/docs/l4desk/snapshots/openapi_baseline.json
  - MenuBuilder/docs/l4desk/snapshots/inventory_baseline.json
artifact_sha256:
  - cdae906ca929b14235b499331e7a562727a5c694a49ef6939714467f19891279
  - 3514eff4b7e0e1654314518564b5f290d155c139bc86eb0af04c32917e89c301
  - 31896fcace9f6f8331b8938cebb2913f28b2c9e19e7b69725a3cacd659211a28
compatibility:
  backward_compatible_with:
    - N/A
  breaking_changes: false
  notes: Baseline audit and inventory of MenuBuilder commercial and UX contour. Unified seams proven for VideoPlayerScreen + RemoteControlOverlay, DeviceConsoleTab, Billing/License flows and RBAC/Tenant isolation without alternative flows. All 289 backend tests and 20 frontend tests passing. Production deployed commit 890f485c558126ab4fb82905aa2ed2c4623eab7c verified on host 87.242.100.34. No runtime code changes.
deployment_status: DEPLOYED
deployed_environment: production
feature_flags:
  remote_control_enabled: enabled
contract_payload:
  identifiers:
    org_id: tenant organization ID (integer)
    user_id: user ID (integer)
    terminal_id: terminal primary key ID (integer)
    sn: terminal serial number (ASCII string, e.g. a4b0000773c12345d210826)
    order_id: billing order UUID (string)
    lease_id: remote input control lease UUID (string)
    mountpoint_id: Janus streaming mountpoint ID (integer)
  operations_events:
    - POST /api/auth/login, POST /api/auth/logout, POST /api/auth/refresh, GET /api/auth/me
    - GET /api/admin/tenants/available, POST /api/admin/tenants/switch
    - GET /api/billing/summary, GET /api/billing/status, GET /api/billing/licenses, POST /api/billing/checkout
    - POST /api/certificate-pin/generate, GET /api/certificate-pin/status/{terminal_id}
    - POST /api/v1/video/devices/{device_id}/session
    - POST /api/v1/video/control/lease/acquire, POST /api/v1/video/control/lease/{id}/keepalive, POST /api/v1/video/control/lease/{id}/release
    - GET /api/v1/video/control/devices/{sn}/inventory, POST /api/v1/video/control/devices/{sn}/stream/start, POST /api/v1/video/control/devices/{sn}/stream/stop
    - GET /api/v1/video/control/ws/lease/{lease_id}
    - Nginx /janus-ws -> l4media-janus:8188 WebRTC
    - Nginx /api/internal/v1/diagnostics/ -> app1:8000 WebSocket Console
  errors:
    http_rest: 400 Bad Request, 401 Unauthorized, 403 Forbidden, 404 Not Found, 409 Conflict, 502 Bad Gateway
    ws_control: close code 4400 (Invalid Frame/JSON), 4401 (Unauthorized/No Token), 4403 (Foreign Lease/Forbidden), 4404 (Lease Not Found), 4408 (Lease Timeout/Expired)
  invariants:
    - Multi-tenant strict boundary isolation by org_id in all queries
    - RBAC roles: role 1 (superuser), role 3 (tenant admin), role 4 (viewer with granular permissions)
    - Zero alternative flows: L4Desk interactive stream utilizes VideoPlayerScreen + RemoteControlOverlay, console utilizes DeviceConsoleTab
    - Billing operations use whole minor units (kopecks) without float calculations
    - MenuBuilder does not run Alembic migrations (sole authority ProcessingBackend)
supersedes: []
known_risks:
  - Console and video mutual exclusion locking is not yet globally unified (addressed in L4D-07-IOT / L4D-08B-MB)
  - Fin ledger models and migrations are pending in shared and ProcessingBackend (addressed in L4D-04A-C and L4D-09-MB)
  - User self-registration and public onboarding endpoint not yet implemented (addressed in L4D-05-MB)
consumers:
  - L4D-00F-SHARED
  - L4D-00G-DOCS
next_prompt_id: L4D-00F-SHARED
```
<!-- HANDOFF:H-L4D-00E-MB-v1:END -->

<!-- HANDOFF:H-L4D-00F-SHARED-v1:BEGIN -->
```yaml
handoff_id: H-L4D-00F-SHARED-v1
status: ACCEPTED
contract_kinds:
  - REPORT
  - MODEL_BASELINE
producer_prompt_id: L4D-00F-SHARED
producer_scope_project: shared/etranprocessing_db
producer_report_path: shared/docs/l4desk/handoffs/L4D-00F-SHARED-report.md
producer_branch: l4desk/l4d-00f-shared
producer_commit: 97094aedf52bb6d1c8285d8df30d7346307cb946
accepted_at_utc: 2026-09-17T20:15:00Z
contract_version: 0.1.0
schema_revision: N/A
artifact_version: 0.1.0
artifact_paths:
  - shared/docs/l4desk/handoffs/L4D-00F-SHARED-report.md
artifact_sha256:
  - e96ffab67cd53ef823afe88506b693305e22386b14331b2fe3aed6452235be21
compatibility:
  backward_compatible_with:
    - N/A
  breaking_changes: false
  notes: Baseline audit and inventory of shared thin declarative ORM model layer (etranprocessing_db). 31 unified declarative models verified, pure SQLAlchemy 2.0 without framework/business/auth/crypto dependencies, Python 3.14 compatibility confirmed, linters/formatters passing, fin_* safe expand points documented without modifying runtime models.
deployment_status: DEPLOYED
deployed_environment: local_package
feature_flags: {}
contract_payload:
  identifiers:
    package_name: etranprocessing-db
    module_name: etranprocessing_db
    models_count: 31
    base_class: etranprocessing_db.base.Base
  models:
    auth:
      - ApiToken (api_tokens)
      - User (users)
      - UserSession (user_sessions)
    billing:
      - BillingOrder (billing_orders)
      - BillingOrderItem (billing_order_items)
      - CertificatePin (certificate_pins)
    catalog:
      - CatalogCategory (catalog_categories)
      - CatalogItem (catalog_items)
    email:
      - EmailVerification (email_verifications)
      - EmailLog (email_logs)
    menu:
      - MenuVariant (menu_variants)
      - MenuVariantSnapshot (menu_variant_snapshots)
      - Group (groups)
      - Service (services) [alias ServiceMenu]
      - TerminalMenuBinding (terminal_menu_bindings)
    org:
      - Org (orgs)
      - OrgBillingSettings (org_billing_settings)
      - OrgStatus (org_statuses)
    payment:
      - Tsp (tsp)
      - TspParameterCode (tsp_parameter_codes)
      - Payment (payments)
      - PaymentParam (payment_params)
      - BalanceTerminalTsp (balance_terminal_tsp)
    telemetry:
      - GateGaugeRecord (gate_gauge_records)
      - TechGateRecord (tech_gate_records)
      - TerminalGaugeState (terminal_gauge_states)
    terminal:
      - TerminalType (terminal_types)
      - Terminal (terminals)
      - License (licenses)
      - TerminalCertHistory (terminal_cert_history)
      - TerminalCertDiscovery (terminal_cert_discovery)
  conventions:
    orm_style: SQLAlchemy 2.0 DeclarativeBase, Mapped[T] = mapped_column(...)
    money_representation: integer minor units (kopecks) in BigInteger, float strictly prohibited
    timestamps: DateTime(timezone=True) with server_default=func.now()
    naming: PascalCase classes, snake_case tables, idx_/ix_ indexes, ck_ checks, uq_ uniques
  expand_points_fin:
    target_module: shared/etranprocessing_db/models/fin.py
    target_models:
      - FinAccount (fin_accounts)
      - FinTariffVersion (fin_tariff_versions)
      - FinBillingCycle (fin_billing_cycles)
      - FinUsageDaily (fin_usage_daily)
      - FinTerminalMonthlyCharge (fin_terminal_monthly_charges)
      - FinPayment (fin_payments)
      - FinManualPayment (fin_manual_payments)
      - FinLedgerTransaction (fin_ledger_transactions)
      - FinLedgerEntry (fin_ledger_entries)
      - FinBalanceProjection (fin_balance_projections)
      - FinNotificationDelivery (fin_notification_deliveries)
      - FinReconciliationRun (fin_reconciliation_runs)
      - FinArchiveBatch (fin_archive_batches)
    foreign_keys_to_existing:
      - orgs.org_id (as tenant_id)
      - terminals.id
      - users.id (audit actor)
supersedes: []
known_risks: []
consumers:
  - L4D-00G-DOCS
next_prompt_id: L4D-00G-DOCS
```
<!-- HANDOFF:H-L4D-00F-SHARED-v1:END -->

<!-- HANDOFF:H-L4D-00G-DOCS-v1:BEGIN -->
```yaml
handoff_id: H-L4D-00G-DOCS-v1
status: ACCEPTED
contract_kinds:
  - REPORT
  - SEQUENCE_GATE
producer_prompt_id: L4D-00G-DOCS
producer_scope_project: l4desk-service
producer_report_path: l4desk-service/docs/handoffs/L4D-00G-DOCS-report.md
producer_branch: l4desk/l4d-00g-docs
producer_commit: 4f57f607c8ff34bf75cf1ad76fccc263e25f32f2
accepted_at_utc: 2026-09-17T20:30:00Z
contract_version: 1.0.0
schema_revision: N/A
artifact_version: 1.0.0
artifact_paths:
  - l4desk-service/docs/handoffs/L4D-00G-DOCS-report.md
artifact_sha256:
  - fdc2817bd5a51e80f4ec36ba45ed7e33b3a4ef39771173d58c4330d37d38886a
compatibility:
  backward_compatible_with:
    - 1.7.7
    - 0.2.1
    - 1.0.0
    - 0.1.0
  breaking_changes: false
  notes: Central baseline contract matrix consolidating all six Stage 00 baseline handoffs (00A-TOOLS through 00F-SHARED). Zero contract conflicts detected. Exact baselines verified and locked for Stage 01.
deployment_status: DOCS_PUBLISHED
deployed_environment: documentation
feature_flags: {}
contract_payload:
  identifiers:
    sn: ASCII string (9-10 chars classic, up to 23+ extended)
    device_id: integer kiosk identifier
    terminal_id: integer primary key in terminals table
    org_id: integer tenant organization ID (mapped to tenant_id)
    user_id: integer user ID
    session_id: UUID remote session identifier
    stream_instance_id: UUID video streaming session identifier
    lease_id: UUID remote input control lease identifier
    mountpoint_id: integer Janus WebRTC mountpoint identifier
    pin: 6-digit one-time certificate enrollment code
    order_id: UUID billing order identifier
  baselines:
    tools: version 1.7.7, L4RTP/1, methods 7000/7001/7002, LWT dev/{SN}/svc & dev/{SN}/app
    iot_rpc_rest_app: version 0.2.1, schema 2026_08_30_0003, RabbitMQ srv/dev topics, WEB_CONCURRENCY=1
    processing_backend: version 1.0.0, Alembic head 026, PIN/CSR/X.509 API, mTLS Nginx
    l4media: version 1.0.0, mTLS :8443 ingress, L4RTP/1 demux, Janus WebRTC :8088/:8188
    menubuilder: version 0.1.0, VideoPlayerScreen + RemoteControlOverlay, DeviceConsoleTab, RBAC multi-tenant
    shared_etranprocessing_db: version 0.1.0, 31 declarative SQLAlchemy 2.0 models, Thin DB Layer
  invariants:
    - No unverified architectural claims treated as implemented
    - Strict cross-project boundaries without direct DB or private queue coupling
    - Zero alternative UX flows for console/video in MenuBuilder
    - Whole minor units (kopecks) for all financial representations
    - ProcessingBackend sole authority for database schema migrations
    - Append-only cascade governance via contract-handoff.md
supersedes: []
known_risks:
  - Windows SAS Ctrl+Alt+Del hardware intercept requires shortcut_action in Agent
  - In-memory LeaseRegistry in IoT requires WEB_CONCURRENCY=1 until distributed locks (L4D-07-IOT)
  - Missing persistent event feed with cursors in IoT (scheduled for L4D-02-IOT)
  - Console and video mutual exclusion not globally unified (scheduled for L4D-07-IOT / L4D-08B-MB)
  - Concurrency gap without row lock in PB PIN setup handler (scheduled for L4D-06A-PB)
  - Dynamic media routes in memory only with 0B host swap (monitored, scheduled for L4D-08A-MEDIA)
  - fin_* models and double-entry subledger not yet implemented (scheduled for L4D-04A-C, L4D-09-MB)
  - Public user self-registration not yet implemented (scheduled for L4D-05-MB)
consumers:
  - L4D-01A-TOOLS
next_prompt_id: L4D-01A-TOOLS
```
<!-- HANDOFF:H-L4D-00G-DOCS-v1:END -->

<!-- HANDOFF:H-L4D-01A-TOOLS-v1:BEGIN -->
```yaml
handoff_id: H-L4D-01A-TOOLS-v1
status: ACCEPTED
contract_kinds:
  - FIXTURES
producer_prompt_id: L4D-01A-TOOLS
producer_scope_project: tools
producer_report_path: tools/docs/l4desk/handoffs/L4D-01A-TOOLS-report.md
producer_branch: l4desk/l4d-01a-tools
producer_commit: c33030bc5f9ac07a010d5ff8c9b996c80c1def85
accepted_at_utc: 2026-09-17T20:45:00Z
contract_version: 1.0.0
schema_revision: 2026-09-17-v1
artifact_version: 1.7.7
artifact_paths:
  - tools/docs/l4desk/contracts/agent_compatibility_contract_v1.json
  - tools/docs/l4desk/contracts/schemas/agent_contract_v1.schema.json
  - tools/docs/l4desk/contracts/schemas/presence_event.schema.json
  - tools/docs/l4desk/contracts/schemas/rpc_7000_stream_control.schema.json
  - tools/docs/l4desk/contracts/schemas/rpc_7001_exec.schema.json
  - tools/docs/l4desk/contracts/schemas/rpc_7002_cancel.schema.json
  - tools/docs/l4desk/contracts/schemas/l4rtp_wire_protocol.schema.json
  - tools/docs/l4desk/fixtures/golden_vectors_v1.json
  - tools/tests/test_agent_compatibility_contract_v1.py
artifact_sha256:
  - 38e4ae5f13d563b3ae57a83259d63f9a63049d528d9667ae33efbd5a1e71267a
  - f065dd53101c4bf90b237c85082a05eea212e1a2b3de39d2bf890708e3a42f1d
  - fd061b7a1a113ec4ba518208e5693ffad98593cd8096d9a013f34a0ca7748d07
  - d7ed9deaeddc4a8a5f668cd59ac95aa0941aeff083e4ef6d94a1c9e75ba4ab6e
  - fb511cfb368f809fb042dbece552d7f24aeedb384f7186915f82e1dfb561ee1b
  - a1dac309f324b1d0e2073ac8ab251ed70f6cfd191c46ae38f3c9192854079a8f
  - b38aeeda96a5df81561117a0acb13606b417f136abb5250e72d41d38b630bd53
  - b4f3c1a465e88babf89c0850cfd8dffc29a4cd921ec51a73e2112e6cf9c3034b
  - 7e6ce52fc9351cc8a95134bcde0304fc208e0fdbec3287f279b2a7bfd0db0d52
compatibility:
  backward_compatible_with:
    - 1.7.6
    - 1.7.7
  breaking_changes: false
  notes: Исполняемый контракт совместимости Agent Compatibility Contract v1 и golden vectors для l4tools 1.7.7/1.7.6. Фиксация тем топиков, кодов методов (7000, 7001, 7002), JSON схем запросов и ответов, LWT/presence, L4RTP/1 wire protocol без изменения бинарных файлов агента.
deployment_status: PUBLISHED
deployed_environment: artifact-registry
feature_flags:
  l4con_cmd_exec: enabled
  l4desk_desktop_stream: enabled
contract_payload:
  identifiers:
    sn_pattern: "^[0-9A-Za-z_-]{6,32}$"
    cert_dn_pattern: "CN={SN}"
    task_id_pattern: "^task-[a-z0-9-]+$"
    session_id_pattern: "^sess-[a-z0-9-]+$"
  operations_events:
    presence_topics:
      - "dev/{SN}/app"
      - "dev/{SN}/svc"
    rpc_topics:
      - "srv/{SN}/tsk"
      - "srv/{SN}/rsp"
      - "dev/{SN}/out"
      - "dev/{SN}/res"
    methods:
      - code: 7000
        name: "STREAM_CONTROL"
        actions: ["inventory_get", "stream_start", "lease_renew", "stream_stop", "mouse_click", "key_event", "shortcut_action"]
      - code: 7001
        name: "EXEC_COMMAND"
        shells: ["cmd", "powershell"]
      - code: 7002
        name: "CANCEL_TASK"
        statuses: ["cancelled", "not_found", "already_finished"]
  errors:
    stream_errors: ["desktop_locked", "session_unavailable", "already_running", "invalid_button", "forbidden_key", "unsupported_action", "device_not_found", "encoder_failure"]
    exec_errors: ["timed_out", "failed", "cancelled"]
  invariants:
    - "No financial, billing, entitlement, or organization fields in agent payloads or topics"
    - "All device topics strictly prefixed with dev/{SN}/ and server topics with srv/{SN}/"
    - "Presence messages published with QoS 1 and retain = true"
    - "Method codes 7000, 7001, 7002 and action names are immutable and backward-compatible"
    - "Streaming output chunks over dev/{SN}/out have monotonic sequence numbering and boolean eof"
    - "No MQTT client was created or modified in tools"
    - "Published agent binary release remains 1.7.7"
supersedes:
  - H-L4D-00A-TOOLS-v1
known_risks:
  - "Interactive mouse/key input injection is rejected if screen is locked or session unavailable"
  - "L4RTP UDP loopback fallback on legacy Windows systems without native loopback fast path"
consumers:
  - L4D-01B-IOT
next_prompt_id: L4D-01B-IOT
```
<!-- HANDOFF:H-L4D-01A-TOOLS-v1:END -->

<!-- HANDOFF:H-L4D-01B-IOT-v1:BEGIN -->
```yaml
handoff_id: H-L4D-01B-IOT-v1
status: ACCEPTED
contract_kinds:
  - DEPLOYMENT
  - FIXTURES
producer_prompt_id: L4D-01B-IOT
producer_scope_project: iot-rpc-rest-app
producer_report_path: docs/l4desk/handoffs/L4D-01B-IOT-report.md
producer_branch: l4desk/l4d-01b-iot
producer_commit: 0307dd7953b339ee48c3068a490732c82ea4e401
accepted_at_utc: 2026-09-17T21:45:00Z
contract_version: 1.0.0
schema_revision: 2026-09-17-v1
artifact_version: 1.0.0
artifact_paths:
  - app-service/core/adapters/agent_contract_v1.py
  - app-service/tests/core/test_l4d_01b_agent_contract_v1.py
  - docs/l4desk/handoffs/L4D-01B-IOT-report.md
artifact_sha256:
  - 4c22174762d570dd70cbcbea28fc419748184a9a65ae9296f3f7577d7fa584e8
  - 0c5005d42935736030c793af7b4e3c9e08ba382523750d742d5a2d169e768a7f
  - 9e7bec92783a8cdab71777296d7e0440f2df0a56183f689883974cf0e390f69a
compatibility:
  backward_compatible_with:
    - 1.7.6
    - 1.7.7
  breaking_changes: false
  notes: Реализован и протестирован AgentContractV1Adapter (app-service/core/adapters/agent_contract_v1.py), обеспечивающий полную совместимость с Agent Compatibility Contract v1 (агенты 1.7.6 и 1.7.7). Подтверждена неизменяемость топиков dev/{SN}/app, dev/{SN}/svc, srv/{SN}/rsp, srv/{SN}/ctl, dev/{SN}/out, dev/{SN}/res, методов 7000/7001/7002, wire protocol L4RTP/1. Внедрен assert_no_commercial_fields, исключающий передачу биллинговых/финансовых полей. Пройдены все 25 golden vectors, 24 теста контракта, 357 тестов в репозитории.
deployment_status: DEPLOYED
deployed_environment: production
feature_flags:
  agent_contract_v1: enabled
  alpha_billing: enabled
contract_payload:
  identifiers:
    sn_pattern: "^[0-9A-Za-z_-]{6,32}$"
    session_id_pattern: "^(sess-[a-z0-9-]+|[0-9a-fA-F-]{36})$"
    command_id_pattern: "^[a-z0-9_-]{1,64}$"
    task_id_pattern: "^task-[a-z0-9-]+$"
  operations_events:
    presence_topics:
      - "dev/{SN}/app"
      - "dev/{SN}/svc"
    rpc_topics:
      - "srv/{SN}/rsp"
      - "srv/{SN}/ctl"
      - "dev/{SN}/out"
      - "dev/{SN}/res"
    methods:
      - code: 7000
        name: "STREAM_CONTROL"
        actions: ["inventory_get", "stream_start", "lease_renew", "stream_stop", "mouse_click", "key_event", "shortcut_action"]
      - code: 7001
        name: "EXEC_COMMAND"
        shells: ["cmd", "powershell"]
      - code: 7002
        name: "CANCEL_TASK"
        statuses: ["cancelled", "not_found", "already_finished"]
  errors:
    stream_errors: ["desktop_locked", "session_unavailable", "already_running", "invalid_button", "forbidden_key", "unsupported_action", "device_not_found", "encoder_failure"]
    exec_errors: ["timed_out", "failed", "cancelled"]
  invariants:
    - "No financial, billing, entitlement, or organization fields transmitted to Agent"
    - "Existing MQTT client preserved; no new client created"
    - "Streaming output chunks over dev/{SN}/out have monotonic seq >= 1 and boolean eof"
    - "Single-worker invariant preserved (WEB_CONCURRENCY=1)"
    - "Deployed container app1 running on etranprocessing (87.242.100.34)"
supersedes:
  - H-L4D-00B-IOT-v1
known_risks:
  - "In-memory session registry requires WEB_CONCURRENCY=1 until distributed Redis storage is added (L4D-07-IOT)"
  - "Interactive mouse/key input injection is rejected if screen is locked or session unavailable"
consumers:
  - L4D-01C-DOCS
next_prompt_id: L4D-01C-DOCS
```
<!-- HANDOFF:H-L4D-01B-IOT-v1:END -->

<!-- HANDOFF:H-L4D-01C-DOCS-v1:BEGIN -->
```yaml
handoff_id: H-L4D-01C-DOCS-v1
status: ACCEPTED
contract_kinds:
  - SEQUENCE_GATE
  - FIXTURES
producer_prompt_id: L4D-01C-DOCS
producer_scope_project: l4desk-service
producer_report_path: l4desk-service/docs/handoffs/L4D-01C-DOCS-report.md
producer_branch: l4desk/l4d-01c-docs
producer_commit: b07962f8805666581d87a7d4b064dcafb2e869fb
accepted_at_utc: 2026-09-17T22:05:00Z
contract_version: 1.0.0
schema_revision: 2026-09-17-v1
artifact_version: 1.7.7
artifact_paths:
  - l4desk-service/docs/handoffs/L4D-01C-DOCS-report.md
  - tools/docs/l4desk/contracts/agent_compatibility_contract_v1.json
  - tools/docs/l4desk/fixtures/golden_vectors_v1.json
artifact_sha256:
  - 130b56a4e67bd9b3b87df52629e85e5ac6230657c59e49d2b6aebc98a8fac358
  - 38e4ae5f13d563b3ae57a83259d63f9a63049d528d9667ae33efbd5a1e71267a
  - b4f3c1a465e88babf89c0850cfd8dffc29a4cd921ec51a73e2112e6cf9c3034b
compatibility:
  backward_compatible_with:
    - 1.7.6
    - 1.7.7
  breaking_changes: false
  notes: Зарегистрирована и нормативно принята доказанная пара контрактов Agent Compatibility Contract v1 (tools 1.7.7/1.7.6) и deployed provider AgentContractV1Adapter (iot-rpc-rest-app 1.0.0). Подтверждено нулевое расхождение по топикам, кодам методов (7000/7001/7002), LWT presence, L4RTP/1 wire protocol и кодам ошибок. Подтверждена изоляция коммерческих полей (assert_no_commercial_fields) и прохождение всех 25 golden vectors.
deployment_status: DOCS_PUBLISHED
deployed_environment: documentation
feature_flags:
  agent_contract_v1: enabled
  alpha_billing: enabled
contract_payload:
  identifiers:
    sn_pattern: "^[0-9A-Za-z_-]{6,32}$"
    session_id_pattern: "^(sess-[a-z0-9-]+|[0-9a-fA-F-]{36})$"
    command_id_pattern: "^[a-z0-9_-]{1,64}$"
    task_id_pattern: "^task-[a-z0-9-]+$"
  operations_events:
    presence_topics:
      - "dev/{SN}/app"
      - "dev/{SN}/svc"
    rpc_topics:
      - "srv/{SN}/rsp"
      - "srv/{SN}/ctl"
      - "dev/{SN}/out"
      - "dev/{SN}/res"
    methods:
      - code: 7000
        name: "STREAM_CONTROL"
        actions: ["inventory_get", "stream_start", "lease_renew", "stream_stop", "mouse_click", "key_event", "shortcut_action"]
      - code: 7001
        name: "EXEC_COMMAND"
        shells: ["cmd", "powershell"]
      - code: 7002
        name: "CANCEL_TASK"
        statuses: ["cancelled", "not_found", "already_finished"]
  errors:
    stream_errors: ["desktop_locked", "session_unavailable", "already_running", "invalid_button", "forbidden_key", "unsupported_action", "device_not_found", "encoder_failure"]
    exec_errors: ["timed_out", "failed", "cancelled"]
  invariants:
    - "No financial, billing, entitlement, or organization fields transmitted to Agent"
    - "Monotonic chunk sequencing seq >= 1 and boolean eof for command output"
    - "Zero changes to Agent MQTT protocol allowed in downstream prompts"
    - "Single-worker invariant preserved (WEB_CONCURRENCY=1) until L4D-07-IOT"
supersedes:
  - H-L4D-00G-DOCS-v1
known_risks:
  - "In-memory session registry requires WEB_CONCURRENCY=1 until distributed Redis storage is added (L4D-07-IOT)"
  - "Interactive mouse/key input injection is rejected if screen is locked or session unavailable"
consumers:
  - L4D-02-IOT
next_prompt_id: L4D-02-IOT
```
<!-- HANDOFF:H-L4D-01C-DOCS-v1:END -->

<!-- HANDOFF:H-L4D-02-IOT-v1:BEGIN -->
```yaml
handoff_id: H-L4D-02-IOT-v1
status: ACCEPTED
contract_kinds:
  - API
  - EVENT
  - DEPLOYMENT
producer_prompt_id: L4D-02-IOT
producer_scope_project: iot-rpc-rest-app
producer_report_path: docs/l4desk/handoffs/L4D-02-IOT-report.md
producer_branch: l4desk/l4d-02-iot
producer_commit: a5524d356dda343eca96010d16535d9f37ff4ece
accepted_at_utc: 2026-09-17T23:30:00Z
contract_version: 1.0.0
schema_revision: 2026-09-17-v1
artifact_version: 1.0.0
artifact_paths:
  - docs/l4desk/contracts/iot_event_feed_contract_v1.json
  - docs/l4desk/contracts/schemas/iot_event_feed_openapi.json
  - docs/l4desk/contracts/schemas/remote_session_event.schema.json
  - docs/l4desk/contracts/schemas/remote_session.schema.json
  - docs/l4desk/fixtures/iot_event_feed_examples_v1.json
artifact_sha256:
  - 7acd49cb4d761a074e6e41f04380bef5db78d465fa8f6417bdf1fb16167e46c3
  - 07b0b3e4e54b96e08ffc716b00f9e1a4dabe0f0ba90ca09708485cf068ccba56
  - 230a22727a493b2980ba85cb2735e50d5ac42ac9b110cf3a6f3ba03ea0ebb12b
  - 1de26a6fc47ebbe1d97d2f93108c3760ebf4a742908825c7d73e5a905da18f36
  - 1fafb1d27010917f43f5d36502cbfaa1decd5cce36c80a6dc397f4180556df2b
compatibility:
  backward_compatible_with:
    - 0.2.1
    - 1.7.7
  breaking_changes: false
  notes: Durable session facts and monotonic cursor event feed added via additive internal REST API (/api/internal/v1/remote-session-events and /api/internal/v1/remote-sessions). Agent MQTT protocol and existing broker topologies completely untouched and binary backward-compatible. Commercial/financial fields strictly excluded.
deployment_status: DEPLOYED
deployed_environment: production
feature_flags:
  remote_session_events_feed: enabled
  durable_session_facts: enabled
contract_payload:
  identifiers:
    cursor_type: "int64 (BIGSERIAL monotonic, strictly positive)"
    event_id_pattern: "^evt_[a-z0-9_]+$"
    session_id_pattern: "^sess-(console|video)-[a-z0-9-]+$"
    operation_id_pattern: "^[0-9a-fA-F-]{36}$"
    sn_pattern: "^[0-9A-Za-z_-]{6,32}$"
  endpoints:
    - method: GET
      path: "/api/internal/v1/remote-session-events"
      params: ["after", "limit", "tenant_id", "sn", "session_id", "event_type"]
    - method: GET
      path: "/api/internal/v1/remote-session-events/reconciliation"
      params: ["tenant_id", "from_cursor", "to_cursor", "from_time", "to_time"]
    - method: POST
      path: "/api/internal/v1/remote-sessions"
    - method: GET
      path: "/api/internal/v1/remote-sessions/{session_id}"
    - method: POST
      path: "/api/internal/v1/remote-sessions/{session_id}/stop"
  events:
    - "device_online"
    - "remote_session_start_requested"
    - "remote_session_active"
    - "remote_session_stop_requested"
    - "remote_session_closed"
    - "remote_session_failed"
    - "console_command_started"
    - "console_command_completed"
    - "console_command_timed_out"
  errors:
    - code: 400
      name: "BAD_REQUEST"
      reasons: ["negative_cursor", "limit_out_of_bounds", "commercial_field_detected"]
    - code: 403
      name: "FORBIDDEN"
      reasons: ["missing_or_invalid_internal_service_key"]
    - code: 404
      name: "NOT_FOUND"
      reasons: ["remote_session_not_found"]
  cursor_rules:
    - "Monotonically increasing sequence; no holes on successful commits"
    - "Query parameter 'after' returns items where cursor > after"
    - "Result ordered strictly by cursor ASC"
    - "Consumers resume from next_cursor returned in feed response"
    - "Duplicate event deliveries by event_id or operation_id are deduplicated without cursor progression"
supersedes:
  - H-L4D-01C-DOCS-v1
known_risks:
  - "Consumer must store last processed cursor in durable storage to ensure fault-tolerant resume after crash"
  - "Polling frequency should be configured based on SLA; typical interval 1-5 seconds"
consumers:
  - L4D-03-MB
next_prompt_id: L4D-03-MB
```
<!-- HANDOFF:H-L4D-02-IOT-v1:END -->

<!-- HANDOFF:H-L4D-03-MB-v1:BEGIN -->
```yaml
handoff_id: H-L4D-03-MB-v1
status: ACCEPTED
contract_kinds:
  - REPORT
  - DEPLOYMENT
producer_prompt_id: L4D-03-MB
producer_scope_project: MenuBuilder
producer_report_path: MenuBuilder/docs/l4desk/handoffs/L4D-03-MB-report.md
producer_branch: l4desk/l4d-03-mb
producer_commit: 4da76eca24bab856bdad764df6e6a1dc9de44f1c
accepted_at_utc: 2026-09-17T22:20:00Z
contract_version: 1.0.0
schema_revision: 2026-09-17-v1
artifact_version: 1.0.0
artifact_paths:
  - MenuBuilder/backend/tests/fixtures/iot_event_feed_examples_v1.json
  - MenuBuilder/backend/tests/test_iot_event_feed_consumer.py
artifact_sha256:
  - 1fafb1d27010917f43f5d36502cbfaa1decd5cce36c80a6dc397f4180556df2b
  - 6664cc17db932fd4c84566c197cd8182a7521bb73589256a78fd3fa530ca9589
compatibility:
  backward_compatible_with:
    - 0.1.0
    - 0.2.0
  breaking_changes: false
  notes: Versioned IoT event feed consumer v1 connected strictly in MenuBuilder scope. Zero financial mutations or alternative session state; technical projections stored in idempotent inbox. Monotonic cursor checkpointing with lag observability and quarantine for contract violations. Dark consumer deployed with iot_consumer_enabled=false and shadow mode active.
deployment_status: DEPLOYED
deployed_environment: production
feature_flags:
  iot_consumer_enabled: false
  iot_consumer_shadow_mode: true
contract_payload:
  identifiers:
    consumer_id: "menubuilder_iot_event_consumer"
    cursor_type: "int64 (BIGSERIAL monotonic, strictly positive)"
    event_id_pattern: "^evt_[a-z0-9_]+$"
    session_id_pattern: "^sess-(console|video)-[a-z0-9-]+$"
  models:
    checkpoint_model: "IotConsumerCheckpoint (table: iot_consumer_checkpoints, last_cursor: BigInteger)"
    inbox_model: "IotEventInbox (table: iot_event_inbox, event_id: primary key)"
    quarantine_model: "IotEventQuarantine (table: iot_event_quarantine, quarantine_id: primary key, error_code: String)"
  endpoints:
    - method: GET
      path: "/api/internal/v1/iot-consumer/status"
      auth: "Bearer superuser or X-Internal-Service-Key"
    - method: POST
      path: "/api/internal/v1/iot-consumer/poll"
      auth: "Bearer superuser or X-Internal-Service-Key"
  invariants:
    - "Strict scope isolation: MenuBuilder does not mutate financial ledger, balances, or license entitlements"
    - "Dark consumer defaults: iot_consumer_enabled=false, iot_consumer_shadow_mode=true"
    - "Monotonic cursor tracking: checkpoint cursor advances only upon contiguous, error-free event consumption"
    - "Idempotent inbox: duplicate events suppressed by event_id without cursor regression"
    - "Strict quarantine: contract-violating payloads or out-of-order anomalies quarantined without blocking valid stream"
    - "Zero alternative flows: remote session telemetry feeds solely into inbox/projection tables"
supersedes:
  - H-L4D-00E-MB-v1
known_risks:
  - "Consumer relies on polling /api/internal/v1/remote-session-events; real-time latency bounded by poll_interval_seconds (default 5.0s)"
  - "Dark consumer is disabled by default (iot_consumer_enabled=false) and in shadow mode (iot_consumer_shadow_mode=true) until L4D-04C-MB activation"
  - "Storage schema migrations in MenuBuilder use idempotent DDL on startup; central Alembic migrations remain in ProcessingBackend"
consumers:
  - L4D-04A-SHARED
next_prompt_id: L4D-04A-SHARED
```
<!-- HANDOFF:H-L4D-03-MB-v1:END -->

<!-- HANDOFF:H-L4D-04A-SHARED-v1:BEGIN -->
```yaml
handoff_id: H-L4D-04A-SHARED-v1
status: ACCEPTED
contract_kinds:
  - SCHEMA
producer_prompt_id: L4D-04A-SHARED
producer_scope_project: shared/etranprocessing_db
producer_report_path: shared/docs/l4desk/handoffs/L4D-04A-SHARED-report.md
producer_branch: l4desk/l4d-04a-shared
producer_commit: 537a1e493c83d1fa8e8cb765228be8d1b24a1d62
accepted_at_utc: 2026-09-18T00:45:41Z
contract_version: 1.0.0
schema_revision: L4D-04A-v1
artifact_version: 0.1.1
artifact_paths:
  - shared/docs/l4desk/schema-v1.json
  - shared/docs/l4desk/schema-v1.md
  - shared/docs/l4desk/package-source-v011.json
artifact_sha256:
  - 52f481dd3d9985c54b5388a1d9e63062a8fdbe626870b58a83b3461c3e08e49f
  - d80626d6f84bab0e44d2236a172b3ffa385c7779bccd26b42c2947b071f77935
  - 364efa7b369cdcb8da12025b377518834b6013fd693a28f321a81dcbe18a68c6
compatibility:
  backward_compatible_with:
    - 0.1.0
  breaking_changes: false
  notes: "23 opt-in declarative models; 31 legacy tables/root exports unchanged. Existing IoT DDL/client defaults preserved. Replace MenuBuilder-local IoT declarations before opt-in import; update consumer lockfiles. No migration or policy activation. Source package published through Git by explicit user approval."
deployment_status: PUBLISHED
deployed_environment: artifact-registry
feature_flags: {}
contract_payload:
  package_name: etranprocessing-db
  package_version: 0.1.1
  delivery: git-source
  source_repository: https://github.com/OlegLebedevRU/etranprocessing.git
  source_root: shared
  package_source_sha256: 364efa7b369cdcb8da12025b377518834b6013fd693a28f321a81dcbe18a68c6
  schema_import: etranprocessing_db.l4desk
  identifiers:
    tenant_user_terminal: "Integer; tenant=orgs.org_id, user=users.id; durable terminal identity retains original terminals.id"
    external_event_session_operation_correlation_terminal: "Opaque String(128), not UUID-only"
    cursor: "BigInteger; inbox primary key event_id; quarantine primary key id"
    archive: "String(128) batch id, composite manifest PK (id, source_project)"
  operations_events: "Schema only; no new HTTP/MQTT contract or runtime behavior"
  errors: "Named PK/FK/UNIQUE/CHECK violations; exact names and PostgreSQL DDL in schema-v1.json"
  invariants:
    - "Financial table/constraint/index names start fin_; integer kopecks; timezone-aware timestamps"
    - "Unique original terminal/date usage, terminal/cycle charge, provider payment, tenant/cycle/type notification"
    - "One reserved/start_requested/active/stop_requested console-or-video reservation per terminal"
    - "Calculated = posted + discarded; 0 <= discarded < 100; posted/payment/ledger amounts are whole rubles"
    - "Ledger metadata supports balanced transactions; cross-row entry totals and append-only require consumer/DB guards"
    - "Financial source identifiers/hashes have no mandatory FK to purgeable technical events"
    - "Source-only additive rollout; no destructive changes, migration, feature activation or main merge"
  verification:
    shared_tests: "65 passed"
    lint_format_type_build: "passed; pyright 0 errors/0 warnings; wheel/sdist and isolated wheel import verified"
    post_publish_smoke: "20 Git blob SHA-256 checks and 2 package tests passed; origin ref matched producer commit"
supersedes: []
known_risks:
  - "04B must reconcile live IoT DDL and run PostgreSQL Alembic tests; this provider did not access the live DB"
  - "04C must replace duplicate local IoT declarations before opt-in import; both consumers must update their lockfiles"
  - "Cross-row ledger balance/account ownership/append-only enforcement and archive retention verification are not implemented in this thin package"
  - "Local wheel/sdist are verification artifacts only; required published artifact is Git source at producer_commit"
consumers:
  - L4D-04B-PB
next_prompt_id: L4D-04B-PB
```
<!-- HANDOFF:H-L4D-04A-SHARED-v1:END -->

<!-- HANDOFF:H-L4D-04B-PB-v1:BEGIN -->
```yaml
handoff_id: H-L4D-04B-PB-v1
status: ACCEPTED
contract_kinds:
  - SCHEMA
  - DEPLOYMENT
producer_prompt_id: L4D-04B-PB
producer_scope_project: ProcessingBackend
producer_report_path: ProcessingBackend/docs/l4desk/handoffs/L4D-04B-PB-report.md
producer_branch: l4desk/l4d-04b-pb
producer_commit: c889ec5f9b0366d3a61e908f82dcd2e8f4c0b367
accepted_at_utc: 2026-09-18T08:35:00Z
contract_version: 1.0.0
schema_revision: "027"
artifact_version: 0.1.1
artifact_paths:
  - ProcessingBackend/backend/alembic/versions/027_add_l4desk_and_fin_ledger.py
  - ProcessingBackend/docs/l4desk/schema-027.sql
  - ProcessingBackend/backend/tests/test_schema_migration.py
artifact_sha256:
  - 5993027230ffc6121e4bd76988cbbf21d2a2602f64bdcfd39aad72f5efe6177d
  - dfbf10b1249da4d9486309701722cc22b093dc335a1d73949081fc7a6a7ddbd0
  - dbbc3bf5f053eefbaea8bbcc71775796a5beba410a8277271e16f39ddc43557e
compatibility:
  backward_compatible_with:
    - "026"
  breaking_changes: false
  notes: "Non-destructive expand migration 027 deployed to production PostgreSQL. Added 23 tables (14 fin_*, 3 iot_*, 6 l4desk_*). Existing 31 core tables and application endpoints untouched. Clean transactional rollback 027->026 verified. menubuilder-backend restarted and healthy."
deployment_status: DEPLOYED
deployed_environment: production
feature_flags: {}
contract_payload:
  alembic_head: "027"
  alembic_down_revision: "026"
  package_name: etranprocessing-db
  package_version: 0.1.1
  input_schema_sha256: 52f481dd3d9985c54b5388a1d9e63062a8fdbe626870b58a83b3461c3e08e49f
  input_package_source_sha256: 364efa7b369cdcb8da12025b377518834b6013fd693a28f321a81dcbe18a68c6
  ddl_snapshot_sha256: dfbf10b1249da4d9486309701722cc22b093dc335a1d73949081fc7a6a7ddbd0
  deployed_tables_count: 23
  deployed_host: 87.242.100.34
  mcp_ops_readiness: UNAVAILABLE (fallback to SSH)
  verification:
    pytest_tests: "113 passed"
    linters: "ruff check passed, ruff format passed, pyright 0 errors/0 warnings"
    live_db_check: "alembic current is 027 (head); all 23 tables confirmed present in public schema"
    rollback_readiness: "alembic downgrade --sql 027:026 verified and transactional"
    service_health: "menubuilder-backend restarted and Up, processing-backend Up"
supersedes: []
known_risks:
  - "L4D-04C-MB must reconcile local IoT model classes with shared package models to avoid duplicate Base declarations"
  - "Financial triggers / balanced transaction invariants must be enforced in business logic prior to enabling financial writes"
consumers:
  - L4D-04C-MB
next_prompt_id: L4D-04C-MB
```
<!-- HANDOFF:H-L4D-04B-PB-v1:END -->

<!-- HANDOFF:H-L4D-04C-MB-v1:BEGIN -->
```yaml
handoff_id: H-L4D-04C-MB-v1
status: ACCEPTED
contract_kinds:
  - SCHEMA
  - DEPLOYMENT
producer_prompt_id: L4D-04C-MB
producer_scope_project: MenuBuilder
producer_report_path: MenuBuilder/docs/l4desk/handoffs/L4D-04C-MB-report.md
producer_branch: l4desk/l4d-04c-mb
producer_commit: a726ec94022517697a59fee6644f598dc3b978d8
accepted_at_utc: 2026-09-18T12:40:00Z
contract_version: 1.0.0
schema_revision: "027"
artifact_version: 0.1.1
artifact_paths:
  - MenuBuilder/backend/app/schema_compatibility.py
  - MenuBuilder/backend/app/models_l4desk.py
  - MenuBuilder/backend/app/repositories/l4desk_repository.py
  - MenuBuilder/backend/tests/test_schema_compatibility.py
artifact_sha256:
  - 670e8d1e780e503625865a41d61b004b28b14adc93be4e5710aadb73dfa8630e
  - 7f708171cec710524a3f042701bec31524d7cd2ebb07f0dbf501aa4b019d5131
  - 316adf73ab2765377b64d55f26cadb2b41b541b260b1e0c63f55be817ebeeb89
  - 055e43be0acd36c34b3e932dcfc30b67d4afe51b66e6df3b82cbcdacbd9e978f
consumed_contracts:
  - handoff_id: H-L4D-04A-SHARED-v1
    contract_id: l4desk_shared_schema_v1
    contract_version: 1.0.0
    schema_revision: L4D-04A-v1
    producer: shared
    package_name: etranprocessing-db
    package_version: 0.1.1
    package_source_sha256: 364efa7b369cdcb8da12025b377518834b6013fd693a28f321a81dcbe18a68c6
  - handoff_id: H-L4D-04B-PB-v1
    contract_id: alembic_migration_027
    contract_version: 1.0.0
    schema_revision: "027"
    producer: ProcessingBackend
    alembic_head: "027"
    deployed_host: 87.242.100.34
compatibility:
  backward_compatible_with:
    - 0.1.0
  breaking_changes: false
  notes: "MenuBuilder connected to published etranprocessing-db==0.1.1 and deployed expand schema 027 in dark mode. Replaced duplicate local IoT model declarations with shared package re-exports. Added strict startup schema compatibility verification (reads alembic_version and 23 required tables; zero automatic DDL). Added dark mode feature flags (registration, billing, ui all disabled by default). Verified backward compatibility and rolling deploy resilience."
deployment_status: DEPLOYED
deployed_environment: production
feature_flags:
  l4desk_registration_enabled: false
  l4desk_billing_enabled: false
  l4desk_ui_enabled: false
  schema_compatibility_check_enabled: true
  required_alembic_revision: "027"
contract_payload:
  package_name: etranprocessing-db
  package_version: 0.1.1
  package_source_sha256: 364efa7b369cdcb8da12025b377518834b6013fd693a28f321a81dcbe18a68c6
  alembic_head: "027"
  schema_revision: "027"
  deployed_host: 87.242.100.34
  deployed_service: menubuilder-backend
  deployed_image: user1-menubuilder-backend:latest
  tables_checked_count: 23
  invariants:
    - "Strict scope: MenuBuilder performs zero automatic DDL at startup (auto-DDL disabled in storage and lifespan)"
    - "Startup guard: verify_schema_compatibility verifies alembic_version == '027' and presence of all 23 L4Desk tables; aborts startup on mismatch"
    - "Dark mode: L4Desk features disabled by default via config flags (l4desk_registration_enabled=false, l4desk_billing_enabled=false, l4desk_ui_enabled=false)"
    - "Shared package integration: etranprocessing-db==0.1.1 consumed via etranprocessing_db.l4desk; duplicate local models reconciled"
    - "Rolling deploy resilience: models support omitted optional columns via null defaults and load_only queries"
supersedes: []
known_risks:
  - "L4Desk business routes (registration, billing, UI) remain dark and inaccessible until L4D-05-MB and subsequent prompts"
  - "Startup compatibility check requires PostgreSQL database connection; aborts startup if database schema revision is not 027"
consumers:
  - L4D-05-MB
next_prompt_id: L4D-05-MB
```
<!-- HANDOFF:H-L4D-04C-MB-v1:END -->

<!-- HANDOFF:H-L4D-05-MB-v1:BEGIN -->
```yaml
handoff_id: H-L4D-05-MB-v1
status: ACCEPTED
contract_kinds:
  - API
  - DEPLOYMENT
producer_prompt_id: L4D-05-MB
producer_scope_project: MenuBuilder
producer_report_path: MenuBuilder/docs/l4desk/handoffs/L4D-05-MB-report.md
producer_branch: l4desk/l4d-05-mb
producer_commit: 8902059485471f64fa4bf5f4605c633bcfeaa7b5
accepted_at_utc: 2026-09-18T14:15:00Z
contract_version: 1.0.0
schema_revision: "027"
artifact_version: 0.1.1
artifact_paths:
  - MenuBuilder/backend/app/routers/registration.py
  - MenuBuilder/backend/app/services/registration_service.py
  - MenuBuilder/backend/app/repositories/l4desk_repository.py
  - MenuBuilder/backend/tests/test_l4desk_registration.py
  - MenuBuilder/frontend/src/routes/register.tsx
  - MenuBuilder/frontend/src/routes/register-confirm.tsx
artifact_sha256:
  - 8c091b91b37ed0df5835d6d7c4267d178541f2c83fdff23c65338cb3668209ef
  - 986ca0b5acf6fae6f774cbf8bfc5119c9c8ad5c8bc2fe75ddb9b54799927e40e
  - 4cc8b00440f3217ebb592e7dacaa5c37c84de2fa607f08f655cd141fbba3c08d
  - 0150737921c0d5ffeb3b917d64b703ec96365742e7f40372df59741685a54693
  - bfd8a5419ff8714744fed4d507691fdea7fece9b22ec5c5e25f34273e3388519
  - ff684f883240171cc02919da75888ac4fc302dda9c468485c4529acdb3e57786
consumed_contracts:
  - handoff_id: H-L4D-04C-MB-v1
    contract_id: menubuilder_expand_schema_v1
    contract_version: 1.0.0
    schema_revision: "027"
    producer: MenuBuilder
    alembic_head: "027"
    deployed_host: 87.242.100.34
compatibility:
  backward_compatible_with:
    - 0.1.0
    - 0.1.1
  breaking_changes: false
  notes: "L4Desk public self-registration and email confirmation endpoints implemented in MenuBuilder under dark mode feature flag (l4desk_registration_enabled). Anti-enumeration responses prevent email discovery. Verification tokens are one-time use and hashed with SHA-256 in database. Atomic provisioning on confirmation creates Org, OrgBillingSettings (free package), OrgStatus, L4DeskTenantProfile, User with role_id=5 (l4desk_owner), L4DeskMembership (is_owner=True), and immutable audit event. Replay confirmation is idempotent. Rate limiting protects IP and resend cooldown. Malicious return URLs are sanitized against open redirect vulnerabilities. Existing auth and tenant sessions remain backward-compatible."
deployment_status: DEPLOYED
deployed_environment: production
feature_flags:
  l4desk_registration_enabled: false
  l4desk_billing_enabled: false
  l4desk_ui_enabled: false
  schema_compatibility_check_enabled: true
  required_alembic_revision: "027"
contract_payload:
  endpoints:
    - method: POST
      path: /api/auth/register
      description: "Public self-registration endpoint for tenant owners (anti-enumeration generic 200 response)"
    - method: POST
      path: /api/auth/register/confirm
      description: "One-time token verification and atomic tenant + user role 5 provisioning"
    - method: POST
      path: /api/auth/register/resend
      description: "Resend verification email with cooldown rate limits"
    - method: GET
      path: /api/auth/register/status
      description: "Public feature flag status check"
  roles:
    role_id_5:
      name: l4desk_owner
      permissions: ALL_PERMISSIONS
      is_tenant_admin: true
  invariants:
    - "Dark mode: endpoints guarded by l4desk_registration_enabled flag (returns 403 when disabled)"
    - "Security: token in database is hashed with SHA-256 (plaintext never persisted)"
    - "Anti-enumeration: registration and resend return generic message regardless of email existence"
    - "Atomicity: single PostgreSQL transaction creates Org, OrgBillingSettings, OrgStatus, TenantProfile, User (role=5), Membership, and Audit"
    - "Idempotency: replaying confirmation token returns already_confirmed without duplicate entities"
    - "Open redirect safety: return_url validated against whitelist and restricted to safe relative paths"
supersedes: []
known_risks:
  - "L4Desk registration remains disabled in production until explicitly activated via configuration flag"
  - "Billing payment processing and terminal provisioning are deferred to subsequent prompts (L4D-06A-PB / L4D-06B-MB)"
consumers:
  - L4D-06A-PB
next_prompt_id: L4D-06A-PB
```
<!-- HANDOFF:H-L4D-05-MB-v1:END -->

<!-- HANDOFF:H-L4D-06A-PB-v1:BEGIN -->
```yaml
handoff_id: H-L4D-06A-PB-v1
status: ACCEPTED
contract_kinds:
  - API
  - DEPLOYMENT
producer_prompt_id: L4D-06A-PB
producer_scope_project: ProcessingBackend
producer_report_path: ProcessingBackend/docs/l4desk/handoffs/L4D-06A-PB-report.md
producer_branch: l4desk/l4d-06a-pb
producer_commit: 083138f223b723098e9a188803e3fc802e8a6011
accepted_at_utc: 2026-09-18T15:45:00Z
contract_version: 1.0.0
artifact_paths:
  - ProcessingBackend/backend/app/routers/certificates.py
  - ProcessingBackend/backend/app/schemas/certificates.py
  - ProcessingBackend/backend/app/services/cert_billing.py
  - ProcessingBackend/backend/app/dependencies.py
  - ProcessingBackend/backend/app/config.py
  - ProcessingBackend/backend/app/models.py
  - ProcessingBackend/backend/tests/test_certificate_pin_contract.py
artifact_sha256:
  - 0a0e925b1dfad9c6b96f5063cc33b5bea822cd558062681d9b011f0fe02ed93a
  - 5e5327e51703cabb08c696c72477fed5abb75093782bd1514c43649b8681b6f0
  - 50ccee8cb7311e2a55d47ae127ffdcb41e48b2f121aeb1c6a2c8606026770ce5
  - 9b716bf58d274ef478f220ee398c13560d02919092a340fce008178ca955018c
  - 8873a6ecff0b01e045b6e3f66f39e866c0cbb8476aa2ecf6f97ca4b60b30c0ba
  - 5d6b0c36127443bc2d02f90341ad494a7fd86c021f60ef7ff5d81ff3574f403a
  - 4eaa876994b3be8037763685188ef0ade2b1a36a9a1a9c947de0300bf8dae37e
compatibility:
  backward_compatible_with:
    - H-L4D-00C-PB-v1
    - H-L4D-00G-DOCS-v1
  breaking_changes: false
  notes: "Additive service-to-service PIN issuance and query endpoints (/api/certificates/pins/issue, /api/certificates/pins/by-operation/{operation_id}). Existing terminal endpoints (function=check, function=setup) preserved with full backward compatibility and reinforced with row-level locking, CSR signature checking, CSR mismatch rejection, and safe retry caching."
deployment_status: DEPLOYED
deployed_environment: production
feature_flags: {}
contract_payload:
  endpoints:
    - path: /api/certificates/pins/issue
      method: POST
      auth: require_service_auth
      request_schema: IssueCertificatePinRequest
      response_schema: IssueCertificatePinResponse
      status_codes:
        201: Created (new PIN issued)
        200: OK (idempotent replay of existing operation_id)
        400: Bad Request (SERIAL_NUMBER_MISMATCH)
        401: Unauthorized (SERVICE_AUTH_FAILED)
        403: Forbidden (TENANT_OWNERSHIP_MISMATCH)
        404: Not Found (TERMINAL_NOT_FOUND)
        409: Conflict (OPERATION_ID_CONFLICT)
    - path: /api/certificates/pins/by-operation/{operation_id}
      method: GET
      auth: require_service_auth
      response_schema: IssueCertificatePinResponse
      status_codes:
        200: OK
        401: Unauthorized (SERVICE_AUTH_FAILED)
        404: Not Found (OPERATION_NOT_FOUND)
  identifiers:
    tenant_id: int
    terminal_id: int
    sn: str
    operation_id: str
    correlation_id: str | None
  idempotency_semantics:
    replayed_flag: boolean
    conflict_on_parameter_change: true
    duplicate_pin_issuance: prohibited
    consumed_pin_visibility: "pin=None, pin_masked preserved, status=consumed"
    expired_pin_visibility: "pin=None, pin_masked preserved, status=expired"
  deployed_host: 87.242.100.34
  mcp_ops_readiness: UNAVAILABLE (fallback to SSH)
  verification:
    pytest_tests: "130 passed"
    linters: "ruff check passed, ruff format passed, pyright 0 errors/0 warnings"
    live_smoke_probes: "health 200, check code=2, issue 404/403 with error_code"
supersedes: []
known_risks: []
consumers:
  - L4D-06B-IOT
  - L4D-06C-MB
next_prompt_id: L4D-06B-IOT
```
<!-- HANDOFF:H-L4D-06A-PB-v1:END -->

## 8. Регистрация корректирующего шага L4D-06B-IOT-FIX-01

Контроллер добавил эту отдельную запись по явному подтверждению пользователя на регистрацию FIX, адресный допуск и отдельный candidate с digest отчёта без самоссылки. Основание — BLOCKED_CONTRACT исполнителя: FIX отсутствовал в реестре и consumers обоих входных handoff. Запись дополняет только проверку адресации из §1 этого журнала по §8 PROMPT-STANDARD.md (1.1.0); прежние принятые блоки, их payload, версии и consumers не изменены.

Это не приёмка H-L4D-06B-IOT-v1 или H-L4D-06B-IOT-FIX-01-v1, не новый provider-релиз и не доказательство тестов/deploy. Последний принятый основной шаг остаётся H-L4D-06A-PB-v1. До запуска corrective требуется публикация пакета документов по README и полный gate исходных артефактов; до повторной приёмки исходного 06B переход к L4D-06C-MB закрыт.

<!-- CORRECTIVE_REGISTRATION:R-L4D-06B-IOT-FIX-01-v1:BEGIN -->
```yaml
registration_id: R-L4D-06B-IOT-FIX-01-v1
status: AUTHORIZED
authorized_by: Cascade Controller
authorization_basis: explicit_user_confirmation_in_current_session
registered_at_utc: 2026-09-18T19:17:53Z
prompt_id: L4D-06B-IOT-FIX-01
prompt_path: l4desk-service/docs/prompts/etran_dev-l4d-06b-iot-fix-01.md
scope_project: iot-rpc-rest-app
scope_root: D:\work\iot.leo4.ru\iot-rpc-rest-app
blocked_prompt_id: L4D-06B-IOT
authorized_inputs:
  - handoff_id: H-L4D-06A-PB-v1
    contract_version: 1.0.0
    producer_commit: 083138f223b723098e9a188803e3fc802e8a6011
  - handoff_id: H-L4D-02-IOT-v1
    contract_version: 1.0.0
    producer_commit: a5524d356dda343eca96010d16535d9f37ff4ece
sequence_gate_handoff_id: H-L4D-06A-PB-v1
output_handoff_id: H-L4D-06B-IOT-FIX-01-v1
next_prompt_id: L4D-06B-IOT
report_path: docs/l4desk/handoffs/L4D-06B-IOT-FIX-01-report.md
candidate_format: DETACHED_V1
detached_candidate_approved: true
candidate_path: docs/l4desk/handoffs/L4D-06B-IOT-FIX-01-candidate.md
publication_required_before_execution: true
grant_scope: consumer_addressing_only
runtime_acceptance: NOT_GRANTED
blocked_next_prompt_id: L4D-06C-MB
original_journal_bytes: 70039
original_journal_sha256: 1205e0e16e14ee29ba1cd68f9175e128c7a89a50aa69db87afcf4758a0f525c0
```
<!-- CORRECTIVE_REGISTRATION:R-L4D-06B-IOT-FIX-01-v1:END -->

## 9. Самостоятельный provider-пакет и допуск FIX v2

Операция контроллера по явному поручению пользователя подготовить всё необходимое для
L4D-06B-IOT-FIX-01 и отдельному подтверждению публикации нового документационного пакета.
По §10 PROMPT-STANDARD 1.2.0 выполнен документационный шаг L4D-06A-PB-CONTRACT-01.
Ниже оформлены его результат, точная привязка Git-байтов 02-IOT и замена регистрации FIX.
Это адресное дополнение правил чтения/digest §1 журнала, не правка прежних handoff.
H-L4D-06A-PB-v1 остаётся только sequence gate для FIX; исходный 06B не принят,
переход к L4D-06C-MB закрыт. Runtime provider не изменён и повторно не принимался.

<!-- HANDOFF:H-L4D-06A-PB-CONTRACT-01-v1:BEGIN -->
```yaml
handoff_id: H-L4D-06A-PB-CONTRACT-01-v1
status: ACCEPTED
contract_kinds: [API]
producer_prompt_id: L4D-06A-PB-CONTRACT-01
producer_scope_project: l4desk-service
producer_report_path: l4desk-service/docs/prompts/contracts/certificate-pin-v1/verification.md
producer_branch: l4desk/l4d-06a-pb
producer_commit: 1971e51f1e7764a31d586174e42513160f8598eb
accepted_at_utc: 2026-09-18T21:36:36Z
contract_version: 1.0.0
schema_revision: 2026-09-18-pin-docs-v1
artifact_version: 1.0.0
artifact_paths:
  - l4desk-service/docs/prompts/contracts/certificate-pin-v1/contract.md
  - l4desk-service/docs/prompts/contracts/certificate-pin-v1/schemas.json
  - l4desk-service/docs/prompts/contracts/certificate-pin-v1/examples.json
  - l4desk-service/docs/prompts/contracts/certificate-pin-v1/verification.md
artifact_sha256:
  - 1c2787fc2c34343d9b46658bd304cb2110bf554019667712c5596eae8ce6c7f4
  - 563a00aabf4a539c92f6fccad36596dd63fea05bfc088ca1cf7ddbb8e16f26c0
  - 92a3beeb8323d4697e89ef3978d1d54de07202e5c87debec1adb53779cc48737
  - 59f24caaf5439b0b6134535fab2ff055740c9760db5c52ad68d50496255efa92
artifact_urls:
  - https://raw.githubusercontent.com/OlegLebedevRU/etranprocessing/1971e51f1e7764a31d586174e42513160f8598eb/l4desk-service/docs/prompts/contracts/certificate-pin-v1/contract.md
  - https://raw.githubusercontent.com/OlegLebedevRU/etranprocessing/1971e51f1e7764a31d586174e42513160f8598eb/l4desk-service/docs/prompts/contracts/certificate-pin-v1/schemas.json
  - https://raw.githubusercontent.com/OlegLebedevRU/etranprocessing/1971e51f1e7764a31d586174e42513160f8598eb/l4desk-service/docs/prompts/contracts/certificate-pin-v1/examples.json
  - https://raw.githubusercontent.com/OlegLebedevRU/etranprocessing/1971e51f1e7764a31d586174e42513160f8598eb/l4desk-service/docs/prompts/contracts/certificate-pin-v1/verification.md
compatibility:
  backward_compatible_with: [H-L4D-06A-PB-v1]
  breaking_changes: false
  notes: "Documentation export of unchanged PIN API; precise auth/replay/error semantics and limitations, no runtime guarantee added. Old source artifacts are provenance, not recursive inputs."
deployment_status: DOCS_PUBLISHED
deployed_environment: documentation
feature_flags: {}
contract_payload:
  verification_status: VERIFIED
  source_handoff_id: H-L4D-06A-PB-v1
  source_commit: 083138f223b723098e9a188803e3fc802e8a6011
  source_project: ProcessingBackend
  runtime_verification: NOT_REPEATED
  endpoints:
    - method: POST
      path: /api/certificates/pins/issue
      request_schema: schemas.json#/$defs/IssueRequest
      response_schema: schemas.json#/$defs/IssueResponse
    - method: GET
      path: /api/certificates/pins/by-operation/{operation_id}
      response_schema: schemas.json#/$defs/IssueResponse
  error_schemas: [schemas.json#/$defs/ErrorResponse, schemas.json#/$defs/ValidationErrorResponse]
  auth_and_semantics: contract.md
  examples: examples.json
  verification:
    schema_fixtures: 20
    additional_boundary_checks: 22
    provider_request_ast: MATCHED
    docs_publish_commit: 1971e51f1e7764a31d586174e42513160f8598eb
    remote_ref_verified_at_utc: 2026-09-18T21:09:50Z
  authorization_basis: explicit_user_request_and_confirmation_of_two_stage_docs_publication
supersedes: []
known_risks:
  - "Provider permits requests when both server credentials are empty; production configuration not verified by this export."
  - "Service credential is not tenant-scoped; GET requires consumer-side ownership enforcement."
  - "Concurrent first PIN issuance guarantee not established; no new provider runtime tests or deployment performed."
consumers: [L4D-06B-IOT-FIX-01]
next_prompt_id: L4D-06B-IOT-FIX-01
```
<!-- HANDOFF:H-L4D-06A-PB-CONTRACT-01-v1:END -->

<!-- ARTIFACT_BYTE_BINDING:B-L4D-02-IOT-GIT-v1:BEGIN -->
```yaml
binding_id: B-L4D-02-IOT-GIT-v1
status: VERIFIED
verified_at_utc: 2026-09-18T21:36:36Z
handoff_id: H-L4D-02-IOT-v1
contract_version: 1.0.0
producer_commit: a5524d356dda343eca96010d16535d9f37ff4ece
consumers: [L4D-06B-IOT-FIX-01]
reason: LF_CRLF_ONLY
byte_source: git_blob
evidence_report: l4desk-service/docs/prompts/contracts/certificate-pin-v1/verification.md
evidence_commit: 1971e51f1e7764a31d586174e42513160f8598eb
artifacts:
  - path: docs/l4desk/contracts/iot_event_feed_contract_v1.json
    historical_sha256: 7acd49cb4d761a074e6e41f04380bef5db78d465fa8f6417bdf1fb16167e46c3
    git_blob_sha256: 07be82d70e768ae0a44f24f6e5de6b948a039b746a798ce9c08179fbae810a77
  - path: docs/l4desk/contracts/schemas/iot_event_feed_openapi.json
    historical_sha256: 07b0b3e4e54b96e08ffc716b00f9e1a4dabe0f0ba90ca09708485cf068ccba56
    git_blob_sha256: 8196befa2b3e103ec27cfbd39f65cbd230de55de037cadfbb890b06792d4d324
  - path: docs/l4desk/contracts/schemas/remote_session_event.schema.json
    historical_sha256: 230a22727a493b2980ba85cb2735e50d5ac42ac9b110cf3a6f3ba03ea0ebb12b
    git_blob_sha256: 4d7393d0dcd1ae62f04e0ad488b6bab519d8d7e357f0cad569809743cb6270e9
  - path: docs/l4desk/contracts/schemas/remote_session.schema.json
    historical_sha256: 1de26a6fc47ebbe1d97d2f93108c3760ebf4a742908825c7d73e5a905da18f36
    git_blob_sha256: c05027474d31f993954451d388667370caadcaeee044997a7a5a97e066cbb1ad
  - path: docs/l4desk/fixtures/iot_event_feed_examples_v1.json
    historical_sha256: 1fafb1d27010917f43f5d36502cbfaa1decd5cce36c80a6dc397f4180556df2b
    git_blob_sha256: 41734c7b68850b083eefc07891183c91965c88d0a6589f15e265be0563006f61
runtime_acceptance: NOT_GRANTED
```
<!-- ARTIFACT_BYTE_BINDING:B-L4D-02-IOT-GIT-v1:END -->

<!-- CORRECTIVE_REGISTRATION_REVOCATION:R-L4D-06B-IOT-FIX-01-v1:BEGIN -->
```yaml
registration_id: R-L4D-06B-IOT-FIX-01-v1
status: REVOKED
revoked_at_utc: 2026-09-18T21:36:36Z
reason: "Replace source-only PIN input with published data-only contract and finite read grant; explicit IOT Git-byte binding. No runtime handoff revoked."
replacement_registration_id: R-L4D-06B-IOT-FIX-01-v2
```
<!-- CORRECTIVE_REGISTRATION_REVOCATION:R-L4D-06B-IOT-FIX-01-v1:END -->

<!-- CORRECTIVE_REGISTRATION:R-L4D-06B-IOT-FIX-01-v2:BEGIN -->
```yaml
registration_id: R-L4D-06B-IOT-FIX-01-v2
status: AUTHORIZED
authorized_by: Cascade Controller
authorization_basis: explicit_user_request_and_confirmation_of_two_stage_docs_publication
registered_at_utc: 2026-09-18T21:36:36Z
prompt_id: L4D-06B-IOT-FIX-01
prompt_path: l4desk-service/docs/prompts/etran_dev-l4d-06b-iot-fix-01.md
scope_project: iot-rpc-rest-app
scope_root: D:\work\iot.leo4.ru\iot-rpc-rest-app
blocked_prompt_id: L4D-06B-IOT
authorized_inputs:
  - handoff_id: H-L4D-06A-PB-CONTRACT-01-v1
    contract_version: 1.0.0
    producer_commit: 1971e51f1e7764a31d586174e42513160f8598eb
  - handoff_id: H-L4D-02-IOT-v1
    contract_version: 1.0.0
    producer_commit: a5524d356dda343eca96010d16535d9f37ff4ece
artifact_byte_binding_ids: [B-L4D-02-IOT-GIT-v1]
external_artifact_reads:
  - handoff_id: H-L4D-06A-PB-CONTRACT-01-v1
    artifact_commit: 1971e51f1e7764a31d586174e42513160f8598eb
    paths:
      - l4desk-service/docs/prompts/contracts/certificate-pin-v1/contract.md
      - l4desk-service/docs/prompts/contracts/certificate-pin-v1/schemas.json
      - l4desk-service/docs/prompts/contracts/certificate-pin-v1/examples.json
      - l4desk-service/docs/prompts/contracts/certificate-pin-v1/verification.md
sequence_gate_handoff_id: H-L4D-06A-PB-v1
output_handoff_id: H-L4D-06B-IOT-FIX-01-v1
next_prompt_id: L4D-06B-IOT
report_path: docs/l4desk/handoffs/L4D-06B-IOT-FIX-01-report.md
candidate_format: DETACHED_V1
detached_candidate_approved: true
candidate_path: docs/l4desk/handoffs/L4D-06B-IOT-FIX-01-candidate.md
publication_required_before_execution: true
grant_scope: consumer_addressing_and_finite_data_only_reads
runtime_acceptance: NOT_GRANTED
blocked_next_prompt_id: L4D-06C-MB
original_journal_bytes: 72781
original_journal_sha256: 329844b0b829bf1f0a4d8dbe7f47fd8b5048852e435b33d0e8b376bf4c198802
```
<!-- CORRECTIVE_REGISTRATION:R-L4D-06B-IOT-FIX-01-v2:END -->

## 10. Нормативное определение составных схем и допуск FIX v3

Операция контроллера по явному запросу пользователя устранить блокировку смежного агента
(BLOCKED_CONTRACT на этапе contract gate из-за внутренней ссылки `$ref: #/$defs/RemoteSessionType`
в артефакте `docs/l4desk/contracts/schemas/remote_session.schema.json` входного контракта
`H-L4D-02-IOT-v1`, producer_commit `a5524d356dda343eca96010d16535d9f37ff4ece`, привязка
`B-L4D-02-IOT-GIT-v1`).

Контроллер каскада нормативно устанавливает следующее обязательное правило интерпретации:
1. Артефакт `docs/l4desk/contracts/schemas/remote_session.schema.json` является составным
   каталогом моделей (multi-schema bundle). Корневой объект `RemoteSessionSchemas` служит
   пространством имён / контейнером определений (`definitions`).
2. Каждая подсхема под `#/definitions/<ModelName>` (`RemoteSessionCreate`, `RemoteSessionResponse`,
   `RemoteSessionStop`) нормативно признаётся самостоятельным, изолированным документом схемы
   соответствующей модели (autonomous standalone schema document).
3. Базой разрешения внутренних JSON Pointer / `$ref` фрагментов (`#`) внутри каждой подсхемы
   является корень соответствующей подсхемы `#/definitions/<ModelName>`, где расположен её
   локальный блок `$defs: {"RemoteSessionType": ...}`.
4. Ссылка `#/definitions/RemoteSessionCreate/properties/session_type/$ref: #/$defs/RemoteSessionType`
   признаётся нормативно корректной и полностью разрешимой в автономном контексте подсхемы
   `RemoteSessionCreate`. Отсутствие корневого `$defs` на уровне внешнего контейнера
   `RemoteSessionSchemas` не является дефектом контракта и не блокирует contract gate.
5. При проверке схем входного контракта валидация и разрешение ссылок должны проводиться для
   каждой подсхемы модели автономно (per-subschema evaluation), либо при интегральной проверке
   в качестве базового URI для подсхемы принимается её локальный контекст.

Ниже оформлены отзыв регистрации v2 и ввод регистрации v3 с фиксацией нормативного правила.
Исходный коммит и Git-байты `B-L4D-02-IOT-GIT-v1` остаются неизменными.

<!-- CORRECTIVE_REGISTRATION_REVOCATION:R-L4D-06B-IOT-FIX-01-v2:BEGIN -->
```yaml
registration_id: R-L4D-06B-IOT-FIX-01-v2
status: REVOKED
revoked_at_utc: 2026-09-19T01:25:00Z
reason: "Establish normative resolution rule for multi-schema bundle remote_session.schema.json (#/$defs/RemoteSessionType resolves in RemoteSessionCreate context); issue replacement registration v3."
replacement_registration_id: R-L4D-06B-IOT-FIX-01-v3
```
<!-- CORRECTIVE_REGISTRATION_REVOCATION:R-L4D-06B-IOT-FIX-01-v2:END -->

<!-- CORRECTIVE_REGISTRATION:R-L4D-06B-IOT-FIX-01-v3:BEGIN -->
```yaml
registration_id: R-L4D-06B-IOT-FIX-01-v3
status: AUTHORIZED
authorized_by: Cascade Controller
authorization_basis: explicit_user_request_and_normative_multi_schema_resolution_rule
registered_at_utc: 2026-09-19T01:25:00Z
prompt_id: L4D-06B-IOT-FIX-01
prompt_path: l4desk-service/docs/prompts/etran_dev-l4d-06b-iot-fix-01.md
scope_project: iot-rpc-rest-app
scope_root: D:\work\iot.leo4.ru\iot-rpc-rest-app
blocked_prompt_id: L4D-06B-IOT
authorized_inputs:
  - handoff_id: H-L4D-06A-PB-CONTRACT-01-v1
    contract_version: 1.0.0
    producer_commit: 1971e51f1e7764a31d586174e42513160f8598eb
  - handoff_id: H-L4D-02-IOT-v1
    contract_version: 1.0.0
    producer_commit: a5524d356dda343eca96010d16535d9f37ff4ece
artifact_byte_binding_ids: [B-L4D-02-IOT-GIT-v1]
external_artifact_reads:
  - handoff_id: H-L4D-06A-PB-CONTRACT-01-v1
    artifact_commit: 1971e51f1e7764a31d586174e42513160f8598eb
    paths:
      - l4desk-service/docs/prompts/contracts/certificate-pin-v1/contract.md
      - l4desk-service/docs/prompts/contracts/certificate-pin-v1/schemas.json
      - l4desk-service/docs/prompts/contracts/certificate-pin-v1/examples.json
      - l4desk-service/docs/prompts/contracts/certificate-pin-v1/verification.md
sequence_gate_handoff_id: H-L4D-06A-PB-v1
output_handoff_id: H-L4D-06B-IOT-FIX-01-v1
next_prompt_id: L4D-06B-IOT
report_path: docs/l4desk/handoffs/L4D-06B-IOT-FIX-01-report.md
candidate_format: DETACHED_V1
detached_candidate_approved: true
candidate_path: docs/l4desk/handoffs/L4D-06B-IOT-FIX-01-candidate.md
publication_required_before_execution: true
grant_scope: consumer_addressing_and_finite_data_only_reads
schema_interpretation_rules:
  - artifact_path: docs/l4desk/contracts/schemas/remote_session.schema.json
    rule: MULTI_SCHEMA_BUNDLE_AUTONOMOUS_SUBSCHEMAS
    definitions_scope: ["RemoteSessionCreate", "RemoteSessionResponse", "RemoteSessionStop"]
    ref_resolution_base: subschema_root
    notes: "Subschema #/definitions/RemoteSessionCreate resolves #/$defs/RemoteSessionType against its local $defs. Absence of root-level $defs in outer container does not violate contract gate."
runtime_acceptance: NOT_GRANTED
blocked_next_prompt_id: L4D-06C-MB
original_journal_bytes: 81789
original_journal_sha256: d6a9e33b3ee3316b2cde18ea25ed9371d74346af49ca1ccf45c754b349bbf293
```
<!-- CORRECTIVE_REGISTRATION:R-L4D-06B-IOT-FIX-01-v3:END -->

## 11. Принятие handoff H-L4D-06B-IOT-FIX-01-v1 (DETACHED_V1)

Фиксация контроллером каскада принятого контракта H-L4D-06B-IOT-FIX-01-v1 по результатам проверки отчёта `docs/l4desk/handoffs/L4D-06B-IOT-FIX-01-report.md` и отдельного кандидата `docs/l4desk/handoffs/L4D-06B-IOT-FIX-01-candidate.md` в формате DETACHED_V1 согласно §9 PROMPT-STANDARD 1.2.0 и нормативной регистрации R-L4D-06B-IOT-FIX-01-v3.

Все 6 оснований отказа исторического отчёта устранены и подтверждены воспроизводимым пакетом evidence:
1. Линтеры, форматирование и типизация проверены (black, ruff, pyright: 0 errors, 0 warnings).
2. Полный перечень изменённых файлов с коммитами и назначением зафиксирован.
3. Деплой и smoke-тесты на хосте 87.242.100.34 (app1) выполнены с реальными выводами и статусами HTTP (403, 404, 201, 200, 409).
4. Связь запущенного контейнера (Container ID 44add06a41e5, Image sha256:6974b172...) и побайтовое совпадение файлов с коммитом 4a0f9d4b218e96273eed605e9edd0f9ab3564b68 подтверждены.
5. Контрольные суммы SHA-256 артефактов и отчёта проверены и совпадают.
6. Входной sequence gate H-L4D-06A-PB-v1 и адресный допуск R-L4D-06B-IOT-FIX-01-v3 проверены.

<!-- HANDOFF:H-L4D-06B-IOT-FIX-01-v1:BEGIN -->
```yaml
handoff_id: H-L4D-06B-IOT-FIX-01-v1
status: ACCEPTED
contract_kinds:
  - API
  - EVENT
  - DEPLOYMENT
producer_prompt_id: L4D-06B-IOT-FIX-01
producer_scope_project: iot-rpc-rest-app
producer_report_path: docs/l4desk/handoffs/L4D-06B-IOT-FIX-01-report.md
producer_branch: l4desk/l4d-06b-iot-fix-01
producer_commit: 4a0f9d4b218e96273eed605e9edd0f9ab3564b68
report_commit: 2bca5e83ec9e4cf0c0774a3f4e1f7dcfb2bb0dfa
accepted_at_utc: 2026-09-19T03:30:00Z
contract_version: 1.0.0
schema_revision: 2026-09-18-v1
artifact_version: 1.0.0
candidate_format: DETACHED_V1
detached_candidate_approved: true
candidate_path: docs/l4desk/handoffs/L4D-06B-IOT-FIX-01-candidate.md
artifact_paths:
  - docs/l4desk/contracts/schemas/device_provisioning_openapi.json
  - docs/l4desk/contracts/schemas/device_provision_request.schema.json
  - docs/l4desk/contracts/schemas/device_provision_response.schema.json
  - docs/l4desk/fixtures/device_provisioning_examples_v1.json
  - docs/l4desk/handoffs/L4D-06B-IOT-FIX-01-report.md
artifact_sha256:
  - dccc1beefc97be7b4d89502193cb865e95f7fe3b4a3bbae8d528574c7d736a3d
  - 3cba891ebef0e1783bda8bdf02821e3eb6f9a12eba080b31a735fb2c5a667081
  - 0f2914e286fbe665401dc412acb4308aa91741c5f6d3a141acd301e1bf1cf3a8
  - 86dd26818fadf2d8c4ea07113a77410f19f3cbbf64fb6eccc098100bf893c2fb
  - 5759fc1ab00dacfe2f16585f4df2753a8b4d5a8bc197af22f5b99c0fcff62d80
compatibility:
  backward_compatible_with:
    - H-L4D-02-IOT-v1
    - H-L4D-06A-PB-v1
  breaking_changes: false
  notes: "Device provisioning REST API (/api/internal/v1/devices/provision) with durable idempotent tracking, single-event emission (device_provisioned) and certificate PIN consumption via X-Internal-Key."
deployment_status: DEPLOYED
deployed_environment: production
feature_flags: {}
contract_payload:
  corrects_candidate: H-L4D-06B-IOT-v1
  architecture_sections: [3, 4, 5, 6, 11, 12, 14, 16, 17]
  registration_id: R-L4D-06B-IOT-FIX-01-v3
  service_key_header: X-Internal-Key
  endpoints:
    provision: /api/internal/v1/devices/provision
    get_by_operation: /api/internal/v1/devices/provision/by-operation/{operation_id}
    get_by_sn: /api/internal/v1/devices/provision/by-sn/{sn}
    get_by_operation_legacy: /api/internal/v1/devices/provision/{operation_id}
  durable_event_type: device_provisioned
  alembic_revision: 0005_device_provisioning
  tests_passed: 384
  verification_status: VERIFIED_READY
supersedes: []
known_risks:
  - "WEB_CONCURRENCY=1 invariant required for in-memory state consistency on app1"
  - "Requires valid certificate PIN issued by ProcessingBackend prior to provisioning"
consumers:
  - L4D-06B-IOT
next_prompt_id: L4D-06B-IOT
```
<!-- HANDOFF:H-L4D-06B-IOT-FIX-01-v1:END -->

## 12. Повторная приёмка основного шага 18 L4D-06B-IOT (H-L4D-06B-IOT-v1)

Повторная приёмка контроллером каскада основного шага 18 `L4D-06B-IOT` (`iot-rpc-rest-app`) на основе исправленного и проверенного пакета `L4D-06B-IOT-FIX-01` (коммит реализации `4a0f9d4b218e96273eed605e9edd0f9ab3564b68`, ветка `l4desk/l4d-06b-iot-fix-01`).

Все 6 оснований первичного отказа успешно устранены и верифицированы:
1. Линтеры, форматирование и типизация (`black`, `ruff`, `pyright`: 0 ошибок/предупреждений).
2. Полный аудит изменённых файлов (исходных `bab8cfa`..`63f502f` и корректирующих `4a0f9d4`).
3. Доказательство фактического развёртывания миграции `0005_device_provisioning` и результатов 7 smoke-проверок (HTTP 403, 404, 201, 200, 409).
4. Подтверждение идентичности работающих байтов в контейнере `app1` (`44add06a41e5`, образ `sha256:6974b172...`) с коммитом `4a0f9d4b218e96273eed605e9edd0f9ab3564b68`.
5. Контрольные суммы SHA-256 артефактов и отчёта проверены и совпадают.
6. Входные sequence gates `H-L4D-06A-PB-v1` и промежуточный корректирующий handoff `H-L4D-06B-IOT-FIX-01-v1` приняты в журнале.

<!-- HANDOFF:H-L4D-06B-IOT-v1:BEGIN -->
```yaml
handoff_id: H-L4D-06B-IOT-v1
status: ACCEPTED
contract_kinds:
  - API
  - EVENT
  - DEPLOYMENT
producer_prompt_id: L4D-06B-IOT
producer_scope_project: iot-rpc-rest-app
producer_report_path: docs/l4desk/handoffs/L4D-06B-IOT-report.md
producer_branch: l4desk/l4d-06b-iot-fix-01
producer_commit: 4a0f9d4b218e96273eed605e9edd0f9ab3564b68
accepted_at_utc: 2026-09-19T11:55:00Z
contract_version: 1.0.0
schema_revision: 2026-09-18-v1
artifact_version: 1.0.0
artifact_paths:
  - docs/l4desk/contracts/schemas/device_provisioning_openapi.json
  - docs/l4desk/contracts/schemas/device_provision_request.schema.json
  - docs/l4desk/contracts/schemas/device_provision_response.schema.json
  - docs/l4desk/fixtures/device_provisioning_examples_v1.json
  - docs/l4desk/handoffs/L4D-06B-IOT-FIX-01-report.md
artifact_sha256:
  - dccc1beefc97be7b4d89502193cb865e95f7fe3b4a3bbae8d528574c7d736a3d
  - 3cba891ebef0e1783bda8bdf02821e3eb6f9a12eba080b31a735fb2c5a667081
  - 0f2914e286fbe665401dc412acb4308aa91741c5f6d3a141acd301e1bf1cf3a8
  - 86dd26818fadf2d8c4ea07113a77410f19f3cbbf64fb6eccc098100bf893c2fb
  - 5759fc1ab00dacfe2f16585f4df2753a8b4d5a8bc197af22f5b99c0fcff62d80
compatibility:
  backward_compatible_with:
    - H-L4D-06A-PB-v1
    - H-L4D-02-IOT-v1
  breaking_changes: false
  notes: "Versioned idempotent device and terminal provisioning contract implemented in iot-rpc-rest-app (/api/internal/v1/devices/provision) with evidence verified via L4D-06B-IOT-FIX-01. Supports exact identifier mapping (tenant_id: int, terminal_id: int, sn: str, operation_id: str, correlation_id: str | None), status states (requested, provisioned, failed), stable device_id/SN allocation, identity/tenant conflict protection (409 Conflict), and fact publishing into the durable tb_remote_session_events feed. Agent protocol and broker topologies remain 100% binary backward-compatible."
deployment_status: DEPLOYED
deployed_environment: production
feature_flags:
  device_provisioning_v1: enabled
contract_payload:
  evidence_source: L4D-06B-IOT-FIX-01
  verified_by_handoff: H-L4D-06B-IOT-FIX-01-v1
  identifiers:
    tenant_id: int
    terminal_id: int
    sn: str
    device_id: int
    operation_id: str
    correlation_id: str | None
  states:
    - requested
    - provisioned
    - failed
  endpoints:
    - method: POST
      path: /api/internal/v1/devices/provision
      auth: require_service_auth
      request_schema: DeviceProvisionRequest
      response_schema: DeviceProvisionResponse
      status_codes:
        201: Created (new device provisioned, replayed_flag=false)
        200: OK (idempotent replay of existing operation_id, replayed_flag=true)
        400: Bad Request (INVALID_PAYLOAD)
        401: Unauthorized (SERVICE_AUTH_FAILED)
        403: Forbidden (INVALID_CREDENTIALS)
        409: Conflict (OPERATION_ID_CONFLICT / IDENTITY_CONFLICT)
        422: Unprocessable Entity (validation error)
    - method: GET
      path: /api/internal/v1/devices/provision/by-operation/{operation_id}
      auth: require_service_auth
      response_schema: DeviceProvisionResponse
      status_codes:
        200: OK
        401: Unauthorized
        403: Forbidden
        404: Not Found (OPERATION_NOT_FOUND)
    - method: GET
      path: /api/internal/v1/devices/provision/by-sn/{sn}
      auth: require_service_auth
      response_schema: DeviceProvisionResponse
      status_codes:
        200: OK
        401: Unauthorized
        403: Forbidden
        404: Not Found (DEVICE_NOT_FOUND)
  events:
    - "device_provision_requested"
    - "device_provisioned"
    - "device_provision_failed"
  idempotency_semantics:
    replayed_flag: boolean
    conflict_on_parameter_change: true
    cross_tenant_sn_protection: enforced
    terminal_rebind_protection: enforced
  alembic_revision: 0005_device_provisioning
  tests_passed: 384
  verification_status: VERIFIED_READY
supersedes: []
known_risks:
  - "WEB_CONCURRENCY=1 invariant required for in-memory state consistency on app1"
  - "Requires valid certificate PIN issued by ProcessingBackend prior to provisioning"
consumers:
  - L4D-06C-MB
  - L4D-17C-IOT
  - L4D-18C-IOT
next_prompt_id: L4D-06C-MB
```
<!-- HANDOFF:H-L4D-06B-IOT-v1:END -->

## 13. Принятие handoff H-L4D-06C-MB-v1 (шаг 19 MenuBuilder)

Фиксация контроллером каскада принятого контракта `H-L4D-06C-MB-v1` шага 19 (`MenuBuilder`) по результатам проверки отчёта `MenuBuilder/docs/l4desk/handoffs/L4D-06C-MB-report.md`, корректирующего отчёта `MenuBuilder/docs/l4desk/handoffs/L4D-06C-MB-FIX-01-report.md` и отдельного кандидата `MenuBuilder/docs/l4desk/handoffs/L4D-06C-MB-FIX-01-candidate.md` в формате `DETACHED_V1` согласно §9 `PROMPT-STANDARD.md`.

Все 4 основания первичного отказа устранены и верифицированы:
1. Валидный коммит проверенной реализации: `c91b24cc155dc0013500162c6e517897d8074a42` (ветка `l4desk/l4d-06c-mb`).
2. Причина таймаута выпуска PIN устранена: изолированы границы транзакций в `terminal_onboarding_service.py` (`await self.db.commit()`), снята взаимная блокировка строк `l4desk_terminals` между `MenuBuilder` и `ProcessingBackend`.
3. Реальный live smoke evidence на продакшен-хосте `87.242.100.34`: полный онбординг выполнен за 0.375 секунды с выдачей статуса `HTTP 201 Created`, получением PIN (`pin_masked: ***468`), созданием записи в IoT (`iot: ready`) и корректным удалением (`HTTP 200 OK`). Идентичность работающего кода в контейнере `menubuilder-backend` (`a04a69c83d0b`) подтверждена по контрольной сумме SHA-256 (`54ba3aff7c3d...`).
4. Контрольные суммы SHA-256 всех 6 артефактов проверены побайтно и полностью совпадают. Блок кандидата оформлен строго по каноническому стандарту.
5. Входные sequence gates `H-L4D-06A-PB-v1` и `H-L4D-06B-IOT-v1` приняты в журнале.

<!-- HANDOFF:H-L4D-06C-MB-v1:BEGIN -->
```yaml
handoff_id: H-L4D-06C-MB-v1
status: ACCEPTED
contract_kinds:
  - API
  - DEPLOYMENT
producer_prompt_id: L4D-06C-MB
producer_scope_project: MenuBuilder
producer_report_path: MenuBuilder/docs/l4desk/handoffs/L4D-06C-MB-report.md
producer_branch: l4desk/l4d-06c-mb
producer_commit: c91b24cc155dc0013500162c6e517897d8074a42
accepted_at_utc: 2026-09-19T14:10:00Z
contract_version: 1.0.0
schema_revision: 2026-09-19-v1
artifact_version: 1.0.0
candidate_format: DETACHED_V1
detached_candidate_approved: true
candidate_path: MenuBuilder/docs/l4desk/handoffs/L4D-06C-MB-FIX-01-candidate.md
artifact_paths:
  - MenuBuilder/backend/app/routers/settings.py
  - MenuBuilder/backend/app/services/terminal_onboarding_service.py
  - MenuBuilder/frontend/src/routes/settings/TerminalsSettingsPage.tsx
  - MenuBuilder/frontend/src/api/settings.ts
  - MenuBuilder/backend/tests/test_terminal_onboarding.py
  - MenuBuilder/docs/l4desk/handoffs/L4D-06C-MB-FIX-01-report.md
artifact_sha256:
  - f9f34368b347dc67e9481d7c319d913dfb3ef5fbb99bd41123b5fe4f34245ad4
  - 54ba3aff7c3d35a99314d7759cf2714b685deeac8287b564990a33b817606089
  - 71d4d891c6b573858c1c4a1e1005a8e11847f0d529428178bd1cb509f8706827
  - a49a54e4a2b4f98cafbc33f62b15ebc140fc60fddf16c9f4c1a93501af16c093
  - 2d710f66d97adf541ed472cf4ba9914637ffcbb89b7726e818fabcc47262954e
  - 80c9b55ae6e814a0f3c6709846029f63e32e660dd8f9b544d6cd422bb24429ca
compatibility:
  backward_compatible_with:
    - H-L4D-06A-PB-v1
    - H-L4D-06B-IOT-v1
  breaking_changes: false
  notes: "Unified terminal onboarding consumer in MenuBuilder orchestrating H-L4D-06A-PB-v1 and H-L4D-06B-IOT-v1. Verified and confirmed under corrective step L4D-06C-MB-FIX-01."
deployment_status: DEPLOYED
deployed_environment: production
feature_flags:
  l4desk_terminal_onboarding_enabled: true
contract_payload:
  evidence_source: L4D-06C-MB-FIX-01
  verified_by_handoff: H-L4D-06C-MB-FIX-01-v1
  endpoints:
    onboard_status: /api/settings/terminals/onboard/status
    onboard_terminal: /api/settings/terminals
    onboard_terminal_alias: /api/settings/terminals/onboard
    retry_terminal_saga: /api/settings/terminals/{terminal_id}/retry
    terminal_readiness: /api/settings/terminals/{terminal_id}/readiness
    list_terminals: /api/settings/terminals
    delete_terminal: /api/settings/terminals/{terminal_id}
  saga_steps:
    - step_a: "IoT Device Provisioning (POST /api/internal/v1/devices/provision)"
    - step_b: "Certificate PIN Issuance (POST /api/certificates/pins/issue)"
  readiness_states:
    record: ["ready", "pending", "failed"]
    certificate: ["pending", "issued", "consumed", "expired", "failed"]
    iot: ["pending", "ready", "failed"]
    online: ["online", "offline"]
  quota_rules:
    free_tier_first_terminal: "ordinal == min_active_ordinal marked is_free=true"
    deletion_transfer: "free tier automatically reassigns to next earliest active terminal upon soft deletion"
  audit_security:
    plain_pin_persistence: "never stored in database or audit logs"
    audit_masking: "***773 pattern enforced across all audit events"
    consumer_pin_visibility: "plain PIN delivered on 201 Created and active query only, hidden once consumed or expired"
  deployed_host: 87.242.100.34
  live_smoke_evidence:
    status_code: 201
    execution_time_seconds: 0.375
    pin_masked: "***468"
    pin_state: "issued"
    provisioning_state: "ready"
    last_error: null
  tests_passed: 9
  full_backend_suite: 344
  verification_status: VERIFIED_READY
supersedes: []
known_risks:
  - "IoT platform (app1) requires WEB_CONCURRENCY=1 for in-memory session tracking consistency"
  - "External Agent download URL hosted on cloud.ru generic repository"
consumers:
  - L4D-07-IOT
  - ALL_FOLLOWING
next_prompt_id: L4D-07-IOT
```
<!-- HANDOFF:H-L4D-06C-MB-v1:END -->

## 14. Принятие handoff H-L4D-07-IOT-v1 (шаг 20 iot-rpc-rest-app)

Фиксация контроллером каскада принятого контракта `H-L4D-07-IOT-v1` шага 20 (`iot-rpc-rest-app`) по результатам приёмки отчёта `D:\work\iot.leo4.ru\iot-rpc-rest-app\docs\l4desk\handoffs\L4D-07-IOT-report.md`.

Все проверки выполнены и подтверждены инструментально:
1. Коммит проверенной реализации: `c4e892f4c1dbf8f967109e8a06c3f63b0c9bd483` (ветка `l4desk/l4d-07-iot`). Коммит отчёта: `2b21f4e3670cdd662999e225625dc3471bb242b9`.
2. Sequence gate пройден: предшествующий обязательный handoff `H-L4D-06C-MB-v1` принят в журнале, архитектурные разделы §3, §4, §5, §6, §8, §11, §12, §16, §17 соблюдены.
3. Единый session lock на устройство (`sn`), взаимное исключение между типами сессий (HTTP 409 `session_busy`), расширенный жизненный цикл (`starting`), командно-ориентированный graceful stop с bounded timeout (`asyncio.wait_for`, default 5.0s), media flow teardown и детекция stale-сессий полностью подтверждены. Инвариант контракта Агента v1 (топики MQTT, методы 7000–7002, payload) сохранён на 100%.
4. Побайтно проверены контрольные суммы SHA-256 для всех 5 артефактов реализации:
   - `docs/l4desk/contracts/schemas/remote_session.schema.json`: `d72324f4a468e5b94569a6f390d122ce38364581705c90b9fb4a241b56fb68bc`
   - `docs/l4desk/contracts/schemas/remote_session_event.schema.json`: `230a22727a493b2980ba85cb2735e50d5ac42ac9b110cf3a6f3ba03ea0ebb12b`
   - `docs/l4desk/contracts/schemas/iot_event_feed_openapi.json`: `621e2ed32a7c82237a44627e2768ba15b1689b5b53ddb51ab9af48a98f08af94`
   - `app-service/alembic/versions/2026_09_19_0006_add_remote_session_lock.py`: `7de502480a352e113fa7959384b40457f70994ae721a4aa6f46840f739022b4d`
   - `app-service/tests/core/test_l4d_07_session_lock_and_graceful_stop.py`: `c691b7bfdd6e3bb63c8584fb90f3a00b2df7931a2ebf9e5cdeb69e7d521053e8`
5. Тестовый сьют `iot-rpc-rest-app` успешно пройден: 396 passed, 0 failed, 0 errors.

<!-- HANDOFF:H-L4D-07-IOT-v1:BEGIN -->
```yaml
handoff_id: H-L4D-07-IOT-v1
status: ACCEPTED
contract_kinds:
  - API
  - EVENT
  - DEPLOYMENT
producer_prompt_id: L4D-07-IOT
producer_scope_project: iot-rpc-rest-app
producer_report_path: docs/l4desk/handoffs/L4D-07-IOT-report.md
producer_branch: l4desk/l4d-07-iot
producer_commit: c4e892f4c1dbf8f967109e8a06c3f63b0c9bd483
report_commit: 2b21f4e3670cdd662999e225625dc3471bb242b9
accepted_at_utc: 2026-09-19T18:36:14Z
contract_version: 1.0.0
schema_revision: 2026-09-19-v1
artifact_version: 1.0.0
previous_handoff_ids:
  - H-L4D-06C-MB-v1
  - H-L4D-01C-DOCS-v1
  - H-L4D-02-IOT-v1
consumers:
  - L4D-08A-MEDIA
  - L4D-08B-MB
  - L4D-12-MB
architecture_sections:
  - 3
  - 4
  - 5
  - 6
  - 8
  - 11
  - 12
  - 16
  - 17
artifact_paths:
  - docs/l4desk/contracts/schemas/remote_session.schema.json
  - docs/l4desk/contracts/schemas/remote_session_event.schema.json
  - docs/l4desk/contracts/schemas/iot_event_feed_openapi.json
  - app-service/alembic/versions/2026_09_19_0006_add_remote_session_lock.py
  - app-service/tests/core/test_l4d_07_session_lock_and_graceful_stop.py
artifact_sha256:
  - d72324f4a468e5b94569a6f390d122ce38364581705c90b9fb4a241b56fb68bc
  - 230a22727a493b2980ba85cb2735e50d5ac42ac9b110cf3a6f3ba03ea0ebb12b
  - 621e2ed32a7c82237a44627e2768ba15b1689b5b53ddb51ab9af48a98f08af94
  - 7de502480a352e113fa7959384b40457f70994ae721a4aa6f46840f739022b4d
  - c691b7bfdd6e3bb63c8584fb90f3a00b2df7931a2ebf9e5cdeb69e7d521053e8
compatibility:
  backward_compatible_with:
    - H-L4D-02-IOT-v1
    - H-L4D-06B-IOT-v1
    - H-L4D-06C-MB-v1
  breaking_changes: false
  notes: "Unified session lock and mutual exclusion per device (sn) for console and video remote sessions. Command-aware graceful stop with bounded timeout for console sessions and media flow teardown for video sessions. Strict lifecycle states (requested, starting, active, stopping, closed, failed) published to durable event feed 02. Agent Contract v1 protocol, MQTT topics, and payloads are 100% binary backward-compatible and untouched."
deployment_status: DEPLOYED
deployed_environment: production
feature_flags:
  session_lock_enabled: true
  graceful_stop_enabled: true
contract_payload:
  session_lock:
    ownership: "iot-rpc-rest-app"
    cardinality: "exactly_one_active_or_starting_per_device_sn"
    enforcement: "uq_active_remote_session_per_sn partial index + transaction lock"
    conflict_status: 409
    conflict_code: "session_busy"
  lifecycle_states:
    - requested
    - starting
    - active
    - stopping
    - closed
    - failed
  graceful_stop:
    console: "command_aware_wait_or_timeout_new_commands_rejected"
    video: "remote_media_flow_teardown_lease_revoked"
    unbounded_wait: forbidden
  billable_interval:
    start_point: "started_at (state: active)"
    end_point: "closed_at (state: closed)"
    pre_active_billing: prohibited
  agent_contract_v1:
    topics_modified: false
    methods_modified: false
    payloads_modified: false
  alembic_revision: "0006_remote_session_lock"
  tests_passed: 396
  verification_status: VERIFIED_READY
supersedes: []
known_risks:
  - "WEB_CONCURRENCY=1 invariant required for in-memory session tracking consistency"
  - "In-flight commands without terminal response are terminated after bounded timeout_sec (default 5.0s, max 60.0s)"
consumers:
  - L4D-08A-MEDIA
  - L4D-08B-MB
  - L4D-12-MB
next_prompt_id: L4D-08A-MEDIA
```
<!-- HANDOFF:H-L4D-07-IOT-v1:END -->

## 15. Принятие handoff H-L4D-08A-MEDIA-v1 (шаг 21 l4media)

Фиксация контроллером каскада принятого контракта `H-L4D-08A-MEDIA-v1` шага 21 (`l4media`) по результатам приёмки отчёта `l4media/docs/l4desk/handoffs/L4D-08A-MEDIA-report.md`.

Все проверки выполнены и подтверждены инструментально:
1. Коммит проверенной реализации: `37adfd01e5492e6b61e8ecb243579389ae2d858e` (ветка `l4desk/l4d-08a-media`). Коммит отчёта: `aba1339a315bcc5956bb8686a0ad5cc113eee8fd`.
2. Sequence gate пройден: предшествующий обязательный handoff `H-L4D-07-IOT-v1` принят в журнале (шаг 20), совместимость с baseline `H-L4D-00D-MEDIA-v1` подтверждена.
3. Реализован и развернут аддитивный API управления жизненным циклом медиасессий по требованию на порту 9100 сервиса `l4media-ingress` (`/api/v1/media/sessions/start`, `/sessions/{session_id}`, `/sessions/{session_id}/stop`, `/reconcile`, `/metrics`, `/openapi.json`) со служебной авторизацией (`X-Media-Service-Token`).
4. Гарантии надежности и предотвращения утечек ресурсов: компенсирующий откат (compensating rollback), сторожевой таймер сессий (TTL watchdog), автоматическая периодическая (каждые 60 с) и ручная reconciliation для удаления orphan-маунтпоинтов Janus и маршрутов Ingress, изоляция устройств (409 Conflict `session_busy`), детерминированная идемпотентность повторных вызовов start/stop.
5. Инструментально проверены контрольные суммы SHA-256 артефактов:
   - `l4media/ingress/openapi.json`: `ba2b4a19fd5c568a4b758b57121b01bf3062533906fcbd9e55991fc59157fcec` (совпадение 100%)
   - `l4media/docs/l4desk/handoffs/L4D-08A-MEDIA-report.md`: `449a8b1a6a4e6ac3bdbb153058e8823f3134fa613aa3f446a04bec47163eacb1`
6. Тестирование и верификация: 7/7 C unit-тестов успешно пройдены, 9/9 интеграционных тестов `test_media_lifecycle.py` пройдены, 6/6 регрессионных тестов `test_ingress_regression.py` пройдены, 7/7 проверок `check.sh` на хосте 87.242.100.34 пройдены. Внешние контейнеры не затронуты.

<!-- HANDOFF:H-L4D-08A-MEDIA-v1:BEGIN -->
```yaml
handoff_id: H-L4D-08A-MEDIA-v1
status: ACCEPTED
contract_kinds:
  - API
  - DEPLOYMENT
producer_prompt_id: L4D-08A-MEDIA
producer_scope_project: l4media
producer_report_path: l4media/docs/l4desk/handoffs/L4D-08A-MEDIA-report.md
producer_branch: l4desk/l4d-08a-media
producer_commit: 37adfd01e5492e6b61e8ecb243579389ae2d858e
report_commit: aba1339a315bcc5956bb8686a0ad5cc113eee8fd
accepted_at_utc: 2026-09-20T08:37:00Z
contract_version: 1.0.0
schema_revision: 1.0.0
artifact_version: 1.0.0
artifact_paths:
  - l4media/ingress/openapi.json
artifact_sha256:
  - ba2b4a19fd5c568a4b758b57121b01bf3062533906fcbd9e55991fc59157fcec
compatibility:
  backward_compatible_with:
    - H-L4D-00D-MEDIA-v1
  breaking_changes: false
  notes: Additive service-authenticated on-demand media session lifecycle API on l4media-ingress port 9100. Retains 100% backward compatibility for legacy /health, /stats, /routes. Provides atomic start, health monitoring, stop, automated reconciliation of orphan Janus mountpoints/routes, and TTL watchdog.
deployment_status: DEPLOYED
deployed_environment: production
feature_flags: {}
contract_payload:
  identifiers:
    session_id: correlation session identifier from 07 external contract (string)
    operation_id: client idempotency operation identifier (string)
    sn: terminal serial number (ASCII string)
    device_id: numeric device ID / Janus mountpoint ID (integer)
    rtp_port: dynamically allocated Janus video RTP port in range 6010-6200 (integer)
    rtcp_port: dynamically allocated Janus video RTCP port (rtp_port + 1) (integer)
  operations_events:
    - POST /api/v1/media/sessions/start (start session, allocate ports, create Janus mountpoint, insert ingress route, idempotent repeat)
    - GET /api/v1/media/sessions/{session_id} (session health, state, freshness, timestamps, elapsed/remaining TTL)
    - POST /api/v1/media/sessions/{session_id}/stop (stop session, harvest final stats, delete ingress route, destroy Janus mountpoint, idempotent repeat)
    - POST /api/v1/media/reconcile (reconciliation of orphan Janus mountpoints and Ingress routes)
    - GET /api/v1/media/metrics (aggregate technical and audit metrics)
    - GET /api/v1/openapi.json (OpenAPI 3.0.3 specification)
  errors:
    400: invalid_request (missing session_id or sn)
    401: unauthorized (missing or invalid X-Media-Service-Token / Bearer token)
    404: session_not_found (no session with specified session_id)
    409: session_busy (active session already exists on device sn), session_terminated
    502: janus_error (Janus Admin API gateway communication failure)
    503: port_exhaustion (RTP port range exhausted), max_sessions_exceeded
  invariants:
    - Service authentication enforced on all /api/v1/media/* endpoints via X-Media-Service-Token or Authorization: Bearer
    - Deterministic repeated start returns 200 OK with identical session connection parameters
    - Deterministic repeated stop returns 200 OK with state=stopped
    - Stop of non-existent or already-stopped session returns 200 OK
    - Exactly one active session per terminal SN at any given time (enforces device mutual exclusion)
    - Atomic rollback on partial start: failure during route upsert triggers compensating destroy of Janus mountpoint
    - Automated TTL watchdog terminates sessions and frees resources upon ttl_sec expiration
    - Periodic background reconciliation every 60s prunes orphan Janus mountpoints and routes while protecting static routes and default mountpoint 1
    - Technical timestamps (created_at, started_at, stopped_at, last_rtp_at) and streaming counters (rtp_packets, bytes) provided for audit; no billing decisions made in media layer
supersedes: []
known_risks: []
consumers:
  - L4D-08B-MB
next_prompt_id: L4D-08B-MB
```
<!-- HANDOFF:H-L4D-08A-MEDIA-v1:END -->

## 16. Регистрация корректирующего шага L4D-08B-MB-FIX-01 (шаг 22 MenuBuilder)

Регистрация корректирующего шага `L4D-08B-MB-FIX-01` для устранения дефектов схемы candidate-блока, актуализации контрольных сумм SHA-256 артефактов и привязки проверенного коммита реализации `ad5a13d9fce804746f4f961812b8a026ba416bf4` в соответствии с §8 и §9 `PROMPT-STANDARD.md`.

<!-- CORRECTIVE_REGISTRATION:R-L4D-08B-MB-FIX-01-v1:BEGIN -->
```yaml
registration_id: R-L4D-08B-MB-FIX-01-v1
status: AUTHORIZED
authorized_by: Cascade Controller
authorization_basis: explicit_user_request_and_controller_rejection_findings
registered_at_utc: 2026-09-20T11:20:00Z
prompt_id: L4D-08B-MB-FIX-01
prompt_path: l4desk-service/docs/prompts/L4D-08B-MB-FIX-01.md
scope_project: MenuBuilder
scope_root: D:\repo\platerra\Public\etranprocessing\MenuBuilder
blocked_prompt_id: L4D-08B-MB
authorized_inputs:
  - handoff_id: H-L4D-07-IOT-v1
    contract_version: 1.0.0
    producer_commit: 55462cf8e847c1ba420d9f485db7112ea1bc8fe8
  - handoff_id: H-L4D-08A-MEDIA-v1
    contract_version: 1.0.0
    producer_commit: 37adfd01e5492e6b61e8ecb243579389ae2d858e
sequence_gate_handoff_id: H-L4D-08A-MEDIA-v1
output_handoff_id: H-L4D-08B-MB-FIX-01-v1
next_prompt_id: L4D-08B-MB
report_path: MenuBuilder/docs/l4desk/handoffs/L4D-08B-MB-FIX-01-report.md
candidate_format: DETACHED_V1
detached_candidate_approved: true
candidate_path: MenuBuilder/docs/l4desk/handoffs/L4D-08B-MB-FIX-01-candidate.md
publication_required_before_execution: true
grant_scope: consumer_addressing_and_finite_data_only_reads
runtime_acceptance: NOT_GRANTED
blocked_next_prompt_id: L4D-09-MB
```
<!-- CORRECTIVE_REGISTRATION:R-L4D-08B-MB-FIX-01-v1:END -->

## 17. Принятие handoff H-L4D-08B-MB-FIX-01-v1 (DETACHED_V1)

Фиксация контроллером каскада принятого корректирующего контракта `H-L4D-08B-MB-FIX-01-v1` по результатам проверки отчёта `MenuBuilder/docs/l4desk/handoffs/L4D-08B-MB-FIX-01-report.md` и отдельного кандидата `MenuBuilder/docs/l4desk/handoffs/L4D-08B-MB-FIX-01-candidate.md` в формате `DETACHED_V1` согласно §9 `PROMPT-STANDARD.md` и нормативной регистрации `R-L4D-08B-MB-FIX-01-v1`.

Все 4 основания первичного отказа устранены и подтверждены контрольной проверкой:
1. `HASH_MISMATCH` и структурный дефект схемы устранены: количество путей в `artifact_paths` (14) строго равно количеству сумм в `artifact_sha256` (14), `main.py` включён, файл конфигурации хоста `port_3000.conf` исключён из scope `MenuBuilder`.
2. Коммит реализации зафиксирован как `producer_commit: ad5a13d9fce804746f4f961812b8a026ba416bf4` (ветка `l4desk/l4d-08b-mb`), изменения строго изолированы в проекте `MenuBuilder`. Коммит публикации отчётов: `report_commit: 8bd1bc52cf2614188f82745c0dcc49a8562792b6`. Коммит отдельного кандидата: `ebcead566ca270e61dc6a10e1c9c8e8bd077e6db`.
3. Candidate-блок вынесен в отдельный файл `candidate_path: MenuBuilder/docs/l4desk/handoffs/L4D-08B-MB-FIX-01-candidate.md` (`DETACHED_V1`).
4. Ошибка базы данных (нарушение check-констрейнта `l4desk_session_active_ck` на легаси-эндпоинтах `/control/lease` и `/stream/start`) устранена в репозитории и роутере, подтверждена регрессионными тестами и live smoke-проверками в контейнере `menubuilder-backend` на хосте `87.242.100.34`.
5. Контрольные суммы SHA-256 всех 14 артефактов проверены побайтно и полностью совпадают на 100%. Sequence gate `H-L4D-08A-MEDIA-v1` и регистрация `R-L4D-08B-MB-FIX-01-v1` подтверждены.

<!-- HANDOFF:H-L4D-08B-MB-FIX-01-v1:BEGIN -->
```yaml
handoff_id: H-L4D-08B-MB-FIX-01-v1
status: ACCEPTED
contract_kinds:
  - API
  - DEPLOYMENT
producer_prompt_id: L4D-08B-MB-FIX-01
producer_scope_project: MenuBuilder
producer_report_path: MenuBuilder/docs/l4desk/handoffs/L4D-08B-MB-FIX-01-report.md
producer_branch: l4desk/l4d-08b-mb
producer_commit: ad5a13d9fce804746f4f961812b8a026ba416bf4
report_commit: 8bd1bc52cf2614188f82745c0dcc49a8562792b6
accepted_at_utc: 2026-09-20T11:40:00Z
contract_version: 1.0.0
schema_revision: 1.0.0
artifact_version: 1.0.0
candidate_format: DETACHED_V1
detached_candidate_approved: true
candidate_path: MenuBuilder/docs/l4desk/handoffs/L4D-08B-MB-FIX-01-candidate.md
artifact_paths:
  - MenuBuilder/backend/app/services/remote_session_use_case.py
  - MenuBuilder/backend/app/services/media_orchestrator_client.py
  - MenuBuilder/backend/app/services/remote_session_policy.py
  - MenuBuilder/backend/app/routers/remote_sessions.py
  - MenuBuilder/backend/app/routers/video_control.py
  - MenuBuilder/backend/app/routers/video.py
  - MenuBuilder/backend/app/repositories/l4desk_repository.py
  - MenuBuilder/backend/app/config.py
  - MenuBuilder/backend/app/main.py
  - MenuBuilder/frontend/src/api/video.ts
  - MenuBuilder/frontend/src/routes/video-surveillance.tsx
  - MenuBuilder/frontend/src/routes/devices/DeviceConsoleTab.tsx
  - MenuBuilder/backend/tests/test_remote_session_orchestration.py
  - MenuBuilder/docs/l4desk/handoffs/L4D-08B-MB-FIX-01-report.md
artifact_sha256:
  - e83af253732b11d89e63c18562b563420ae6b228492f40eee74d27de07df2389
  - 65b07e3b35eccbfa412ec75a8b1362f1cdf682107af51385e5e06e4d8652ed8a
  - 688e4d3d31ab4c623d4bc85f602ede31bb935ee39394e88fd3de08c5444e5ca5
  - f6612a7f679e6e1c73d74128911dcbe608778fb9d8212ac2f93096777e94dd72
  - 0ec7212e941b825407a15e47d68fd499298b5f230e6e1e963848f94e09f1d69b
  - ac7856605aa42cc24db1ec8657d5f5959e6496a35e5940ff68dbc614f78f03bc
  - 46947572410dab6e163f7ca9f3f22644ef8c33c3629edef51709915a81aefb23
  - 31782a1eb607a3f84375ef798ed000e614de33c09161e7353d0855b6db6a3116
  - d54d19cfe79fc00a2c1d3db397cb83c44759f02c018742c0131676e716626e55
  - ae38c22884ad8246cbcaefb70aa49be5b42687dfa477f7b19860b0224c789ea7
  - 87f8dbc8e396bad3d6c35005d1672cc9a48815afbb894323378bf9e095b72d14
  - d8b93b0ab0285781f33efba06dfca6d3469ddf2872ec48ec8b3333e7fc7a1cf5
  - c34880ca65b4ac4b81a25b26034d1c2317f9f224c46a189cbcd450fcf3c030f1
  - 3d242f40722d1e8b9e65a8c7808a11c9c58ce27688534ef85bbc525afef38460
compatibility:
  backward_compatible_with:
    - H-L4D-07-IOT-v1
    - H-L4D-08A-MEDIA-v1
  breaking_changes: false
  notes: "Corrective handoff package resolving HASH_MISMATCH, schema alignment, and PostgreSQL check constraint l4desk_session_active_ck on remote session creation."
deployment_status: DEPLOYED
deployed_environment: production
feature_flags:
  l4desk_session_orchestration_enabled: true
  l4desk_policy_enforcement_enabled: false
contract_payload:
  corrects_candidate: H-L4D-08B-MB-v1
  registration_id: R-L4D-08B-MB-FIX-01-v1
  evidence_source: L4D-08B-MB-FIX-01
  endpoints:
    start_session: /api/v1/remote-sessions/start
    stop_session: /api/v1/remote-sessions/stop
    stop_session_by_id: /api/v1/remote-sessions/{session_id}/stop
    device_active_session: /api/v1/remote-sessions/devices/{device_id}/active
  policy_seam:
    interface: RemoteSessionPolicy
    legacy_implementation: PermissiveLegacyPolicy
    commercial_implementation: L4DeskEntitlementPolicy (disabled in 08B)
  error_mapping:
    400: invalid_request
    401: unauthorized
    403: tenant_forbidden, permission_denied, policy_denied
    404: terminal_not_found
    409: session_busy (active session conflict, automatic switch forbidden), lease_conflict
    502: iot_gateway_error, media_gateway_error
  invariants:
    - Exactly one active remote session per terminal device across both console and video
    - Automatic cross-switching between console and video is strictly forbidden
    - Replay with identical operation_id returns active session parameters idempotently
    - Partial failure during media or stream launch executes compensating stop on IoT and releases control lease
supersedes: []
known_risks: []
consumers:
  - L4D-08B-MB
next_prompt_id: L4D-08B-MB
```
<!-- HANDOFF:H-L4D-08B-MB-FIX-01-v1:END -->

## 18. Повторная приёмка основного шага 22 L4D-08B-MB (H-L4D-08B-MB-v1)

Повторная приёмка контроллером каскада основного шага 22 `L4D-08B-MB` (`MenuBuilder`) на основе исправленного и проверенного пакета `L4D-08B-MB-FIX-01` (коммит реализации `ad5a13d9fce804746f4f961812b8a026ba416bf4`, ветка `l4desk/l4d-08b-mb`).

Все требования к приёмке основного шага выполнены:
1. Входные sequence gates `H-L4D-07-IOT-v1`, `H-L4D-08A-MEDIA-v1` и промежуточный корректирующий handoff `H-L4D-08B-MB-FIX-01-v1` приняты в журнале.
2. Единая оркестрация удалённых сессий консоли и видео (`RemoteSessionUseCase`) реализована с изоляцией тенантов, взаимным исключением (HTTP 409 `session_busy`), запретом автопереключения между консолью и видео, компенсирующим откатом при частичных сбоях медиа/стрима и policy seam (`PermissiveLegacyPolicy` по умолчанию, подготовлен шов к `L4D-12-MB`).
3. Контрольные суммы SHA-256 всех 14 артефактов проверены инструментально и совпадают на 100%.
4. Кандидат оформлен по стандарту `DETACHED_V1` в файле `MenuBuilder/docs/l4desk/handoffs/L4D-08B-MB-candidate.md`.
5. Разрешён переход к следующему шагу каскада: `L4D-09-MB` (потребитель: `MenuBuilder`).

<!-- HANDOFF:H-L4D-08B-MB-v1:BEGIN -->
```yaml
handoff_id: H-L4D-08B-MB-v1
status: ACCEPTED
contract_kinds:
  - API
  - DEPLOYMENT
producer_prompt_id: L4D-08B-MB
producer_scope_project: MenuBuilder
producer_report_path: MenuBuilder/docs/l4desk/handoffs/L4D-08B-MB-report.md
producer_branch: l4desk/l4d-08b-mb
producer_commit: ad5a13d9fce804746f4f961812b8a026ba416bf4
report_commit: 8bd1bc52cf2614188f82745c0dcc49a8562792b6
accepted_at_utc: 2026-09-20T11:41:00Z
contract_version: 1.0.0
schema_revision: 1.0.0
artifact_version: 1.0.0
candidate_format: DETACHED_V1
detached_candidate_approved: true
candidate_path: MenuBuilder/docs/l4desk/handoffs/L4D-08B-MB-candidate.md
artifact_paths:
  - MenuBuilder/backend/app/services/remote_session_use_case.py
  - MenuBuilder/backend/app/services/media_orchestrator_client.py
  - MenuBuilder/backend/app/services/remote_session_policy.py
  - MenuBuilder/backend/app/routers/remote_sessions.py
  - MenuBuilder/backend/app/routers/video_control.py
  - MenuBuilder/backend/app/routers/video.py
  - MenuBuilder/backend/app/repositories/l4desk_repository.py
  - MenuBuilder/backend/app/config.py
  - MenuBuilder/backend/app/main.py
  - MenuBuilder/frontend/src/api/video.ts
  - MenuBuilder/frontend/src/routes/video-surveillance.tsx
  - MenuBuilder/frontend/src/routes/devices/DeviceConsoleTab.tsx
  - MenuBuilder/backend/tests/test_remote_session_orchestration.py
  - MenuBuilder/docs/l4desk/handoffs/L4D-08B-MB-report.md
artifact_sha256:
  - e83af253732b11d89e63c18562b563420ae6b228492f40eee74d27de07df2389
  - 65b07e3b35eccbfa412ec75a8b1362f1cdf682107af51385e5e06e4d8652ed8a
  - 688e4d3d31ab4c623d4bc85f602ede31bb935ee39394e88fd3de08c5444e5ca5
  - f6612a7f679e6e1c73d74128911dcbe608778fb9d8212ac2f93096777e94dd72
  - 0ec7212e941b825407a15e47d68fd499298b5f230e6e1e963848f94e09f1d69b
  - ac7856605aa42cc24db1ec8657d5f5959e6496a35e5940ff68dbc614f78f03bc
  - 46947572410dab6e163f7ca9f3f22644ef8c33c3629edef51709915a81aefb23
  - 31782a1eb607a3f84375ef798ed000e614de33c09161e7353d0855b6db6a3116
  - d54d19cfe79fc00a2c1d3db397cb83c44759f02c018742c0131676e716626e55
  - ae38c22884ad8246cbcaefb70aa49be5b42687dfa477f7b19860b0224c789ea7
  - 87f8dbc8e396bad3d6c35005d1672cc9a48815afbb894323378bf9e095b72d14
  - d8b93b0ab0285781f33efba06dfca6d3469ddf2872ec48ec8b3333e7fc7a1cf5
  - c34880ca65b4ac4b81a25b26034d1c2317f9f224c46a189cbcd450fcf3c030f1
  - 7c442c52c20e5944c667d14869f791f455d7e0de12802e511f79c672a9b206f9
compatibility:
  backward_compatible_with:
    - H-L4D-07-IOT-v1
    - H-L4D-08A-MEDIA-v1
  breaking_changes: false
  notes: "Unified RemoteSessionUseCase for console and video session orchestration across legacy MenuBuilder users and L4Desk commercial profile. Enforces mutual exclusion (session_busy 409, no auto-switch), compensating stop upon partial provider failures, and provides a policy seam with disabled entitlement flag. Verified and confirmed under corrective step L4D-08B-MB-FIX-01."
deployment_status: DEPLOYED
deployed_environment: production
feature_flags:
  l4desk_session_orchestration_enabled: true
  l4desk_policy_enforcement_enabled: false
contract_payload:
  evidence_source: L4D-08B-MB-FIX-01
  verified_by_handoff: H-L4D-08B-MB-FIX-01-v1
  endpoints:
    start_session: /api/v1/remote-sessions/start
    stop_session: /api/v1/remote-sessions/stop
    stop_session_by_id: /api/v1/remote-sessions/{session_id}/stop
    device_active_session: /api/v1/remote-sessions/devices/{device_id}/active
  policy_seam:
    interface: RemoteSessionPolicy
    legacy_implementation: PermissiveLegacyPolicy
    commercial_implementation: L4DeskEntitlementPolicy (disabled in 08B)
  error_mapping:
    400: invalid_request
    401: unauthorized
    403: tenant_forbidden, permission_denied, policy_denied
    404: terminal_not_found
    409: session_busy (active session conflict, automatic switch forbidden), lease_conflict
    502: iot_gateway_error, media_gateway_error
  invariants:
    - Exactly one active remote session per terminal device across both console and video
    - Automatic cross-switching between console and video is strictly forbidden
    - Replay with identical operation_id returns active session parameters idempotently
    - Partial failure during media or stream launch executes compensating stop on IoT and releases control lease
supersedes: []
known_risks: []
consumers:
  - L4D-09-MB
next_prompt_id: L4D-09-MB
```
<!-- HANDOFF:H-L4D-08B-MB-v1:END -->

## 19. Принятие handoff H-L4D-09-MB-v1 (шаг 23 MenuBuilder)

Фиксация контроллером каскада принятого контракта `H-L4D-09-MB-v1` шага 23 (`MenuBuilder`) по результатам приёмки отчёта `MenuBuilder/docs/l4desk/handoffs/L4D-09-MB-report.md` и кандидата `MenuBuilder/docs/l4desk/handoffs/L4D-09-MB-candidate.md`.

Все проверки выполнены и подтверждены инструментально:
1. Коммит проверенной реализации: `3d0dddba68df211a1d6c89844e0311b43bccd44d` (ветка `l4desk/l4d-09-mb`). Коммит отчёта и кандидата: `d487bc23011d90cad1ab9945abf480fca73e397a`.
2. Sequence gate пройден: предшествующий обязательный handoff `H-L4D-08B-MB-v1` (шаг 22) и промежуточный `H-L4D-04C-MB-v1` приняты в журнале со статусом `ACCEPTED`. Архитектурные разделы §3, §5, §7, §9, §10, §13, §14, §15, §16, §17 соблюдены.
3. Финансовое ядро двойной записи (`fin_*` subledger) и быстрая проекция баланса реализованы в `MenuBuilder`:
   - `FinAccountService`: обеспечение системных счетов (`payment_clearing`, `usage_revenue`) и расчетных счетов тенантов (`tenant_settlement`).
   - `FinPostingService`: строгий append-only аудит (`FinLedgerTransaction`, `FinLedgerEntry`), инвариант двойной записи (`sum(debit) == sum(credit) > 0`), запрет `float`, целочисленные рубли (кратность 100 копейкам), односторонность строк, идемпотентность и строгая изоляция тенантов.
   - `FinProjectionService`: баланс тенанта $\text{credits} - \text{debits}$, атомарное обновление проекции `fin_balance_projections` с оптимистической блокировкой версий, возможность полного пересчета/восстановления из журнала проводок.
   - `FinReversalService`: корректирующие транзакции (`reversal`) с инверсией проводок и ссылкой `corrects_transaction_id`.
   - `FinReconciliationService`: регламентный аудит и сверка целостности за период, проверка констрейнтов и авто-пересчет.
   - REST API эндпоинты (`/api/v1/finance/balance`, `/api/v1/finance/transactions`, `/api/internal/v1/finance/*`).
4. Побайтно проверены контрольные суммы SHA-256 для всех 14 артефактов реализации и отчёта — совпадают на 100%.
5. Тестовый набор успешно пройден: 20 passed в `test_financial_core.py`, полный набор `MenuBuilder/backend` 376 passed (0 failures, 0 errors).
6. Live smoke evidence на боевом сервере `87.242.100.34` подтверждён (транзакция пополнения -> сторно -> сверка -> пересчет проекции, баланс возвращен в 0).
7. Кандидат оформлен по стандарту `DETACHED_V1` в файле `MenuBuilder/docs/l4desk/handoffs/L4D-09-MB-candidate.md`.
8. Разрешён переход к следующему шагу каскада: `L4D-10-MB` (потребитель: `MenuBuilder`).

<!-- HANDOFF:H-L4D-09-MB-v1:BEGIN -->
```yaml
handoff_id: H-L4D-09-MB-v1
status: ACCEPTED
contract_kinds:
  - SCHEMA
  - API
  - DEPLOYMENT
producer_prompt_id: L4D-09-MB
producer_scope_project: MenuBuilder
producer_report_path: MenuBuilder/docs/l4desk/handoffs/L4D-09-MB-report.md
producer_branch: l4desk/l4d-09-mb
producer_commit: 3d0dddba68df211a1d6c89844e0311b43bccd44d
report_commit: d487bc23011d90cad1ab9945abf480fca73e397a
accepted_at_utc: '2026-09-20T13:00:00Z'
contract_version: 1.0.0
schema_revision: '027'
artifact_version: 1.0.0
candidate_format: DETACHED_V1
detached_candidate_approved: true
candidate_path: MenuBuilder/docs/l4desk/handoffs/L4D-09-MB-candidate.md
artifact_paths:
  - MenuBuilder/backend/app/config.py
  - MenuBuilder/backend/app/main.py
  - MenuBuilder/backend/app/repositories/l4desk_repository.py
  - MenuBuilder/backend/app/routers/finance.py
  - MenuBuilder/backend/app/services/financial_core/__init__.py
  - MenuBuilder/backend/app/services/financial_core/accounts.py
  - MenuBuilder/backend/app/services/financial_core/exceptions.py
  - MenuBuilder/backend/app/services/financial_core/posting.py
  - MenuBuilder/backend/app/services/financial_core/projection.py
  - MenuBuilder/backend/app/services/financial_core/reconciliation.py
  - MenuBuilder/backend/app/services/financial_core/reversal.py
  - MenuBuilder/backend/app/services/financial_core/schemas.py
  - MenuBuilder/backend/tests/test_financial_core.py
  - MenuBuilder/docs/l4desk/handoffs/L4D-09-MB-report.md
artifact_sha256:
  - a5157b6de75e801a9e8c169fb40f4b0e3af2172d5ccf9282f99bb6a0ec49ba07
  - ea8e5f4bc9ff71ffd45d8aee6533be20fc2081304d73f6f5dfd66fcb2e0ac74a
  - 5cd4aa664214126f3cb8dba146d1da14400081cf551992a4a944e3d24cfabcb7
  - 2b9cfab30ae756600b413fa2b2dd2c111f22c93a712643a1d22569d33ea93974
  - 8fb7e50c8d1b8c0da185f3daf785c821d16270ccb47a71442fbc4d01055d582b
  - 731512c8cc5e10c65325b6f746c259f5a01cc0c15e39eaba39e612c8b060c2a8
  - d075e093ca2e8c33503af5a2b16f84946dbcf7b3412f6f6a9d86e31d8fda173d
  - e0033fcf38e1d0a704a3aabb9c8decd44bfb0533c3e8eac67e27879e3557a30b
  - 765a69fad521a893d7cd5fe0f7325f190d53645627aa609ae8e0297a71654af0
  - 64169deadcc64c71187ed0b3f9131a27c36ee8e8490faddd75bbcde91f83064f
  - a0c39a49c132b88f159e6dcd7c5df1e733941ffe073b1b2701a93dc8bee8c7a1
  - 6f839a54bacc139225a20164a3c22623e4e71e845fd112891a4edfb09c8984f0
  - 5b01420ff87ed7d42af838344e79c63b2087d41c39cc74ac404984dac4279aea
  - 729436d7a0ba76b601acc1261287b6264391fc48a5a44f888fc37d71ba8791b8
compatibility:
  backward_compatible_with:
    - H-L4D-08B-MB-v1
    - H-L4D-04C-MB-v1
  breaking_changes: false
  notes: Minimal double-entry fin_* subledger and fast balance projection for MenuBuilder with strict append-only constraints, whole-ruble kopecks, optimistic version locking, reversal support, and periodic reconciliation audits.
deployment_status: DEPLOYED
deployed_environment: production
feature_flags:
  l4desk_financial_core_enabled: true
  l4desk_billing_enabled: false
contract_payload:
  account_kinds:
    - tenant_settlement
    - payment_clearing
    - usage_revenue
  currency: RUB
  subledger_invariants:
    - "double_entry: sum(debit_kopecks) == sum(credit_kopecks) > 0"
    - "integer_only: integer kopecks strictly required, float prohibited"
    - "whole_rubles_rule: debit_kopecks % 100 == 0, credit_kopecks % 100 == 0"
    - "single_sided_entries: exactly one positive side per entry (debit xor credit)"
    - "immutability: update and delete of posted transactions and entries strictly prohibited"
    - "tenant_isolation: all transaction entries and tenant accounts must match transaction tenant_id"
    - "reversal_rule: corrections reference original via corrects_transaction_id with inverse entries"
  balance_projection_rule: "balance_kopecks = credits(tenant_settlement) - debits(tenant_settlement)"
  projection_concurrency: "optimistic locking with version increment and row locking in same DB transaction"
  reconciliation_checks:
    - ledger_balance
    - reversal_invariants
    - tenant_isolation
    - projection_consistency
    - duplicate_posting
    - corruption_detection
  endpoints:
    tenant_balance: GET /api/v1/finance/balance
    tenant_transactions: GET /api/v1/finance/transactions
    internal_post: POST /api/internal/v1/finance/post
    internal_reversal: POST /api/internal/v1/finance/reversal
    internal_rebuild: POST /api/internal/v1/finance/rebuild-projection/{tenant_id}
    internal_reconciliation: POST /api/internal/v1/finance/reconciliation
    internal_reconciliation_runs: GET /api/internal/v1/finance/reconciliation/runs
supersedes: []
known_risks:
  - "Dark deployment active: automated recurring user usage deductions remain disabled until L4D-10-MB meter engine is introduced."
  - "Optimistic concurrency conflict (HTTP 409) requires retry if multiple concurrent operations target the same tenant simultaneously."
consumers:
  - L4D-10-MB
next_prompt_id: L4D-10-MB
```
<!-- HANDOFF:H-L4D-09-MB-v1:END -->

## 20. Принятие handoff H-L4D-10-MB-v1 (шаг 24 MenuBuilder)

Фиксация контроллером каскада принятого контракта `H-L4D-10-MB-v1` шага 24 (`MenuBuilder`) по результатам приёмки отчёта `MenuBuilder/docs/l4desk/handoffs/L4D-10-MB-report.md` и кандидата `MenuBuilder/docs/l4desk/handoffs/L4D-10-MB-candidate.md`.

Все проверки выполнены и подтверждены инструментально:
1. Коммит проверенной реализации: `2d567c2262e8b37022312427e2f77ba21b61f144` (ветка `l4desk/l4d-10-mb`). Коммит отчёта и кандидата: `d7fa495eacd8f80f72dfefa0dcc4d23b5a6b1be8`.
2. Sequence gate пройден: предшествующий обязательный handoff `H-L4D-09-MB-v1` (шаг 23), а также зависимые `H-L4D-03-MB-v1` и `H-L4D-02-IOT-v1` приняты в журнале со статусом `ACCEPTED`. Архитектурные разделы §2, §3, §5, §6, §7, §9, §10, §13, §14, §15, §16, §17 соблюдены.
3. Версионированные тарифы, индивидуальные биллинговые циклы и движок учёта потребления (metering engine) реализованы в `MenuBuilder`:
   - `FinTariffService`: снимки неизменяемых тарифов в `fin_tariff_versions` (базовый `v1.0`: 10000 коп./мес, 100 коп./час, 7200 с бесплатной суточной квоты) и выбор эффективного тарифа `get_effective_tariff(as_of)`.
   - `FinBillingCycleService`: индивидуальная фиксация якорной даты по первому платежу тенанта, правило `add_months` с сохранением времени и правилом последнего существующего дня месяца, расчёт границ циклов и льготного окна `starts_at < grace_deadline < ends_at` (3 календарных дня). Неизменность якоря при повторных платежах и событиях `device_online`.
   - `FinTerminalService`: постоянная льгота первого терминала (`ordinal ASC` среди `deleted_at IS NULL`) с передачей строго вперёд при удалении. Ежемесячный сбор 10000 копеек за платный терминал при первом `device_online` в цикле с дедупликацией по `(terminal_id, billing_cycle_id)`.
   - `FinMeteringService`: нарезка сессий по локальным полуночам тенанта (`Europe/London`, DST-safe), суточное округление часов `ceil(billable_seconds / 3600)`, универсальная формула округления тарифа `calculated = posted + discarded` (`0 <= discarded < 100`, кратность рублям). Неизменяемость проведённых суток и создание корректирующих проводок `kind='adjustment'` для late events со ссылкой `corrects_transaction_id`.
   - REST API эндпоинты (`/api/v1/finance/profile`, `/api/v1/finance/cycles`, `/api/v1/finance/tariffs/current`, `/api/v1/finance/usage`, `/api/v1/finance/monthly-charges`, `/api/internal/v1/finance/*`).
4. Побайтно проверены контрольные суммы SHA-256 для всех 13 артефактов реализации и отчёта, а также отдельного кандидатского файла `L4D-10-MB-candidate.md` (`776e89ed66ea293a0d9c55cb5847f059d7d8fcb136b1ee39722eaf868ab51285`) — совпадают на 100%.
5. Тестовый набор успешно пройден: 14 passed в `test_tariffs_and_metering.py`, полный набор `MenuBuilder/backend` 390 passed (0 failures, 0 errors), `shared` 65 passed, linters и static analysis (ruff, pyright) 0 errors/warnings.
6. Live smoke evidence на боевом сервере `87.242.100.34` подтверждён в Shadow Mode (разрешение тарифа -> правило add_months -> границы цикла -> расчёт метрик 120м/120м01с -> инварианты округления -> live сверка сабреджера matched).
7. Кандидат оформлен по стандарту `DETACHED_V1` в файле `MenuBuilder/docs/l4desk/handoffs/L4D-10-MB-candidate.md`.
8. Разрешён переход к следующему шагу каскада: `L4D-11-MB` (потребитель: `MenuBuilder`).

<!-- HANDOFF:H-L4D-10-MB-v1:BEGIN -->
```yaml
handoff_id: H-L4D-10-MB-v1
status: ACCEPTED
contract_kinds:
  - API
  - DEPLOYMENT
producer_prompt_id: L4D-10-MB
producer_scope_project: MenuBuilder
producer_report_path: MenuBuilder/docs/l4desk/handoffs/L4D-10-MB-report.md
producer_branch: l4desk/l4d-10-mb
producer_commit: 2d567c2262e8b37022312427e2f77ba21b61f144
report_commit: d7fa495eacd8f80f72dfefa0dcc4d23b5a6b1be8
accepted_at_utc: '2026-09-20T17:00:00Z'
contract_version: 1.0.0
schema_revision: '027'
artifact_version: 1.0.0
candidate_format: DETACHED_V1
detached_candidate_approved: true
candidate_path: MenuBuilder/docs/l4desk/handoffs/L4D-10-MB-candidate.md
artifact_paths:
  - MenuBuilder/backend/app/repositories/l4desk_repository.py
  - MenuBuilder/backend/app/routers/finance.py
  - MenuBuilder/backend/app/services/financial_core/__init__.py
  - MenuBuilder/backend/app/services/financial_core/cycles.py
  - MenuBuilder/backend/app/services/financial_core/exceptions.py
  - MenuBuilder/backend/app/services/financial_core/metering.py
  - MenuBuilder/backend/app/services/financial_core/schemas.py
  - MenuBuilder/backend/app/services/financial_core/tariffs.py
  - MenuBuilder/backend/app/services/financial_core/terminals.py
  - MenuBuilder/backend/app/services/financial_core/timezones.py
  - MenuBuilder/backend/tests/test_tariffs_and_metering.py
  - MenuBuilder/backend/tests/test_terminal_onboarding.py
  - MenuBuilder/docs/l4desk/handoffs/L4D-10-MB-report.md
artifact_sha256:
  - 78b98c9bd4d92c64e7e9161084cb2f226a796ee5bd06242c8feea6377d738085
  - 29e5e214ab32e270f3320d4cc22b32a537d3377a8b2e143dd59f543cf61eda4f
  - 73cbaa7f3784d4983331353ca11c394f96de2816736280a339d231f9f821c746
  - bc72f8e02692feba1d7294185b7511880d1fba324ba599694f0e35424189dcb8
  - 19fa02c95d11aa6c1b80eb99150652c73322835d14f6086c12713c862b6d9067
  - f4b05a9f574ea94b121400e1f493e19998d880b4b6306fc98b993af192ca4835
  - cf92379b04b71cd37d49d268a63796ad2b0504bb81f139caa9eb91c3f643123d
  - a09e6c426441e0d9dffa9ccf8389b35c36aaf5f5d1ed480f4c1b8ca87c2f8855
  - cdce9eec1abfcb91aa23b587dba7616a3daf65ce440c7dce9a412218dce49eaf
  - d0d8a075cecbc4f4cfe372e0f19340d593fa44f52abec095c48e73b7077e6935
  - 19164d31773a7bb624276d5c070f6b8bbc556b3e94e0f71c71428ddf84e639bf
  - 0ab63806bcc023406611f669f9424ff2bbad6993a7c0f62d025cc4b63db9fd8c
  - 8bca1e950bfcc9c873c07d3845e38118800586962e41f4777efcf5439bf627b7
compatibility:
  backward_compatible_with:
    - H-L4D-09-MB-v1
    - H-L4D-03-MB-v1
    - H-L4D-02-IOT-v1
  breaking_changes: false
  notes: Versioned immutable tariffs, individual anchor-based billing cycles with last existing day add_months rules, earliest terminal free privilege with forward-only deletion transfer, 10000 kopecks monthly charge on first online per cycle, and daily session metering split by local tenant midnights with rounding ceil(billable_sec/3600) and general tariff rounding invariants.
deployment_status: DEPLOYED
deployed_environment: production
feature_flags:
  l4desk_financial_core_enabled: true
  l4desk_billing_enabled: false
  l4desk_metering_enabled: true
contract_payload:
  tariffs:
    baseline_version: v1.0
    terminal_month_kopecks: 10000
    hourly_rate_kopecks: 100
    free_daily_seconds: 7200
  billing_cycles:
    anchor_rule: "First successful payment sets anchor; subsequent payments or device_online never shift anchor."
    month_addition: "add_months(anchor, n) with last existing calendar day rule and DST preservation."
    grace_window: "starts_at < grace_deadline < ends_at; grace_deadline = starts_at + 3 calendar days."
  terminal_privileges:
    free_terminal_rule: "Earliest existing terminal (min ordinal where deleted_at IS NULL) is free."
    deletion_transfer: "On deletion, privilege transfers forward only to next existing ordinal; closed periods not retroactively altered."
    monthly_charge: "Non-free terminal charged 10000 kopecks on first authenticated device_online in cycle with unique constraint (terminal_id, billing_cycle_id)."
  metering_engine:
    day_splitting: "Intervals partitioned at local tenant midnights into calendar days."
    concurrency_exclusion: "Console and video sessions never overlap."
    billable_seconds:
      free_terminal: "max(0, console + video - 7200)"
      paid_terminal: "console + video"
    paid_hours: "ceil(billable_seconds / 3600)"
    general_tariff_formula:
      calculated: "paid_hours * hourly_rate_kopecks"
      posted: "floor(calculated / 100) * 100"
      discarded: "calculated - posted"
      invariants: "calculated == posted + discarded; 0 <= discarded < 100; posted % 100 == 0; discarded not carried over"
    late_events_policy: "Posted daily usage rows are immutable; late events create adjustment ledger transaction with corrects_transaction_id."
  endpoints:
    tenant_profile: GET /api/v1/finance/profile
    tenant_cycles: GET /api/v1/finance/cycles
    tenant_current_tariff: GET /api/v1/finance/tariffs/current
    tenant_daily_usage: GET /api/v1/finance/usage
    tenant_monthly_charges: GET /api/v1/finance/monthly-charges
    internal_tariffs_list: GET /api/internal/v1/finance/tariffs
    internal_tariff_create: POST /api/internal/v1/finance/tariffs
    internal_metering_online: POST /api/internal/v1/finance/metering/online
    internal_metering_record_usage: POST /api/internal/v1/finance/metering/record-usage
    internal_metering_close_day: POST /api/internal/v1/finance/metering/close-day
supersedes: []
known_risks:
  - "Shadow mode active: automatic recurring user debits operate with dark posting until user billing cart UX (L4D-11-MB) is enabled."
  - "Historical late events spanning across closed days create delta adjustments that affect ledger balance without mutating past usage records."
consumers:
  - L4D-11-MB
next_prompt_id: L4D-11-MB
```
<!-- HANDOFF:H-L4D-10-MB-v1:END -->

## 21. Принятие handoff H-L4D-11-MB-v1 (шаг 25 MenuBuilder)

Фиксация контроллером каскада принятого контракта `H-L4D-11-MB-v1` шага 25 (`MenuBuilder`) по результатам приёмки отчёта `MenuBuilder/docs/l4desk/handoffs/L4D-11-MB-report.md` и кандидата `MenuBuilder/docs/l4desk/handoffs/L4D-11-MB-candidate.md`.

Все проверки выполнены и подтверждены инструментально:
1. Коммит проверенной реализации: `b6f793ad9880cf20489fe37366edc66af8229464` (ветка `l4desk/l4d-11-mb`). Коммит отчёта и кандидата: `221f36dbbe36c581c69a3a65deeb1378b90ab123`.
2. Sequence gate пройден: предшествующий обязательный handoff `H-L4D-10-MB-v1` (шаг 24), а также зависимый `H-L4D-09-MB-v1` (шаг 23) приняты в журнале со статусом `ACCEPTED`. Архитектурные разделы §2, §3, §5, §7, §9, §10, §13, §14, §15, §16, §17 соблюдены.
3. Интеграция с ЮKassa и ручные банковские платежи юрлиц реализованы в `MenuBuilder`:
   - `yookassa.py`: официальный контракт ЮKassa v3, протокол `YooKassaClientProtocol`, мок-клиент `MockYooKassaClient`, безопасный возврат `is_safe_return_url`, валидация доверенных IP-сетей ЮKassa `is_ip_trusted` (`185.71.76.0/27`, `185.71.77.0/27`, `77.75.153.0/25`, `77.75.156.11/32`, `77.75.156.35/32`, `77.75.154.128/25`, `2a02:5180::/32`).
   - `payments.py`: сервис пополнения баланса физических лиц, строгая валидация сумм (только целые рубли >= 1), идемпотентность по `operation_id`, авторитетная синхронизация только через `GET /payments/{id}` с блокировкой `with_for_update()`, двойные проверки безопасности (security mismatch checks), проводка сабреджера `Dr payment_clearing, Cr tenant_settlement` и атомарная фиксация даты якоря биллингового цикла `anchor_at` при первом успешном платеже.
   - `manual_payments.py`: неизменяемая регистрация банковских поручений юрлиц суперпользователем (`role 1 / is_superuser`), проведение транзакции сабреджера, сторнирование через обратную транзакцию `Dr tenant_settlement, Cr payment_clearing` (`FinReversalService`) с генерацией нового документа `STORNO-{doc_number}` и блокировкой повторного сторно.
   - `config.py`: вынесены все ключи фискализации (54-ФЗ) и шлюза ЮKassa без хардкода секретов.
   - REST API эндпоинты (`/api/v1/finance/payments`, `/api/v1/finance/payments/{id}`, `/api/v1/finance/payments/{id}/poll`, `/api/v1/finance/yookassa/webhook`, `/api/internal/v1/finance/manual-payments`, `/api/internal/v1/finance/manual-payments/{id}/storno`, `/api/internal/v1/finance/manual-payments`).
4. Побайтно проверены контрольные суммы SHA-256 для всех 10 артефактов реализации и отчёта, а также отдельного кандидатского файла `L4D-11-MB-candidate.md` (`a9ef5d36ed2fac6e59e8bf39a51da24b974d52d6649da02ceb05fa6a98ba3fe6`) — совпадают на 100%.
5. Тестовый набор успешно пройден: 10 passed в `test_yookassa_and_manual_payments.py`, полный набор `MenuBuilder/backend` 400 passed (0 failures, 0 errors), `shared` 65 passed, linters и static analysis (ruff, pyright) 0 errors/warnings, `MenuBuilder/frontend` build успешен.
6. Live smoke evidence на боевом сервере `87.242.100.34` подтверждён (проверка сетевых гардов, контракт ЮKassa v3, реальная сверка сабреджера PostgreSQL `status=matched, mismatches=0, diff=0`).
7. Кандидат оформлен по стандарту `DETACHED_V1` в файле `MenuBuilder/docs/l4desk/handoffs/L4D-11-MB-candidate.md`.
8. Разрешён переход к следующему шагу каскада: `L4D-12-MB` (потребитель: `MenuBuilder`).

<!-- HANDOFF:H-L4D-11-MB-v1:BEGIN -->
```yaml
handoff_id: H-L4D-11-MB-v1
status: ACCEPTED
contract_kinds:
  - API
  - DEPLOYMENT
producer_prompt_id: L4D-11-MB
producer_scope_project: MenuBuilder
producer_report_path: MenuBuilder/docs/l4desk/handoffs/L4D-11-MB-report.md
producer_branch: l4desk/l4d-11-mb
producer_commit: b6f793ad9880cf20489fe37366edc66af8229464
report_commit: 221f36dbbe36c581c69a3a65deeb1378b90ab123
accepted_at_utc: '2026-09-20T16:35:00Z'
contract_version: 1.0.0
schema_revision: '027'
artifact_version: 1.0.0
candidate_format: DETACHED_V1
detached_candidate_approved: true
candidate_path: MenuBuilder/docs/l4desk/handoffs/L4D-11-MB-candidate.md
artifact_paths:
  - MenuBuilder/backend/app/config.py
  - MenuBuilder/backend/app/repositories/l4desk_repository.py
  - MenuBuilder/backend/app/routers/finance.py
  - MenuBuilder/backend/app/services/financial_core/__init__.py
  - MenuBuilder/backend/app/services/financial_core/schemas.py
  - MenuBuilder/backend/app/services/financial_core/payments.py
  - MenuBuilder/backend/app/services/financial_core/manual_payments.py
  - MenuBuilder/backend/app/services/financial_core/yookassa.py
  - MenuBuilder/backend/tests/test_yookassa_and_manual_payments.py
  - MenuBuilder/docs/l4desk/handoffs/L4D-11-MB-report.md
artifact_sha256:
  - 8944bbd842e287f55863172cbf92afcb65a9f26f7579c8b25edecaecc9b67498
  - b8670d8abb462ae2a0a61bf6e782e82482403bf683ddc31345cc3c369e7d5714
  - afeb55ca680d92a754923a575bbc3ee7eeb509322da9ecfebb8b957e7efadb45
  - 6693513b08f168e6cb3a21f4bce6ec06773a59e3970654c2994ef78446907ae7
  - 86c06f08d3f556925d3d8a9ae44d1a514a0a27f948e4af28b8a43605aaa53576
  - 6abbe80dbc69d60e0c79abc08391a3bb0f3df13cc8a36a4c86af36394f65c401
  - dd68c81271233654ca31a64cf57a7a559718b264225191157475f559042a1950
  - aac015319eb62683c884c2a52933b26f41b49792ebc72c1272e78823dba10713
  - 655b60e3206ad5ac039f3fe794afb83254327876bf5682eb102b47e20c97098e
  - f61b7a366875c07c908161f04e65f6431197cb44f9bd1e5194fe6111be50decf
compatibility:
  backward_compatible_with:
    - H-L4D-10-MB-v1
    - H-L4D-09-MB-v1
  breaking_changes: false
  notes: YooKassa top-up flow for individuals, immutable B2B manual payment registration by superuser, double-entry reversal/storno mechanics, and atomic cycle anchor fixation on first successful payment.
deployment_status: DEPLOYED
deployed_environment: production
feature_flags:
  l4desk_financial_core_enabled: true
  yookassa_enabled: false
  yookassa_ip_filter_enabled: false
  yookassa_receipt_enabled: true
contract_payload:
  payment_states:
    - pending
    - waiting_for_capture
    - succeeded
    - canceled
  idempotency:
    yookassa: "Idempotence-Key header / operation_id on payment creation and replay-safe lookup"
    webhook_and_poll: "Server authoritative GET /payments/{id} verification before ledger posting; duplicate webhook or poll is a safe no-op"
  ledger_posting:
    yookassa_succeeded: "Dr payment_clearing, Cr tenant_settlement"
    manual_payment: "Dr payment_clearing, Cr tenant_settlement"
    manual_storno: "Dr tenant_settlement, Cr payment_clearing (kind=reversal, corrects_transaction_id)"
  cycle_anchor:
    rule: "First successful payment (YooKassa or manual) fixes immutable cycle anchor_at; subsequent payments never shift existing anchor"
  manual_payments:
    role_required: "Superuser only (role 1 / is_superuser)"
    immutability: "Posted manual payment records are append-only; corrections executed strictly via storno + new document"
  fiscal_configuration:
    config_keys:
      - YOOKASSA_ENABLED
      - YOOKASSA_SHOP_ID
      - YOOKASSA_SECRET_KEY
      - YOOKASSA_API_URL
      - YOOKASSA_WEBHOOK_SECRET
      - YOOKASSA_IP_FILTER_ENABLED
      - YOOKASSA_TRUSTED_IPS_RAW
      - YOOKASSA_RETURN_URL_BASE
      - YOOKASSA_RECEIPT_ENABLED
      - YOOKASSA_TAX_SYSTEM_CODE
      - YOOKASSA_VAT_CODE
      - YOOKASSA_PAYMENT_SUBJECT
      - YOOKASSA_PAYMENT_MODE
      - YOOKASSA_ITEM_DESCRIPTION
      - YOOKASSA_REQUEST_TIMEOUT_SEC
  endpoints:
    payment_create: POST /api/v1/finance/payments
    payment_get: GET /api/v1/finance/payments/{payment_id}
    payment_list: GET /api/v1/finance/payments
    payment_poll: POST /api/v1/finance/payments/{payment_id}/poll
    yookassa_webhook: POST /api/v1/finance/yookassa/webhook
    manual_payment_create: POST /api/internal/v1/finance/manual-payments
    manual_payment_storno: POST /api/internal/v1/finance/manual-payments/{manual_payment_id}/storno
    manual_payment_list: GET /api/internal/v1/finance/manual-payments
    manual_payment_get: GET /api/internal/v1/finance/manual-payments/{manual_payment_id}
supersedes: []
known_risks:
  - "Production YooKassa credentials default to disabled/sandbox until production merchant keys are injected into .env."
consumers:
  - L4D-12-MB
next_prompt_id: L4D-12-MB
```
<!-- HANDOFF:H-L4D-11-MB-v1:END -->

## 22. Принятие handoff H-L4D-12-MB-v1 (шаг 26 MenuBuilder)

Фиксация контроллером каскада принятого контракта `H-L4D-12-MB-v1` шага 26 (`MenuBuilder`) по результатам приёмки отчёта `MenuBuilder/docs/l4desk/handoffs/L4D-12-MB-report.md` и кандидата `MenuBuilder/docs/l4desk/handoffs/L4D-12-MB-candidate.md`.

Все проверки выполнены и подтверждены инструментально:
1. Коммит проверенной реализации: `95ba8b7915c1d9e34e76169706b5aa862c2e9954` (ветка `l4desk/l4d-12-mb`). Коммит отчёта и кандидата: `385155dc394f2bd4479f1545695d61a03b485b9b`.
2. Sequence gate пройден: предшествующие обязательные handoff `H-L4D-11-MB-v1` (шаг 25), `H-L4D-10-MB-v1` (шаг 24), `H-L4D-07-IOT-v1` (шаг 20) и `H-L4D-08B-MB-v1` (шаг 22) приняты в журнале со статусом `ACCEPTED`. Архитектурные разделы §2, §3, §5, §6, §8, §9, §10, §13, §14, §15, §16, §17 соблюдены.
3. Коммерческий механизм entitlement, cycle-bound grace, Stop Outbox с повторными попытками и идемпотентные email-уведомления реализованы в `MenuBuilder`:
   - `entitlement.py`: `FinEntitlementService` авторитетно вычисляет статус тенанта (`free`, `active`, `grace`, `blocked`), суточный пул бесплатной квоты 120 минут для первого терминала (`FinTerminalService.is_terminal_free`), немедленную блокировку вторичных терминалов на бесплатном тарифе (`unpaid_secondary_terminal`), завершение сессий при исчерпании квоты при нулевом балансе (`free_quota_exceeded`), платное продолжение при балансе > 0, строгую привязку grace к календарной границе цикла (`cycle_start + 3 days`) без смещения при событиях онлайн, и иммунитет якоря `anchor_at` при поздних платежах.
   - `notifications.py`: `FinNotificationService` обеспечивает строго идемпотентное планирование и диспетчеризацию уведомлений по ключу `(tenant_id, billing_cycle_id, notification_type)` для стадий `-7d`, `-3d`, `-1d`, `grace`, `blocked`, устойчивость к сбоям почтового провайдера с лимитом попыток и audit events.
   - `stop_outbox.py`: `FinStopOutboxService` обеспечивает координированную остановку активных сессий заблокированных тенантов (немедленный teardown WebRTC для видео, ожидание команды / таймаут по контракту `H-L4D-07-IOT-v1` для консоли) с сохранением состояния `stop_requested` в БД и надежным повтором через `process_stop_outbox`.
   - `worker.py`: `FinEntitlementWorker` выполняет периодический аудит всех активных тенантов, проверку границ циклов, генерацию уведомлений, перевод сессий в Stop Outbox и их обработку.
   - `remote_session_policy.py`: интеграция `L4DeskEntitlementPolicy` с поддержкой режимов shadow (по умолчанию) и enforced.
   - `finance.py`: REST API эндпоинты (`/api/v1/finance/entitlement`, `/api/v1/finance/notifications`, `/api/internal/v1/finance/entitlement/{tenant_id}`, `/api/internal/v1/finance/entitlement/worker/tick`, `/api/internal/v1/finance/stop-outbox/process`, `/api/internal/v1/finance/notifications`).
4. Побайтно проверены контрольные суммы SHA-256 для всех 14 артефактов реализации и отчёта, а также отдельного кандидатского файла `L4D-12-MB-candidate.md` (`684730abe4b4dae83e73dafd353c60acec7b2841f392e25c9c6d08a3056f91d4`) — совпадают на 100%.
5. Тестовый набор успешно пройден: 11 passed в `test_l4d_12_entitlement_grace_and_notifications.py`, полный набор `MenuBuilder/backend` 411 passed (0 failures, 0 errors), линтеры и статический анализ (ruff, pyright) 0 errors/warnings.
6. Live smoke evidence на боевом сервере `87.242.100.34` подтверждён (проверка такта воркера entitlement, аудит состояния Stop Outbox и реестра доставок уведомлений).
7. Кандидат оформлен по стандарту `DETACHED_V1` в файле `MenuBuilder/docs/l4desk/handoffs/L4D-12-MB-candidate.md`.
8. Разрешён переход к следующему шагу каскада: `L4D-13-MB` (потребитель: `MenuBuilder`).

<!-- HANDOFF:H-L4D-12-MB-v1:BEGIN -->
```yaml
handoff_id: H-L4D-12-MB-v1
status: ACCEPTED
contract_kinds:
  - API
  - DEPLOYMENT
producer_prompt_id: L4D-12-MB
producer_scope_project: MenuBuilder
producer_report_path: MenuBuilder/docs/l4desk/handoffs/L4D-12-MB-report.md
producer_branch: l4desk/l4d-12-mb
producer_commit: 95ba8b7915c1d9e34e76169706b5aa862c2e9954
report_commit: 385155dc394f2bd4479f1545695d61a03b485b9b
accepted_at_utc: '2026-09-20T17:45:00Z'
contract_version: 1.0.0
schema_revision: '027'
artifact_version: 1.0.0
candidate_format: DETACHED_V1
detached_candidate_approved: true
candidate_path: MenuBuilder/docs/l4desk/handoffs/L4D-12-MB-candidate.md
artifact_paths:
  - MenuBuilder/backend/app/config.py
  - MenuBuilder/backend/app/main.py
  - MenuBuilder/backend/app/repositories/l4desk_repository.py
  - MenuBuilder/backend/app/routers/finance.py
  - MenuBuilder/backend/app/routers/video_control.py
  - MenuBuilder/backend/app/services/financial_core/__init__.py
  - MenuBuilder/backend/app/services/financial_core/entitlement.py
  - MenuBuilder/backend/app/services/financial_core/notifications.py
  - MenuBuilder/backend/app/services/financial_core/schemas.py
  - MenuBuilder/backend/app/services/financial_core/stop_outbox.py
  - MenuBuilder/backend/app/services/financial_core/worker.py
  - MenuBuilder/backend/app/services/remote_session_policy.py
  - MenuBuilder/backend/tests/test_l4d_12_entitlement_grace_and_notifications.py
  - MenuBuilder/docs/l4desk/handoffs/L4D-12-MB-report.md
artifact_sha256:
  - 71ea749442cb9c791863fc15e86633d49c3d36d87064ef9cc677b6254686f018
  - a57b8afddfbaac01772f3f05dbae4b7892a864bcf24283eddb3ce1cad1e3f091
  - d6b7c1421174016861b75375483463b74eb24336686c9f4da76922d927ec38b0
  - 5b0bf751e3149681624ae213cc2ccd4747f55093c76cf1a3ab5c8770731938b1
  - 08af1e5fcd9f7e24ac4aba869dcc84eccfb16b304ff2026f89495d1785d2e7c1
  - 1e7d2698992f0ecbaf07698279d880731b53bb10372e8096bb89e8fd831e03a1
  - c8928efcd52530c71975bbe9b009e5841b8026d0222ee9d1af114d2003976f57
  - fd414844d5f26a86607057e947f8a87aa54904deee81f6262f5b3266f8e6759b
  - 8438eda2f13c5cc9729a3398e15390a2453f2cdc55e992f1b3b20db12401b468
  - 45119132562a10f1eac9e017c54600c751ff015e67806e1c23b73a6989c127d4
  - d4e485c04a30af8471fb095476719dcd15169de91945ed232a696acb186e13d3
  - 1778f36290937ef239415a55d8581ca812c3e6517b7e6186a90ab6100fa9574e
  - 560ae3a021a1ac0943d02f0acfac8091cd14adae75ad175dac0f4ba9d54fbfbd
  - a04349eff17353edabd0b24dc8612fcd996caeb17e78c87488fd15158aee0873
compatibility:
  backward_compatible_with:
    - H-L4D-11-MB-v1
    - H-L4D-10-MB-v1
    - H-L4D-08B-MB-v1
    - H-L4D-07-IOT-v1
  breaking_changes: false
  notes: Commercial start/continue/stop decisioning, cycle-bound grace state machine, Stop Outbox retry pattern, and idempotent email notifications for L4Desk SaaS.
deployment_status: DEPLOYED
deployed_environment: production
feature_flags:
  l4desk_policy_enforcement_enabled: false
  l4desk_policy_shadow_mode: true
  l4desk_entitlement_worker_enabled: false
  l4desk_email_notifications_enabled: true
contract_payload:
  entitlement_states:
    - free
    - active
    - grace
    - blocked
  reason_codes:
    - entitlement_blocked
    - free_quota_exceeded
    - unpaid_secondary_terminal
    - payment_required
    - no_terminals
  notification_types:
    - cycle_minus_7
    - cycle_minus_3
    - cycle_minus_1
    - grace
    - blocked
  normative_rules:
    free_tier: "Single free terminal with 120 min/local day pooled quota before first payment; secondary terminals blocked; continuation allowed if balance > 0"
    cycle_bound_grace: "Grace is active only when balance < 0 and now < cycle_start + 3 days in tenant timezone; always bound to cycle boundary, never to online/charge events"
    late_payment: "Pays off period and preserves immutable anchor_at; balance >= 0 immediately unblocks"
    session_termination: "Video teardown executed immediately; console stops new commands, waits for running command or bounded timeout, then closes"
    stop_outbox: "Pending stops tracked in stop_requested state and retried automatically until confirmed by IoT provider"
    notification_idempotency: "Unique by (tenant_id, billing_cycle_id, notification_type); retries do not produce duplicate records or emails"
  endpoints:
    tenant_entitlement: GET /api/v1/finance/entitlement
    tenant_notifications: GET /api/v1/finance/notifications
    internal_entitlement: GET /api/internal/v1/finance/entitlement/{tenant_id}
    internal_worker_tick: POST /api/internal/v1/finance/entitlement/worker/tick
    internal_stop_outbox_process: POST /api/internal/v1/finance/stop-outbox/process
    internal_notifications_list: GET /api/internal/v1/finance/notifications
supersedes: []
known_risks:
  - "In production, policy enforcement defaults to shadow mode (l4desk_policy_enforcement_enabled=false) to ensure backward compatibility during rollout."
consumers:
  - L4D-13-MB
next_prompt_id: L4D-13-MB
```
<!-- HANDOFF:H-L4D-12-MB-v1:END -->

## 23. Принятие handoff H-L4D-13-MB-v1 (шаг 27 MenuBuilder)

Фиксация контроллером каскада принятого контракта `H-L4D-13-MB-v1` шага 27 (`MenuBuilder`) по результатам приёмки отчёта `MenuBuilder/docs/l4desk/handoffs/L4D-13-MB-report.md` и кандидата `MenuBuilder/docs/l4desk/handoffs/L4D-13-MB-candidate.md`.

Все проверки выполнены и подтверждены инструментально:
1. Коммит проверенной реализации: `f5017615a8a84eee318a78b54a992ceb45f91edc` (ветка `l4desk/l4d-13-mb`). Коммит отчёта, кандидата и конфигурации прокси: `4a6e124d870e06a2001a83464af2beb0123639b5`.
2. Sequence gate пройден: предшествующие обязательные handoff `H-L4D-12-MB-v1` (шаг 26), `H-L4D-11-MB-v1` (шаг 25), `H-L4D-08B-MB-v1` (шаг 22) и `H-L4D-06C-MB-v1` (шаг 19) приняты в журнале со статусом `ACCEPTED`. Дубликаты отсутствуют.
3. В единой SPA `MenuBuilder` без дублирования функционала и ломки классического профиля реализованы:
   - Единый механизм профилей навигации (`navigationProfile.ts`): автоматическое назначение L4Desk для пользователей роли 5 (`l4desk_owner`), переключение через URL/хедер для администраторов и смоук-тестов, сохранение классического интерфейса `PlaterraMonitoring`.
   - 5 канонических разделов L4Desk: «Видеонаблюдение» (`/video`), «Настройки» (`/settings`), «Консоль» (`/console` — прямой реюз `DeviceConsoleTab`), «MCP» (`/mcp` — промо протокола и запись в waitlist), «Лицензии» (`/licenses` — баланс, продление, квота 120 мин, проводки double-entry, платное продолжение при балансе > 0).
   - Мастер онбординга (`OnboardingWizardModal`): регистрация ПК -> PIN и ссылка на Агент -> поллинг 4 статусов готовности (реестр, сертификат, IoT, online) -> запуск первой сессии.
   - Структурированные отказы (`RefusalReasonCard`): `session_conflict`, `offline`, `provisioning_pending`, `free_quota_exhausted`, `grace_blocked`.
   - Proxy-конфигурация Nginx (`nginx-configs/port_3000.conf`) для эндпоинтов `/api/v1/finance/` и `/api/v1/mcp/`.
4. Побайтно проверены контрольные суммы SHA-256 для всех 23 артефактов и отдельного файла кандидата `L4D-13-MB-candidate.md` (`05bba42b6cc147cf7d91b1a06347ea4d4d53c19e6edb09a393bf35d84e16ec4a`) — полное совпадение на 100%.
5. Тестовый набор успешно пройден:
   - Frontend: 9 сьютов, 47 тестов vitest (`47 passed in 22.13s`).
   - Production bundle build: `tsc -b && vite build` выполнен успешно (размер раздельных чанков 4-70 КБ).
   - Backend: 3 passed в `test_mcp_waitlist_and_role5.py`, 43 смежных теста пройдены.
   - Статический анализ и форматирование: `ruff check` — all passed, `ruff format` — clean, `pyright` — 0 errors, 0 warnings.
6. Live smoke evidence на боевом сервере `87.242.100.34`:
   - Nginx на порту 3000 (`dev.leo4.ru`) отвечает `HTTP/1.1 200 OK`.
   - Ассеты фронтенда (`ConsolePage-CAtA6WkK.js`, `LicensesPage-DSNFczN-.js`, `McpPromoPage-BCfHRlJ1.js`) развернуты и отдаются корректно.
   - Контейнеры `menubuilder-backend` и `nginx-default` работают штатно.
7. Кандидат оформлен по стандарту `DETACHED_V1` в файле `MenuBuilder/docs/l4desk/handoffs/L4D-13-MB-candidate.md`.
8. Разрешён переход к следующему шагу каскада: `L4D-14-MB` (потребитель: `MenuBuilder`).

<!-- HANDOFF:H-L4D-13-MB-v1:BEGIN -->
```yaml
handoff_id: H-L4D-13-MB-v1
status: ACCEPTED
contract_kinds:
  - API
  - DEPLOYMENT
producer_prompt_id: L4D-13-MB
producer_scope_project: MenuBuilder
producer_report_path: MenuBuilder/docs/l4desk/handoffs/L4D-13-MB-report.md
producer_branch: l4desk/l4d-13-mb
producer_commit: f5017615a8a84eee318a78b54a992ceb45f91edc
report_commit: 4a6e124d870e06a2001a83464af2beb0123639b5
accepted_at_utc: '2026-09-20T19:45:00Z'
contract_version: 1.0.0
schema_revision: '027'
artifact_version: 1.0.0
candidate_format: DETACHED_V1
detached_candidate_approved: true
candidate_path: MenuBuilder/docs/l4desk/handoffs/L4D-13-MB-candidate.md
artifact_paths:
  - MenuBuilder/backend/app/main.py
  - MenuBuilder/backend/app/routers/auth.py
  - MenuBuilder/backend/app/routers/mcp_waitlist.py
  - MenuBuilder/backend/tests/test_mcp_waitlist_and_role5.py
  - MenuBuilder/frontend/src/App.tsx
  - MenuBuilder/frontend/src/api/finance.ts
  - MenuBuilder/frontend/src/api/mcpWaitlist.ts
  - MenuBuilder/frontend/src/components/OnboardingWizardModal.tsx
  - MenuBuilder/frontend/src/components/RefusalReasonCard.tsx
  - MenuBuilder/frontend/src/routes/console/ConsolePage.tsx
  - MenuBuilder/frontend/src/routes/devices/DeviceConsoleTab.tsx
  - MenuBuilder/frontend/src/routes/layout.tsx
  - MenuBuilder/frontend/src/routes/licenses/LicensesPage.tsx
  - MenuBuilder/frontend/src/routes/mcp/McpPromoPage.tsx
  - MenuBuilder/frontend/src/routes/settings/TerminalsSettingsPage.tsx
  - MenuBuilder/frontend/src/routes/video-surveillance.tsx
  - MenuBuilder/frontend/src/tests/l4desk-accessibility-responsive.test.ts
  - MenuBuilder/frontend/src/tests/l4desk-licenses-mcp.test.ts
  - MenuBuilder/frontend/src/tests/l4desk-profile-navigation.test.ts
  - MenuBuilder/frontend/src/tests/l4desk-refusal-reasons.test.ts
  - MenuBuilder/frontend/src/utils/navigationProfile.ts
  - nginx-configs/port_3000.conf
  - MenuBuilder/docs/l4desk/handoffs/L4D-13-MB-report.md
artifact_sha256:
  - 296e0ef944a9e1abcda254a28f19a77b4741e97b6c82b8a01c1379b1313cad06
  - 0857ae0b33a4d591e319f97f2e2ced8a779b168ad64363b6a864d9e3f75e51a1
  - 6f2bfdf626572eb4cfccbe12c7424bb426aefea365f447ded5e0876174a43095
  - e486e24d5d95eec1cc2c1037a4aae342b877216c96d0b6f0385749420a9f96fb
  - 04856fceb7af3951c448516fb78aad912dd155ca7247fb6d99632139ada9575d
  - aaafeecbe1d0157ce0e06b2aa211a0ae87676592ef625f1f3b8c7cddde296c54
  - d1201e858e13306e8d93d70611ce1b9fbaaad9fa0b01793bee988a6ae46e872b
  - d6497e7df398b0c755071099fa86a45e29fdebe594d61db0e2259f62416b6275
  - d63dee75b4eea4e9c5ef1311a3ec767431d1010edfc410ab9858132a1cfee12c
  - 4167364fa0454f01aaf6fb5a4059a885be757fe56a4e59e392d6eb9f19606516
  - f7ae07658d3024100708242bb399ea87aaa97c63cffa5f2e9f274d677694a797
  - a858ca421328747205c73a759cfb13088f317523f46d5524ac994b89b3a065ee
  - 13da06cba68c032efd5372f6881668487d6feeb0eec3369139589b6724725541
  - 928e63d6b713c9db4c98f615a51a7239d11db96fc581afa8d9fb8ff6ce7ecca5
  - 4d686b27bf504011da0df285383ff45114e19ebd0523a1526f77af65b8cbcb67
  - 376b6a5884185a2ab6d912b9a8be8c4fee0db9d3789ef8b2163c4e12e7b9475d
  - 2515d12f032e3e4c31e92b69232a4a62b21a474335d1c00b8f85e39a90f8debb
  - 4232e6d90806b8413f465de1682c0422120e0e3f8440c33a1aa887827c21d3fc
  - 80b11223a85e23fe1456914a8280b098a48a495a1a7ec4b7067b1ca71353035e
  - 95bc280c549c10e7354932bcfff576c660f0a686de26fe9b4cb098a542efa506
  - bbbf70d9eed9d8e2c2e84960a2195f301a1ba7e1ec0d76662ae8452aee4f2f3d
  - e76037bdee1d28411ff843d6ee8dc3e0e8dff3c95382e2e972566afda1f6ef0d
  - b9027374de01a8e01b2c56e7cc30467747fbc35a8aae646ac6a6eadbe7886c1b
compatibility:
  backward_compatible_with:
    - H-L4D-12-MB-v1
    - H-L4D-06C-MB-v1
    - H-L4D-08B-MB-v1
  breaking_changes: false
  notes: "Unified L4Desk navigation profile and onboarding/licenses UX in single SPA without duplicating console/video components. Classic MenuBuilder profile remains functional and untouched for existing users."
deployment_status: DEPLOYED
deployed_environment: production
feature_flags:
  l4desk_navigation_profile_enabled: true
  l4desk_ui_enabled: true
contract_payload:
  navigation_sections:
    - video: /video
    - settings: /settings
    - console: /console
    - mcp: /mcp
    - licenses: /licenses
  rejection_reasons:
    - session_conflict
    - offline
    - provisioning_pending
    - free_quota_exhausted
    - grace_blocked
  onboarding_wizard_steps:
    - step_0: create_terminal
    - step_1: pin_and_agent_download
    - step_2: readiness_online_polling
    - step_3: launch_single_session
  mcp_endpoints:
    join_waitlist: POST /api/v1/mcp/waitlist
    waitlist_status: GET /api/v1/mcp/waitlist/status
supersedes: []
known_risks: []
consumers:
  - L4D-14-MB
next_prompt_id: L4D-14-MB
```
<!-- HANDOFF:H-L4D-13-MB-v1:END -->

## 24. Принятие handoff H-L4D-14-MB-v1 (шаг 28 MenuBuilder)

Фиксация контроллером каскада принятого контракта `H-L4D-14-MB-v1` шага 28 (`MenuBuilder`) по результатам приёмки отчёта `MenuBuilder/docs/l4desk/handoffs/L4D-14-MB-report.md` и кандидата `MenuBuilder/docs/l4desk/handoffs/L4D-14-MB-candidate.md`.

Все проверки выполнены и подтверждены инструментально:
1. Коммит проверенной реализации: `877dc00ac6e5131c65375c5494659d36ff31822e` (ветка `l4desk/l4d-14-mb`, коммит ветки в origin: `40eb0fc18be3dc299dd5cacd1ae283f253b20472`).
2. Sequence gate пройден: предшествующий обязательный handoff `H-L4D-13-MB-v1` (шаг 27 MenuBuilder) принят в журнале со статусом `ACCEPTED`. Дубликаты отсутствуют.
3. В `MenuBuilder` полностью реализован superuser Хаб и всесторонний аудит финансовой сверки `source facts → usage → ledger → balance`:
   - Архитектурная изоляция (Gates): Хаб обращается исключительно к локальным моделям `MenuBuilder` через SQLAlchemy 2.0; сетевые запросы к чужим БД и внутренним очередям IoT/RabbitMQ исключены.
   - 5 канонических вкладок Хаба (`AdminHubPage`): `registrations` (реестр саморегистраций с таймзонами и первой оплатой), `terminals` (реестр терминалов, 1-й бесплатный / платные, provisioning/PIN/cert/online), `sessions` (объединённое управление сессиями video/console и суточный регистр потребления `FinUsageDaily`), `finance` (коммерческий обзор, B2C/B2B платежи, запуск и история сверки), `notifications` (статусы доставки писем и системный аудит-лог).
   - Система фильтрации: фильтры по `tenant_id`, `terminal_id/sn`, `period`, `user/email`, `session_type`, статусу подписки, типу терминала, источнику платежа, а также селектор `only_errors / only_unreconciled` на каждой вкладке.
   - Сквозной аудит (Correlation Drill-Down): автоматическое построение графа фактов `registration → terminal → pin_provisioning → online_session → usage → ledger_payment` со строгим правилом отсутствующих звеньев (`present: false, mismatch: true, fact: null`, без дорисовывания фактов).
   - Всесторонние инварианты финансовой сверки (`FinReconciliationService`): `debit = credit`, `projection rebuild`, `calculated = posted + discarded` (`0 <= discarded < 100`), `posted % 100 = 0`, `source hash / event coverage`, `unique monthly charge / payment posting`.
   - Защита ручных операций и сторно: создание банковского платежа и сторнирование требуют подтверждения секретным кодом `"11"`, валидируются бэкендом и фиксируются в `L4DeskAuditEvent`.
4. Побайтно проверены контрольные суммы SHA-256 для всех 12 артефактов и отдельного файла кандидата `L4D-14-MB-candidate.md` (`3f929ee9f9f61064e2f69d19d0210107521832508ab254491d4728f1b999a055`) — полное совпадение на 100%.
5. Тестовый набор успешно пройден:
   - Backend: 4 комплексных теста в `test_hub_and_reconciliation.py` пройдены, общий прогон финансовых тестов 59 passed in 3.66s.
   - Статический анализ и форматирование: `ruff check` — all passed, `ruff format` — clean (124 files), `pyright` — 0 errors, 0 warnings.
   - Frontend: 10 тест-файлов, 51 passed в vitest (включая `l4desk-hub-and-reconciliation.test.ts`).
   - Production bundle build: `tsc -b && vite build` выполнен успешно (exit code 0), сгенерирован чанк `AdminHubPage-C_UpKLXQ.js`.
6. Live smoke evidence на боевом сервере `87.242.100.34`:
   - Pre-flight проверки хоста: RAM free > 2.2 GiB, Disk 61%, Load average 0.15.
   - Фронтенд `dist/*` и бэкенд `app/*` доставлены, контейнер `menubuilder-backend` перезапущен, схема БД 027 подтверждена (23 таблицы).
   - Smoke-запросы к эндпоинтам `/api/internal/v1/hub/terminals` (200 OK), `/api/internal/v1/hub/correlation-drilldown` (200 OK), `/api/internal/v1/hub/reconciliation/run` (200 OK, status `matched`), ручной платёж без кода 11 отклоняется (400 Bad Request).
7. Кандидат оформлен по стандарту `DETACHED_V1` в файле `MenuBuilder/docs/l4desk/handoffs/L4D-14-MB-candidate.md`.
8. Разрешён переход к следующему шагу каскада: `L4D-15A-DOCS` (потребитель: `l4desk-service`).

<!-- HANDOFF:H-L4D-14-MB-v1:BEGIN -->
```yaml
handoff_id: H-L4D-14-MB-v1
status: ACCEPTED
contract_kinds:
  - API
  - DEPLOYMENT
producer_prompt_id: L4D-14-MB
producer_scope_project: MenuBuilder
producer_report_path: MenuBuilder/docs/l4desk/handoffs/L4D-14-MB-report.md
producer_branch: l4desk/l4d-14-mb
producer_commit: 877dc00ac6e5131c65375c5494659d36ff31822e
report_commit: 877dc00ac6e5131c65375c5494659d36ff31822e
accepted_at_utc: '2026-09-20T20:55:00Z'
contract_version: 1.0.0
schema_revision: '027'
artifact_version: 1.0.0
candidate_format: DETACHED_V1
detached_candidate_approved: true
candidate_path: MenuBuilder/docs/l4desk/handoffs/L4D-14-MB-candidate.md
artifact_paths:
  - MenuBuilder/backend/app/main.py
  - MenuBuilder/backend/app/routers/hub.py
  - MenuBuilder/backend/app/services/financial_core/hub_schemas.py
  - MenuBuilder/backend/app/services/financial_core/hub_service.py
  - MenuBuilder/backend/app/services/financial_core/reconciliation.py
  - MenuBuilder/backend/tests/test_hub_and_reconciliation.py
  - MenuBuilder/frontend/src/App.tsx
  - MenuBuilder/frontend/src/api/hub.ts
  - MenuBuilder/frontend/src/pages/AdminHubPage.tsx
  - MenuBuilder/frontend/src/routes/admin-layout.tsx
  - MenuBuilder/frontend/src/tests/l4desk-hub-and-reconciliation.test.ts
  - MenuBuilder/docs/l4desk/handoffs/L4D-14-MB-report.md
artifact_sha256:
  - a372b7571162fb7b366b7e52f15304ef7b9f8f4a0b0445d83f3f96360717125b
  - 1b83e283247f80841bc663e6f982e602d5171d5f9648ee46d53bce2525cbdc49
  - 0e4124362c89f0cf6e1d515c0b6f892b02735721e2b9fa883920650911485e2c
  - 3d3526ea19b098e0092fff6b1f874fdd666c3c7df64ba6d991c0aa8e8a5aa204
  - e2ffd67cd9d985e6be7c218c500b1e39c3cbbe1498769231f9733b866e79f364
  - 49509bf568d7c390c122892584b3cdec2cb6a426140d8e74dd0fbf85f9c20100
  - 14903c710fd7d6d52f47b16ab3f93cbb2a2f1218a70a22bd6d05f9e8ec9b16a6
  - 140d3b74c37b34611f8e68d490e5c47bf263128b1e20f0fdfae74d1b2594dd20
  - a751bc1619d5631ba32be823e2d17f1fe7470597ef11865f66edcf284b06760b
  - f73171adb60f790b556951bb955d40e9a865c51a1d4119753d1fefee8fbc4fab
  - 50deda9a76ee33d48eed55c33b4c5e8f5178d4c5c41fd781f7acd63a7cc08a3c
  - 43a419248253c609a11c0e5eaeedcef506924720f3969148054e5c1896608098
compatibility:
  backward_compatible_with:
    - H-L4D-13-MB-v1
    - H-L4D-12-MB-v1
    - H-L4D-11-MB-v1
    - H-L4D-10-MB-v1
    - H-L4D-09-MB-v1
  breaking_changes: false
  notes: "Superuser Hub and comprehensive financial subledger reconciliation contract across source facts -> usage -> ledger -> balance. End-to-end correlation drilldown with strict missing fact mismatch policy and safe code 11 manual payment / storno confirmation."
deployment_status: DEPLOYED
deployed_environment: production
feature_flags:
  l4desk_hub_enabled: true
  l4desk_financial_reconciliation_enabled: true
contract_payload:
  hub_endpoints:
    registrations: GET /api/v1/admin/hub/registrations
    terminals: GET /api/v1/admin/hub/terminals
    sessions: GET /api/v1/admin/hub/sessions
    usage: GET /api/v1/admin/hub/usage
    finance_overview: GET /api/v1/admin/hub/finance/overview
    payments: GET /api/v1/admin/hub/finance/payments
    notifications: GET /api/v1/admin/hub/notifications
    audit_events: GET /api/v1/admin/hub/audit-events
    correlation_drilldown: GET /api/v1/admin/hub/correlation-drilldown
    manual_payment_create: POST /api/v1/admin/hub/finance/manual-payment
    manual_payment_storno: POST /api/v1/admin/hub/finance/manual-payment/{id}/storno
    reconciliation_run: POST /api/v1/admin/hub/reconciliation/run
  mismatch_codes:
    - REGISTRATION_NOT_FOUND
    - REGISTRATION_EXPIRED_UNCONSUMED
    - TERMINAL_NOT_FOUND
    - TERMINAL_DELETED
    - PIN_PROVISIONING_MISSING
    - PIN_PROVISIONING_FAILED
    - SESSION_NOT_FOUND
    - SESSION_FAILED
    - SESSION_HASH_MISSING
    - USAGE_NOT_FOUND
    - USAGE_UNRECONCILED
    - LEDGER_POSTING_MISSING
    - LEDGER_IMBALANCED
    - CALCULATED_SUM_MISMATCH
    - DISCARDED_OUT_OF_BOUNDS
    - POSTED_NOT_MULTIPLE_OF_100
    - MISSING_USAGE_SOURCE_HASH
    - DUPLICATE_MONTHLY_CHARGE
    - DUPLICATE_PAYMENT_POSTING
  reconciliation_invariants:
    debit_equals_credit: true
    projection_rebuild: true
    calculated_equals_posted_plus_discarded: true
    posted_mod_100_is_zero: true
    source_hash_coverage: true
    unique_monthly_charge_and_payment_posting: true
  confirmation_code: "11"
supersedes: []
known_risks: []
consumers:
  - L4D-15A-DOCS
next_prompt_id: L4D-15A-DOCS
```
<!-- HANDOFF:H-L4D-14-MB-v1:END -->

## 25. Принятие handoff H-L4D-15A-DOCS-v1 (шаг 29 l4desk-service)

Фиксация контроллером каскада принятого контракта `H-L4D-15A-DOCS-v1` шага 29 (`l4desk-service`) по результатам приёмки отчёта `l4desk-service/docs/handoffs/L4D-15A-DOCS-report.md` и контрактного пакета `l4desk-service/docs/prompts/contracts/archive-manifest-v1/`.

Все проверки выполнены и подтверждены инструментально:
1. Sequence gate пройден: предшествующий обязательный handoff `H-L4D-14-MB-v1` (шаг 28 MenuBuilder) принят в журнале со статусом `ACCEPTED`. Дубликаты отсутствуют.
2. В `l4desk-service` полностью опубликован и специфицирован общий нормативный контракт архивации `Archive Manifest Contract v1`:
   - Архитектурная изоляция: runtime-репозитории не открывались и не модифицировались.
   - Сквозные идентификаторы: `archive_batch_id`, `owner_project` (`iot-rpc-rest-app`, `l4media`, `MenuBuilder`), `source_month`, `time_range`, `cursor_bounds` (`min_cursor`, `max_cursor`, `through_cursor`, `consumers_passed_cursor`).
   - Архитектура смонтированного тома: layout `<volume_root>/<year>/<month>/<project>/<archive_batch_id>/`, обязательный staging во временном каталоге `.tmp_<archive_batch_id>_<timestamp>` на том же томе, сброс `fsync` и атомарное переименование (`rename(2)` / `os.replace`) только после успешного контрольного перечитывания.
   - Детерминированный формат MVP: UTF-8 `JSONL.gz` (без BOM, LF, ключи отсортированы, без лишних пробелов, временные метки ISO 8601 UTC с `Z`, целые копейки, заголовок gzip с `mtime=0`) + сопутствующий `checksum.sha256`.
   - Защитные барьеры очистки (Purge Guards): запрет очистки оперативной БД до полного перечитывания, совпадения количества строк, проверки хешей SHA-256, успешной пробной выборки (sample restore) и выполнения инварианта курсоров (`consumers_passed_cursor >= through_cursor`).
   - Инвариант `No-Financial-Purge`: финансовый сабледжер (`fin_*`), платежи, тарифные версии, балансовые проекции, суточные агрегаты `FinUsageDaily` и итоговые строки сессий никогда не подлежат очистке.
   - Сроки хранения и резервное копирование: строго 3 полных закрытых календарных месяца горячего окна (относительно текущей даты), архивное хранение не менее 3 лет (`retain_until >= created_at + 3 years`), смонтированный том обязан входить в корпоративный backup.
3. Побайтно проверены контрольные суммы SHA-256 для всех 7 артефактов контрактного пакета и отчёта — полное совпадение на 100%.
4. Полный набор из 13 приёмочных тестов (Acceptance Suite) успешно выполнен раннером `validate_archive_manifest.py` (13 passed, 0 failed).
5. Разрешён переход к следующему шагу каскада: `L4D-15B-IOT` (потребитель: `iot-rpc-rest-app`), а также зафиксированы consumers `L4D-15C-MEDIA` и `L4D-16-MB`.

<!-- HANDOFF:H-L4D-15A-DOCS-v1:BEGIN -->
```yaml
handoff_id: H-L4D-15A-DOCS-v1
status: ACCEPTED
contract_kinds:
  - SCHEMA
  - FIXTURES
producer_prompt_id: L4D-15A-DOCS
producer_scope_project: l4desk-service
producer_report_path: l4desk-service/docs/handoffs/L4D-15A-DOCS-report.md
producer_branch: l4desk/l4d-15a-docs
accepted_at_utc: '2026-09-21T00:30:00Z'
contract_version: 1.0.0
schema_revision: '1.0.0'
artifact_version: 1.0.0
artifact_paths:
  - l4desk-service/docs/prompts/contracts/archive-manifest-v1/archive-manifest.schema.json
  - l4desk-service/docs/prompts/contracts/archive-manifest-v1/schemas.json
  - l4desk-service/docs/prompts/contracts/archive-manifest-v1/examples.json
  - l4desk-service/docs/prompts/contracts/archive-manifest-v1/contract.md
  - l4desk-service/docs/prompts/contracts/archive-manifest-v1/validate_archive_manifest.py
  - l4desk-service/docs/prompts/contracts/archive-manifest-v1/verification.md
  - l4desk-service/docs/handoffs/L4D-15A-DOCS-report.md
artifact_sha256:
  - fc945431d6ceef34511fa40aea379588deb802a44a302061db102970c3d301fb
  - b769d3c45e4819e46d4d7455edd055e03fcf4388f6d2f23089d79c810961d55c
  - a43a07a176dfa28b450dfa5fb456a0451028f95568f0852615168a863245cde2
  - 71572b916c893c09cc0a11c662f826947f8470eed5b0743ffb86cfebecbc09f6
  - d9953d93a3fe1f3d635825802c6054cfbca51e2f1b12b0059b2929cc25a77b6b
  - e27d848f8226415f216a3627a6b63636f5bd92729eddd471a54b2fd92fafa905
  - 3aa7dfdd4e40f6c92f58174e4e5d708e7f25c2ca246f405b9100d320aecde8c1
compatibility:
  backward_compatible_with:
    - H-L4D-14-MB-v1
    - H-L4D-00F-SHARED-v1
    - H-L4D-04B-PB-v1
  breaking_changes: false
  notes: "Canonical immutable Archive Manifest Contract v1 establishing deterministic UTF-8 JSONL.gz + manifest.json + sha256 checksums, atomic directory lifecycle on mounted volume, consumer cursor guards, strict 3-month hot window, 3-year archive retention, backup invariant, and non-purgeable financial records."
deployment_status: DOCS_PUBLISHED
deployed_environment: documentation
feature_flags:
  l4desk_archive_manifest_v1: true
contract_payload:
  manifest_version: "1.0.0"
  schema_id: "https://l4desk.org/schemas/archive-manifest-v1.json"
  supported_owners:
    - "iot-rpc-rest-app"
    - "l4media"
    - "MenuBuilder"
  storage_layout_pattern: "<root>/<year>/<month>/<project>/<archive_batch_id>/"
  compression: "gzip (mtime=0)"
  serialization: "deterministic UTF-8 JSONL (sort_keys=True, compact separators, ISO 8601 UTC Z)"
  states:
    - prepared
    - verified
    - purged
    - failed
  retention_invariants:
    hot_details_months: 3
    archive_retention_years: 3
    backup_required: true
  purge_guards:
    full_reread_required: true
    sha256_match_required: true
    row_count_match_required: true
    restore_sample_required: true
    cursor_guard_required: true
    atomic_rename_required: true
    no_financial_purge: true
  error_codes:
    - CHECKSUM_MISMATCH
    - COUNT_MISMATCH
    - CURSOR_LAG_DETECTED
    - RESTORE_SAMPLE_FAILED
    - HOT_RETENTION_VIOLATION
    - DISK_SPACE_EXHAUSTED
    - VOLUME_UNAVAILABLE
    - ACTIVE_RECORDS_DETECTED
    - ATOMIC_RENAME_FAILED
    - PURGE_OPERATION_FAILED
supersedes: []
known_risks: []
consumers:
  - L4D-15B-IOT
  - L4D-15C-MEDIA
  - L4D-16-MB
next_prompt_id: L4D-15B-IOT
```
<!-- HANDOFF:H-L4D-15A-DOCS-v1:END -->

## 26. Принятие handoff H-L4D-15B-IOT-v1 (шаг 30 iot-rpc-rest-app)

Фиксация контроллером каскада принятого контракта `H-L4D-15B-IOT-v1` шага 30 (`iot-rpc-rest-app`) по результатам приёмки отчёта `docs/l4desk/handoffs/L4D-15B-IOT-report.md`.

Все проверки выполнены и подтверждены инструментально:
1. Sequence gate пройден: предшествующие обязательные handoffs `H-L4D-15A-DOCS-v1`, `H-L4D-02-IOT-v1`, `H-L4D-07-IOT-v1` приняты в журнале со статусом `ACCEPTED`.
2. В `iot-rpc-rest-app` реализована помесячная архивация технических подробностей:
   - Классифицированы high-volume технические данные: `iot_session_events`, `rpc_transitions`, `presence_events`.
   - Инвариант `No-Financial-Purge`: сводные строки сессий (`tb_remote_sessions`) и финансовые сущности исключены из удаления.
   - Детерминированный формат: потоковый UTF-8 `JSONL.gz` (`mtime=0`), SHA-256 файл `checksum.sha256`, маскирование секретов (`SecretScrubber`).
   - Безопасность путей: `PathSecurityGuard` (защита от path traversal, запрет symlink, проверка свободного места на диске).
   - Защитные барьеры: `RetentionGuard` (> 3 закрытых месяцев), `ActiveRecordsGuard` (запрет при открытых сессиях), `CursorGuard` (проверка `consumers_passed_cursor >= through_cursor`), полное перечитывание архива и `sample restore`.
   - Атомарность и порционная очистка: промежуточный каталог `.tmp_<batch_id>_<timestamp>`, атомарное переименование `os.replace` в `<volume_root>/<year>/<month>/iot-rpc-rest-app/<batch_id>/`, удаление порциями (`chunk_size`).
   - Безопасность деплоя: воркер по умолчанию отключен (`archive_worker_enabled: false`), реализована поддержка dry-run.
3. Пройдены все 406 тестов проекта (100% pass), включая комплексный набор тестов `test_l4d_15b_archive.py` и `test_internal_v1_archive_api.py`.
4. Разрешён переход к следующему шагу каскада: `L4D-15C-MEDIA` (потребитель: `l4media`), а также зафиксирован потребитель `L4D-16-MB`.

<!-- HANDOFF:H-L4D-15B-IOT-v1:BEGIN -->
```yaml
handoff_id: H-L4D-15B-IOT-v1
status: ACCEPTED
contract_kinds:
  - API
  - EVENT
  - DEPLOYMENT
producer_prompt_id: L4D-15B-IOT
producer_scope_project: iot-rpc-rest-app
producer_report_path: docs/l4desk/handoffs/L4D-15B-IOT-report.md
producer_branch: l4desk/l4d-15b-iot
producer_commit: af3b4f06456ddad2c8c44477dc52f25c49ee5722
accepted_at_utc: '2026-09-21T03:30:00Z'
contract_version: 1.0.0
schema_revision: '1.0.0'
artifact_version: 1.0.0
artifact_paths:
  - docs/l4desk/handoffs/L4D-15B-IOT-report.md
  - app-service/core/archive/pipeline.py
  - app-service/core/archive/canonical.py
  - app-service/core/archive/guards.py
  - app-service/core/models/archive.py
  - app-service/alembic/versions/2026_09_21_0007_add_fin_archive_batches.py
  - app-service/tests/core/test_l4d_15b_archive.py
compatibility:
  backward_compatible_with:
    - H-L4D-15A-DOCS-v1
    - H-L4D-02-IOT-v1
    - H-L4D-07-IOT-v1
  breaking_changes: false
  notes: "Full implementation of IoT/RPC monthly archive pipeline with deterministic JSONL.gz (mtime=0), SHA-256 manifest contract, staging-to-atomic promotion, consumer cursor guard, active records guard, and No-Financial-Purge bounded deletions."
deployment_status: DEPLOYED
deployed_environment: documentation
feature_flags:
  archive_worker_enabled: false
  archive_dry_run_default: false
contract_payload:
  manifest_version: "1.0.0"
  owner_project: "iot-rpc-rest-app"
  record_types:
    - "iot_session_events"
    - "rpc_transitions"
    - "presence_events"
  cursor_rules:
    through_cursor_source: "max(RemoteSessionEvent.cursor)"
    consumer_guard_condition: "consumers_passed_cursor >= through_cursor"
    on_lag_action: "abort_purge_mark_failed"
  purge_rules:
    financial_records_purged: false
    session_summaries_purged: false
    bounded_chunk_size: 1000
    pre_purge_verification_required: true
    recheck_active_records: true
  storage_rules:
    volume_root_configurable: true
    traversal_symlink_protected: true
    staging_prefix: ".tmp_"
    atomic_promotion: "os.replace"
    compression: "gzip (mtime=0.0)"
supersedes: []
known_risks: []
consumers:
  - L4D-15C-MEDIA
  - L4D-16-MB
next_prompt_id: L4D-15C-MEDIA
```
<!-- HANDOFF:H-L4D-15B-IOT-v1:END -->

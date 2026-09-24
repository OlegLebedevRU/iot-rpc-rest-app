# L4D-08B-FIX-01-MB — Обязательная единая media-session orchestration без legacy direct-flow

```yaml
prompt_id: L4D-08B-FIX-01-MB
scope_project: MenuBuilder
scope_root: D:\repo\platerra\Public\etranprocessing\MenuBuilder
prompt_type: corrective-implementation-step
corrects_prompt_id: L4D-08B-MB
corrective_registration_required: true
sequence_gate_handoff_id: H-L4D-08B-MB-v1
required_handoff_ids:
  - H-L4D-07-IOT-v1
  - H-L4D-08A-MEDIA-v1
  - H-L4D-08B-MB-v1
sequence_gate_status: BLOCKED_UNTIL_CORRECTIVE_REGISTERED
output_handoff_id: H-L4D-08B-FIX-01-MB-v1
next_prompt_id: L4D-09-MB
branch: l4desk/l4d-08b-fix-01-mb
report_path: MenuBuilder/docs/l4desk/handoffs/L4D-08B-FIX-01-MB-report.md
candidate_format: DETACHED_V1
candidate_path: MenuBuilder/docs/l4desk/handoffs/L4D-08B-FIX-01-MB-candidate.md
architecture_sections: [1, 3, 4, 5, 6, 7, 15, 16, 17]
consumers:
  - L4D-09-MB
  - L4D-10-MB
  - L4D-12-MB
  - L4D-13-MB
  - L4D-14-MB
  - L4D-17E-MB
  - L4D-17F-DOCS
  - L4D-18E-MB
```

---

## 1. Цель и обязательный результат

Ты — агент-исполнитель corrective-шага **`L4D-08B-FIX-01-MB`** в единственном разрешённом проекте **`MenuBuilder`**.

Необходимо полностью устранить несовместимость между video-flow MenuBuilder и lifecycle/reconcile-механизмом `l4media-ingress`.

### Корневая проблема

В системе были одновременно доступны два конкурирующих способа подготовки видеотрансляции:

```text
Корректный путь:
MenuBuilder → IoT session lock → media lifecycle API
→ ingress route + Janus mountpoint + ingress MediaSession

Рисковый legacy direct-flow:
MenuBuilder → direct ingress route setup + direct Janus mountpoint setup
→ ingress не знает MediaSession
→ reconcile считает route/mountpoint orphan
→ очистка ресурса через очередной reconcile tick
→ RTP прекращается, браузер показывает зависший кадр
```

### Единственный допустимый результат после corrective-шага

Для **любого** запуска video-сессии — нового, старого UI-flow, operator flow, viewer flow, REST flow или любого сохранённого frontend route — должен существовать ровно один runtime путь:

```text
MenuBuilder UI/API
→ RemoteSessionUseCase
→ IoT session lifecycle / session lock
→ media_orchestrator.start_session(...)
→ POST /api/v1/media/sessions/start
→ l4media-ingress создаёт и владеет:
   - dynamic ingress route;
   - Janus mountpoint;
   - MediaSession;
→ запуск terminal stream только после успешного media start
```

### Непереговорные инварианты

1. **MenuBuilder не создаёт, не обновляет и не удаляет dynamic ingress routes напрямую.**
2. **MenuBuilder не создаёт и не удаляет Janus mountpoints напрямую.**
3. **Запрещены любые runtime fallback-и от lifecycle API к прямому ingress/Janus setup.**
4. При недоступности, ошибке авторизации, timeout, конфликте, ошибке схемы ответа или иной ошибке lifecycle API video start завершается контролируемой ошибкой; direct-flow не запускается.
5. Все существующие UI-пути остаются безопасными для пользователя: они либо используют новый unified API напрямую, либо временно сохраняют прежний HTTP path только как тонкую adapter-обёртку, делегирующую в `RemoteSessionUseCase` без собственной orchestration-логики.
6. HTTP path сам по себе не является legacy media-flow. Legacy считается любая самостоятельная логика создания route/mountpoint или обход lifecycle API.
7. `l4media-ingress` остаётся единственным владельцем lifecycle ресурсов: route, mountpoint, TTL cleanup, reconcile и их технического состояния.
8. На успешном video start обязан существовать lifecycle session с тем же `session_id`, который используется для последующего health/stop.
9. Старт terminal RTP stream разрешён только после успешного ответа lifecycle `start`.
10. При частичном сбое применяется compensating stop через утверждённые IoT/media APIs; прямое удаление ingress/Janus ресурсов из MenuBuilder запрещено.
11. Нельзя отключать, ослаблять, обходить или маскировать reconcile в `l4media`.
12. Нельзя оставлять feature flag, конфигурационный переключатель или «временную» ветку, возвращающую direct setup.
13. Нельзя объявлять step завершённым, пока длительный production-compatible smoke не доказал, что поток переживает минимум три reconcile-интервала.

---

## 2. Scope, изоляция и запреты

### Разрешённый scope

Изменения разрешены только внутри `MenuBuilder`:

```text
MenuBuilder/backend/
MenuBuilder/frontend/
MenuBuilder/docs/l4desk/handoffs/
```

Разрешено изменять только компоненты, необходимые для перехода всех video-session flows на единый безопасный lifecycle:

- routers, services, repositories и tests MenuBuilder;
- frontend API-клиенты, hooks, pages/routes/components MenuBuilder, если это необходимо, чтобы UI использовал единый session API;
- MenuBuilder-specific deployment/runbook documentation;
- отчёт и detached candidate текущего шага.

### Строго запрещено

1. Изменять `l4media`, `iot-rpc-rest-app`, `tools`, `ProcessingBackend`, `shared`, `l4desk-service`.
2. Редактировать `l4desk-service/docs/prompts/contract-handoff.md`.
3. Менять принятые handoff-блоки.
4. Отключать ingress reconcile, TTL watchdog или orphan cleanup.
5. Реализовывать новый параллельный media service.
6. Добавлять прямой HTTP-вызов ingress `PUT /routes/{sn}`.
7. Добавлять прямые вызовы Janus для `create`, `destroy` или иной lifecycle-оркестрации mountpoint.
8. Сохранять fallback на direct ingress/Janus setup при любой ошибке lifecycle API.
9. Скрывать lifecycle ошибки за ответом «успешный старт» или «legacy mode».
10. Вносить unrelated-изменения, откатывать чужие рабочие изменения, выполнять commit/push/deploy других проектов.
11. Включать в логи, тестовые fixtures, отчёт или commit секреты, service tokens, PIN, JWT, cookies, реальные персональные данные.

---

## 3. Contract Gate и допуск к началу работы

До редактирования кода выполни строго следующие действия.

### 3.1. Регистрация corrective prompt

1. Проверь в `l4desk-service/docs/prompts/contract-handoff.md`, что для этого шага существует отдельная append-only запись `CORRECTIVE_REGISTRATION`.
2. Убедись, что регистрация:
    - адресована `L4D-08B-FIX-01-MB`;
    - разрешает изменения только в `MenuBuilder`;
    - ссылается на `H-L4D-08B-MB-v1`;
    - не отозвана;
    - определяет корректный sequence gate.
3. Если регистрации нет, статус результата:

```text
BLOCKED_CORRECTIVE_REGISTRATION
```

Не меняй runtime-код, не создавай handoff и не продолжай выполнение.

### 3.2. Проверка входных handoff

Найди ровно по одному блоку со статусом `ACCEPTED`:

```text
H-L4D-07-IOT-v1
H-L4D-08A-MEDIA-v1
H-L4D-08B-MB-v1
```

Для каждого блока проверь:

- текущий prompt указан в разрешённых consumers либо допущен корректирующей регистрацией;
- paths и SHA-256 immutable artifacts совпадают;
- contract/deployment status пригоден для production-compatible consumer implementation;
- нет `REVOCATION`, конфликтующего superseding-handoff или неоднозначности версии.

Минимально подтверждаемые контрактные гарантии:

| Контракт | Обязательная гарантия |
|---|---|
| `H-L4D-07-IOT-v1` | Идемпотентный remote session lifecycle, один session lock терминала, корректный stop. |
| `H-L4D-08A-MEDIA-v1` | `start / health / stop` lifecycle API; ingress владеет route и Janus mountpoint; reconcile удаляет только ресурсы без активной MediaSession. |
| `H-L4D-08B-MB-v1` | Утверждённый unified orchestration baseline и выбранные API/идентификаторы. |

При отсутствии, неоднозначности, digest mismatch или непринятом статусе заверши шаг с:

```text
BLOCKED_CONTRACT
```

### 3.3. Baseline и диагностическая фиксация

До изменений:

1. Зафиксируй текущую ветку, commit, `git status` и список уже существующих пользовательских изменений.
2. Не включай чужие изменения в свой commit.
3. Определи все MenuBuilder entry points, которые могут:
    - запускать video-session;
    - создавать ingress route;
    - создавать Janus mountpoint;
    - останавливать или уничтожать route/mountpoint;
    - получать video-session/pin/status;
    - запускаться из legacy UI, operator UI, viewer UI или remote session API.
4. Выполни semantic/text search по минимуму следующих признаков:

```text
/routes/
upsert_route
ensure_ingress
janus
mountpoint
create_video_session
destroy_mountpoint
remote_input_stream_start
RemoteSessionUseCase
media_orchestrator_client
start_session
stop_session
```

5. В отчёте составь таблицу:

| Entry point / UI action | Состояние до исправления | Риск | Состояние после исправления |
|---|---|---|---|

---

## 4. Нормативная целевая архитектура

### 4.1. Единый жизненный цикл video-session

Для любого video start соблюдай последовательность:

```text
1. Проверить пользователя, tenant boundary и permissions.
2. Проверить policy/entitlement.
3. Создать или идемпотентно повторить local session reservation.
4. Захватить durable IoT remote session lock.
5. Получить согласованную control lease, если она нужна конкретному режиму.
6. Вызвать media lifecycle start через MediaOrchestratorClient.
7. Только после успешного lifecycle start вызвать terminal stream start.
8. Зафиксировать video session как active.
9. Для status/health обращаться к lifecycle health API.
10. Для stop:
    terminal stream stop
    → lifecycle stop
    → IoT remote-session stop
    → release lease
    → local session closed.
```

### 4.2. Идентификаторы

Для одной remote video-session должны быть согласованно трассируемы:

```text
operation_id
correlation_id
IoT provider session_id
media lifecycle session_id
terminal SN
terminal/device ID
lease_id
stream_instance_id, если он выдаётся Agent/IoT
```

Требования:

1. `media lifecycle session_id` должен быть равен утверждённому provider session identifier либо другому детерминированно связанному идентификатору, документированному в contract-compatible code.
2. Нельзя использовать безымянный fallback вида `sess-video-<device_id>` как замену устойчивого session lifecycle identifier, если такой идентификатор уже выдан IoT.
3. Идемпотентный повтор start с тем же `operation_id` не должен создавать второй media-session, route или mountpoint.
4. Все error logs/audit events обязаны содержать безопасные correlation fields без секретов.

### 4.3. UI-safe migration

Под «UI-safe» понимается сохранение предсказуемого пользовательского поведения при полном удалении опасной внутренней legacy orchestration.

Допустимо:

- сохранить публичный HTTP path, если его используют опубликованные frontend bundle/закладки;
- сохранить shape успешного response, если он нужен существующему UI;
- реализовать такой endpoint как thin adapter;
- постепенно переключить frontend на unified remote-session API в том же шаге.

Обязательно:

1. Любой сохранённый legacy HTTP path должен только:
    - проверить доступ;
    - нормализовать request;
    - вызвать `RemoteSessionUseCase`;
    - преобразовать результат в совместимый UI response при необходимости.
2. Такой path не должен:
    - напрямую управлять ingress route;
    - напрямую управлять Janus mountpoint;
    - самостоятельно создавать конкурентную remote session;
    - игнорировать lifecycle failure;
    - создавать собственный несвязанный `session_id`.
3. UI должен получить контролируемую ошибку запуска, а не ложный успешный video player:
    - `session_busy` → показать, что терминал занят;
    - `media_unavailable` / lifecycle `502` → показать, что медиаканал недоступен и трансляция не запущена;
    - `media_unauthorized` → показать безопасную общую ошибку конфигурации media service, без токенов и внутренних URL;
    - `media_timeout` → показать ошибку ожидания подготовки канала;
    - `stream_start_failed` → показать, что terminal stream не был запущен.
4. При ошибке UI обязан:
    - не открывать Janus player как работающий;
    - не сохранять ложное состояние active;
    - не оставлять бесконечный loader;
    - позволять пользователю повторить start как новую корректную операцию;
    - не выполнять client-side fallback к старому API.
5. Во время загрузки/перехода UI должен корректно обрабатывать `starting`, `active`, `failed`, `closed`; пользователь не должен видеть «трансляция активна» до подтверждённого lifecycle start.
6. Вопросы backward compatibility UI не являются основанием сохранить direct-flow.

---

## 5. Обязательные изменения реализации

### 5.1. Удаление direct ingress route ownership из MenuBuilder

Полностью удали из runtime production path MenuBuilder любую возможность:

```text
PUT /routes/{sn}
POST/PUT/DELETE direct route management
direct ingress route creation/update/deletion
```

Если helper существует исключительно для direct route management:

- удалить его;
- удалить его imports/call sites;
- удалить связанные feature flags;
- удалить obsolete tests;
- удалить/обновить устаревшую документацию MenuBuilder.

Если helper имеет другое необходимое назначение, раздели обязанности так, чтобы никакой production call path не мог использовать его для управления route.

### 5.2. Удаление direct Janus mountpoint ownership из MenuBuilder

Полностью удали из runtime production path MenuBuilder любую возможность:

```text
Janus streaming create mountpoint
Janus streaming destroy mountpoint
recreate mountpoint
direct Janus lifecycle cleanup
```

MenuBuilder может возвращать клиенту connection metadata, полученные от lifecycle API/use case, но не должен сам управлять mountpoint lifecycle.

Удаление local UI pin cache разрешено только после проверки, что lifecycle API остаётся источником значения, нужного player UI. Не допускай рассинхронизации pin между UI и lifecycle-created mountpoint.

### 5.3. Устранение fallback

Любой обработчик, который при ошибке `media_orchestrator.start_session(...)` продолжает выполнение через direct route/Janus setup, должен быть удалён или переписан.

Нормативное поведение при lifecycle start failure:

```text
media lifecycle start failed
→ compensating IoT session stop, если lock уже создан
→ release control lease, если она уже создана
→ local session state = failed
→ audit/event с безопасной причиной
→ контролируемый HTTP error
→ UI показывает failed state
→ route/mountpoint через MenuBuilder не создаются
```

Не используй broad `except Exception` для fallback. Разрешён broad exception только для:

- надёжной фиксации failed state;
- compensating cleanup утверждёнными API;
- последующего преобразования в безопасную error response.

### 5.4. Перевод legacy entry points

Переведи все обнаруженные legacy video/control entry points на `RemoteSessionUseCase` или его единственный внутренний contract-compatible facade.

Минимум проверь и приведи к единой схеме:

- legacy create/get video session flow;
- control lease + stream start flow;
- stream stop flow;
- control lease release flow;
- status/health flow;
- player bootstrap flow;
- frontend API wrappers;
- frontend pages/routes, которые могут запускать видео не через unified endpoint;
- cleanup on browser/UI unmount, если он инициирует server-side stop.

Нельзя оставлять частичную схему, в которой:

```text
legacy stream/start создаёт local active session
→ отдельный legacy video endpoint независимо создаёт media session
→ identifiers, stop owner и state расходятся.
```

Если требуется сохранить несколько HTTP endpoints, они обязаны быть тонкими фасадами одного use case и использовать одну session identity/state machine.

### 5.5. Stop и cleanup

Обеспечь единый idempotent stop flow:

```text
terminal stream stop
→ lifecycle media stop
→ IoT session stop
→ lease release
→ local state closed
```

Требования:

1. Ошибка одного cleanup шага не должна переключать код на direct Janus/ingress cleanup.
2. Ошибки cleanup должны логироваться с `session_id`, `correlation_id`, `SN`, этапом и безопасным кодом причины.
3. Повтор stop не должен создавать ошибку для UI и не должен создавать ресурсы.
4. После stop lifecycle health возвращает `stopped` или согласованный terminal state.
5. MenuBuilder не должен делать предположений о существовании route/mountpoint после lifecycle stop.

### 5.6. Наблюдаемость

Добавь структурированную observability без секретов.

Минимальные события/логи:

```text
video_session_start_requested
video_media_lifecycle_started
video_terminal_stream_started
video_session_start_failed
video_session_stop_requested
video_media_lifecycle_stopped
video_session_closed
```

Минимальные поля:

```text
operation_id
correlation_id
session_id
terminal_id
SN
tenant_id
lease_id, если есть
stream_instance_id, если есть
stage
reason_code
```

Запрещено логировать:

```text
service token
Authorization header
PIN
JWT/cookies
полный request body с секретными полями
```

---

## 6. Обязательные тесты

Все тесты выполняются только в `MenuBuilder`. Межпроектные runtime-тесты заменяются contract-compatible stubs, test doubles и доступными утверждёнными deployed endpoints в рамках project-local smoke.

### 6.1. Unit и integration tests backend

Добавь или обнови тесты, доказывающие следующее.

1. **Unified video start использует lifecycle API.**
    - Для video start вызывается `MediaOrchestratorClient.start_session`.
    - В lifecycle start передаются корректные `session_id`, `operation_id`, `SN`, device/terminal ID и TTL.
    - Terminal stream start выполняется только после успешного lifecycle start.

2. **Lifecycle start failure fail-closed.**
    - Для `401`, `409`, `5xx`, transport timeout и malformed response:
        - HTTP start возвращает контролируемую ошибку;
        - session не становится `active`;
        - выполняются допустимые compensating calls;
        - не происходит вызов direct route setup;
        - не происходит вызов direct Janus create;
        - terminal stream не запускается.

3. **Нет direct ingress calls.**
    - В тестах замокай HTTP transport и докажи отсутствие запросов к legacy route endpoint.
    - Добавь repository-level/static regression assertion, запрещающую production references на legacy route management path в backend MenuBuilder.

4. **Нет direct Janus lifecycle calls.**
    - Добавь regression assertion, запрещающую production references на Janus `create`/`destroy` mountpoint lifecycle из MenuBuilder backend.
    - Исключения разрешены только если доказано, что вызов не управляет media lifecycle; такое исключение должно быть отдельно обосновано в отчёте и одобрено тестом/комментарием. По умолчанию исключений нет.

5. **Legacy endpoint — thin unified facade.**
    - Каждый сохранённый legacy HTTP path вызывает `RemoteSessionUseCase`.
    - Он не вызывает ingress/Janus helpers.
    - Он возвращает UI-safe response или контролируемую error response.

6. **Единая идентичность сессии.**
    - IoT provider session ID и media lifecycle session ID согласованы.
    - Повтор с тем же `operation_id` не создаёт вторую media-session.
    - Stop по `session_id` останавливает именно созданную lifecycle session.

7. **Rollback.**
    - Ошибка terminal stream start после lifecycle start вызывает lifecycle `stop_session`.
    - Ошибка получения lease/IoT lock не создаёт lifecycle session.
    - Ошибка lifecycle start освобождает уже созданные IoT ресурсы утверждёнными API.

8. **Idempotent stop.**
    - Повторный stop успешен.
    - Нет direct route/Janus cleanup.
    - Состояние local session согласованно закрывается.

9. **Status/health.**
    - Unified status использует lifecycle health.
    - При отсутствующей lifecycle session legacy UI не получает ложный `streaming=true`.
    - Ошибка health отображается как controlled unavailable/unknown state, а не как active stream.

10. **Tenant, role и policy regression.**
    - Сохраняются tenant isolation, role matrix, session mutual exclusion и policy/entitlement seam.
    - Исправление не разрешает обход tenant/session lock через сохранённый legacy HTTP path.

### 6.2. Frontend tests

Добавь или обнови tests frontend для следующих пользовательских сценариев:

1. Старый экран видео запускает unified session flow и не вызывает legacy direct setup API.
2. Новый экран/профиль L4Desk использует тот же unified flow.
3. При `media_unavailable`, `media_timeout`, `media_unauthorized`, `stream_start_failed`:
    - отображается понятная ошибка;
    - player не маркируется как active;
    - нет бесконечной загрузки;
    - доступен безопасный повтор запуска.
4. При `session_busy` UI не пытается автоматически вытеснить другую сессию.
5. При штатном start UI использует только lifecycle-provided/ unified-session metadata для подключения player.
6. При stop/unmount не инициируется legacy direct cleanup.

### 6.3. Длительная reconcile-regression проверка

Добавь тестовую процедуру и, где это возможно, автоматизированный integration/smoke test, который доказывает отсутствие обрыва на границе reconcile.

Сценарий:

```text
1. Стартовать video-session через каждый доступный UI/API entry point.
2. Зафиксировать session_id, correlation_id и SN.
3. Подтвердить успешный lifecycle health state=active.
4. Подтвердить наличие растущих RTP/bytes counters.
5. Удерживать поток не менее 180 секунд
   или не менее трёх фактических reconcile-интервалов текущей среды,
   если интервал больше 60 секунд.
6. Не инициировать ручной stop.
7. Подтвердить:
   - lifecycle session остаётся active;
   - route не был удалён как orphan;
   - RTP packet counter продолжает возрастать;
   - browser/player freshness сохраняется;
   - отсутствует событие orphan cleanup для тестового SN;
   - UI не переходит в ложный failed/stale state.
8. Выполнить штатный stop.
9. Подтвердить:
   - lifecycle session stopped;
   - media resources освобождены lifecycle owner-ом;
   - local/IoT state закрыт;
   - повторный stop идемпотентен.
```

Если автоматизация 180-секундного теста в CI непрактична, она обязательна как production-compatible smoke после deploy. Unit/integration tests всё равно должны моделировать минимум три reconcile ticks или их эквивалентную семантику.

### 6.4. Negative test: lifecycle outage

Обязательный тест:

```text
lifecycle start отвечает ошибкой или недоступен
→ start request неуспешен
→ UI получает error
→ нет route
→ нет Janus mountpoint, созданных MenuBuilder
→ нет RTP stream start
→ нет active local session
→ нет orphan cleanup как следствия direct fallback
```

---

## 7. Проверки качества и безопасности

До отчёта выполни только project-local проверки MenuBuilder:

```text
backend lint
backend formatting check
backend type check
backend unit/integration/contract tests
frontend unit tests
frontend TypeScript check
frontend production build
```

Используй фактические команды проекта. Минимально ожидаются эквиваленты:

```bash
npm run build
npm test
```

и штатные Python-команды из `MenuBuilder/backend`.

Также выполни:

1. Поиск по production исходникам MenuBuilder на запрещённые direct media lifecycle patterns.
2. Проверку, что direct route/Janus helpers и их imports/call sites удалены либо недостижимы и не входят в production runtime.
3. Проверку OpenAPI/route registration для сохранённых UI-safe endpoints.
4. Проверку, что frontend production bundle не содержит вызовов удалённого legacy direct API.
5. Проверку `git diff` на отсутствие изменений вне `MenuBuilder`.

Любой failed test, lint/type/build error, scope violation или неоднозначный lifecycle ownership означает:

```text
BLOCKED_IMPLEMENTATION
```

---

## 8. Deploy и production-compatible smoke

Deploy допускается только после зелёных project-local проверок и только по runbook `MenuBuilder`.

### 8.1. Порядок deploy

1. Подготовить rollback point: текущий image/artifact/version и проверенный способ отката.
2. Развернуть backend MenuBuilder.
3. Развернуть frontend bundle MenuBuilder.
4. Не менять l4media, ingress, Janus, IoT, Agent или их конфигурацию.
5. Проверить health/readiness MenuBuilder.
6. Выполнить безопасный smoke на выделенном тестовом terminal/SN и тестовом tenant/user.
7. Не использовать реальные секреты в отчёте.

### 8.2. Обязательный smoke

Выполни отдельно:

1. **Legacy UI path:** существующий экран видеонаблюдения.
2. **Unified API path:** remote session API.
3. **Role path:** operator/L4Desk user согласно текущей role matrix.
4. **Failure path:** контролируемая имитация/тест media lifecycle failure, если production runbook допускает её безопасно; иначе используй тестовый contract stub до deploy и зафиксируй ограничение.
5. **Long-running path:** непрерывный поток минимум 180 секунд.

Для каждого запуска зафиксируй обезличенно:

```text
timestamp
terminal/SN masked
session_id masked
correlation_id
start endpoint/UI path
lifecycle start result
health state before/after wait
RTP/bytes counters before/after wait
browser freshness evidence
stop result
```

### 8.3. Условия успешного production smoke

Все условия обязательны:

- ни один старт не использует direct route/Janus calls;
- lifecycle session существует и `active` во время длительного теста;
- video работает более трёх reconcile-интервалов;
- route не очищается как orphan;
- RTP/bytes counters продолжают возрастать;
- browser получает свежие кадры;
- stop выполняется штатно;
- fallback direct-flow отсутствует;
- старый UI не ломается с точки зрения пользователя;
- ошибки lifecycle видимы как ошибки, а не маскируются ложным стартом;
- rollback readiness проверен.

---

## 9. Документация и handoff artifacts

### 9.1. Отчёт

Создай:

```text
MenuBuilder/docs/l4desk/handoffs/L4D-08B-FIX-01-MB-report.md
```

Отчёт обязан содержать:

1. `prompt_id`, scope, branch, commit, дату и итоговый статус.
2. Подтверждение corrective registration и входных accepted handoff.
3. Baseline-таблицу всех найденных video/media entry points.
4. Точное описание удалённых direct-flow путей.
5. Список удалённых или переписанных helpers/endpoints/components.
6. Доказательство, что сохранённые HTTP paths являются thin facades единого use case.
7. Таблицу до/после по session identifiers и stop ownership.
8. Результаты backend/frontend tests.
9. Результаты static regressions против direct route/Janus calls.
10. Результаты длительного reconcile-regression теста.
11. Результаты production-compatible smoke.
12. Deploy, rollback instructions и rollback readiness.
13. Известные риски, которые действительно остались.
14. Готовый candidate block в формате DETACHED_V1.
15. Явное заявление:

```text
MenuBuilder больше не владеет direct ingress route или Janus mountpoint lifecycle.
Все video flows используют lifecycle API l4media-ingress.
Runtime fallback к direct-flow отсутствует.
```

### 9.2. Candidate

Создай:

```text
MenuBuilder/docs/l4desk/handoffs/L4D-08B-FIX-01-MB-candidate.md
```

Сформируй candidate с реальными SHA-256 после сохранения всех артефактов:

```yaml
<!-- HANDOFF:H-L4D-08B-FIX-01-MB-v1:BEGIN -->
handoff_id: H-L4D-08B-FIX-01-MB-v1
status: CANDIDATE
contract_kinds:
  - MEDIA_SESSION_CONSUMER
  - LEGACY_FLOW_REMOVAL
  - UI_SAFE_UNIFIED_ORCHESTRATION
  - RECONCILE_REGRESSION_GUARD
producer_prompt_id: L4D-08B-FIX-01-MB
producer_scope_project: MenuBuilder
producer_report_path: MenuBuilder/docs/l4desk/handoffs/L4D-08B-FIX-01-MB-report.md
producer_branch: l4desk/l4d-08b-fix-01-mb
producer_commit: <actual_git_commit_sha>
accepted_at_utc: null
contract_version: 1.1.0
schema_revision: <actual_or_N/A>
artifact_version: 1.1.0
artifact_paths:
  - MenuBuilder/docs/l4desk/handoffs/L4D-08B-FIX-01-MB-report.md
  - MenuBuilder/docs/l4desk/handoffs/L4D-08B-FIX-01-MB-candidate.md
  - <all changed runtime source files>
  - <all added_or_changed backend tests>
  - <all added_or_changed frontend tests>
artifact_sha256:
  - <actual_sha256_for_each_artifact_in_matching_order>
compatibility:
  backward_compatible_with:
    - H-L4D-07-IOT-v1
    - H-L4D-08A-MEDIA-v1
  breaking_changes: true
  notes: >
    Direct MenuBuilder ownership of dynamic ingress routes and Janus mountpoints
    is removed. All legacy and current video UI/API flows use the single
    RemoteSessionUseCase and l4media lifecycle API. Legacy HTTP paths, if retained
    for UI routing, are thin facades only and do not preserve direct media setup.
deployment_status: <DEPLOYED_or_LOCAL_BUILD_VERIFIED>
deployed_environment: <actual_environment>
feature_flags:
  direct_ingress_route_fallback: removed
  direct_janus_mountpoint_fallback: removed
  unified_media_lifecycle_required: true
contract_payload:
  ownership:
    menu_builder:
      - tenant/auth/policy/session orchestration
      - IoT session and lease coordination
      - lifecycle API consumer
    l4media_ingress:
      - dynamic ingress route lifecycle
      - Janus mountpoint lifecycle
      - media session state
      - TTL/watchdog/reconcile cleanup
  prohibited_in_menubuilder:
    - direct_route_creation
    - direct_route_deletion
    - direct_janus_mountpoint_creation
    - direct_janus_mountpoint_deletion
    - lifecycle_to_direct_fallback
  required_video_start_order:
    - iot_session_lock
    - control_lease_when_required
    - media_lifecycle_start
    - terminal_stream_start
    - local_session_active
  failure_behavior:
    media_lifecycle_failure: fail_closed_with_compensating_stop
    direct_media_fallback: prohibited
  ui_safety:
    legacy_ui_paths_delegate_to_unified_use_case: true
    false_success_on_media_failure: prohibited
    player_opened_before_confirmed_lifecycle_start: prohibited
  verification:
    long_running_reconcile_test_duration_sec: <actual_duration_gte_180>
    reconcile_intervals_survived: <actual_value_gte_3>
    direct_route_calls_detected: false
    direct_janus_calls_detected: false
    orphan_cleanup_for_test_session_detected: false
supersedes:
  - H-L4D-08B-MB-v1
known_risks:
  - <only actual remaining risks, or []>
consumers:
  - L4D-09-MB
  - L4D-10-MB
  - L4D-12-MB
  - L4D-13-MB
  - L4D-14-MB
  - L4D-17E-MB
  - L4D-17F-DOCS
  - L4D-18E-MB
next_prompt_id: L4D-09-MB
<!-- HANDOFF:H-L4D-08B-FIX-01-MB-v1:END -->
```

---

## 10. Commit, push и статус завершения

1. Commit разрешён только после зелёных проверок.
2. Commit включает только изменения `MenuBuilder`, относящиеся к этому corrective scope.
3. Не включай существующие unrelated user changes.
4. Push выполняй только в ветку:

```text
l4desk/l4d-08b-fix-01-mb
```

5. Deploy выполняй только после commit/push и только по MenuBuilder runbook.
6. Не помечай prompt завершённым до post-deploy smoke.

### Допустимый финальный статус

```text
ACCEPTED
```

только если одновременно выполнены все критерии раздела 11.

### Обязательные блокирующие статусы

```text
BLOCKED_CORRECTIVE_REGISTRATION
BLOCKED_CONTRACT
BLOCKED_IMPLEMENTATION
BLOCKED_TESTS
BLOCKED_DEPLOY
BLOCKED_RECONCILE_REGRESSION
BLOCKED_SCOPE_VIOLATION
```

---

## 11. Критерии приёмки

Шаг может быть передан на handoff acceptance только при одновременном выполнении всех условий:

1. Corrective prompt зарегистрирован в `l4desk-service` контроллером каскада.
2. Все required handoff IDs существуют, приняты и проверены.
3. В MenuBuilder отсутствуют production direct calls для управления ingress route.
4. В MenuBuilder отсутствуют production direct calls для управления Janus mountpoint lifecycle.
5. Нет lifecycle-to-direct fallback ни в backend, ни во frontend.
6. Все video entry points используют единый `RemoteSessionUseCase` или thin facade над ним.
7. Ошибки lifecycle start fail-closed и не создают active stream/session.
8. Compensating stop использует только утверждённые lifecycle/IoT APIs.
9. Старый UI остаётся работоспособным через единый новый flow.
10. Все backend/frontend lint, type, test и build проверки зелёные.
11. Regression tests доказывают отсутствие direct ingress/Janus calls.
12. Длительный reconcile-regression тест успешно удерживает поток минимум 180 секунд и не менее трёх reconcile-интервалов.
13. Для тестовой video-session нет orphan cleanup route/mountpoint.
14. RTP/bytes и browser freshness подтверждают непрерывность трансляции.
15. Штатный и повторный stop корректны и идемпотентны.
16. Выполнены project-local deploy, smoke и rollback readiness.
17. Отчёт и detached candidate содержат реальные SHA-256, commit, branch, tests, deploy/smoke evidence и отсутствующие секреты.
```
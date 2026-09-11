# Шаг 4 — ревизия контрактов Video / Remote Input по серверному инциденту 2026-09-11

## 1. Статус и границы пакета

Это результат SSH-диагностики и задания для последующей реализации, **не отчёт об исправлении или успешном E2E**. Проверен хост `87.242.100.34`; исходники приложений, конфигурация и контейнеры на нём не обновлялись, терминальные команды не отправлялись. Для сверки прочитаны логи и копии четырёх исходных файлов из запущенного `app1`. Временные материалы не являются частью пакета.

Локальные диагностические копии удалены. На сервере остался созданный для выгрузки каталог `/home/user1/contract-audit-20260911-1129` с `schemas.py`, `service.py`, `leases.py`, `publisher.py`. Это отдельные копии, не рабочие файлы приложения. Их удаление не выполнялось: по AGENTS.md требуется явное подтверждение пользователя. Очистка должна затронуть только эти четыре файла и опустевший каталог; изменение/синхронизация runtime-кода при этом не требуется.

Предыдущий [обзор шага 3](prompt_step3_stacks_overview.md) содержит заявления о завершении исправлений. Их нельзя использовать как доказательство совместимости: инцидент ниже подтверждает несовместимый JSON даже при наличии поддержки `lease_renew` с обеих сторон.

### Task intake

- Тип задачи: диагностика + документация; текущие изменения только в `prompts/`.
- Владельцы: `app1` — server lease и ctl producer/consumer; `l4desk` — local lease/watchdog; MenuBuilder BFF — доверенная HTTP/WS-граница; UI — жизненный цикл пользовательской сессии; l4media — медиатранспорт и свежесть RTP; Ops — конфигурация, доступ и наблюдаемость.
- Поток: UI → BFF → app1 → RabbitMQ / терминальный Mosquitto → l4desk → ACK/event → app1 → BFF → UI. Медиатракт проверяется отдельно.
- Инварианты: tenant/owner/scope, fail-closed, изоляция MQTT-топиков, отсутствие секретов в документах, никаких изменений общей БД ради этого дефекта.
- Выполнено: сопоставление журналов, runtime-исходников app1 и локальных потребителей. Не выполнено: исправления, тесты приложений, браузерный E2E, диагностика процесса на Windows-терминале, деплой.
- Готовность документов: отдельные владельцы, факты и гипотезы, общий wire-контракт, критерии совместимости и порядок передачи результатов.

## 2. Серверные свидетельства

`[MCP Ops Readiness: UNAVAILABLE]`: инструменты server-ops отсутствовали в этой сессии. Использован разрешённый SSH с `-n`, `BatchMode=yes`, `sudo -n docker`. Pre-flight: available RAM 2265 MiB, root disk 45%, load 0.26. Это снимок на момент проверки, не постоянная гарантия.

Для повторной выборки из PowerShell:

```powershell
ssh -n -o BatchMode=yes -o ConnectTimeout=10 -i d:\.ssh\id_ed25519 user1@87.242.100.34 'sudo -n docker logs --timestamps --since 2026-09-11T10:55:00Z --until 2026-09-11T10:55:04Z app1'
```

Основное окно: `2026-09-11 10:53:25–10:55:10 UTC`; ошибки завершения уточнялись в `10:55:00–10:55:04 UTC`. Часы терминального лога — UTC+3, JSON timestamp с `Z` — UTC. Не сопоставлять дробные миллисекунды разных машин как синхронизированные часы.

Корреляция (идентификаторы событий, не credentials):
- `device_id=773`, `SN=a4b0000773c82116d210826`;
- `lease_id=831028de-8f1a-42b9-986a-6a2ee4e5e578`;
- `stream_instance_id=8cbcd134-f05e-48fd-bef7-0db96ffab8ed`;
- `stream_start.command_id=dbca37f5-5b0c-427c-a009-a4ddccfe28d0`.

| Время UTC | Источник | Наблюдение |
|---|---|---|
| 10:53:32.461 | app1 `remote_input.log` | Создана server lease |
| 10:53:32.688, время из терминального лога | l4desk, предоставлен пользователем | FFmpeg запущен, событие running |
| 10:53:32.892 | app1 | ACK started для указанного stream_start |
| 10:53:37.642 и далее | app1 | AUDIT lease_keepalive; затем Drop invalid ctl payload, `ack.command_id`: invalid UUID, пустая строка |
| 10:53:37 / 42 / 47 / 52 | l4desk | Получен lease_renew, `Invalid command_id format: ''` |
| 10:53:52.908, время из терминального лога | l4desk | Local lease expired, fail-closed stop; остановка примерно через 20,2 с после старта |
| 10:53:53.471 | app1 | Stream event updated: stopped, lease_expired |
| 10:53:53.472 | MenuBuilder BFF | Stream state event received upstream: stopped, тот же stream_instance_id |
| 10:54:00 / 10 / 20 | l4media-ingress | STREAMING; счётчики неизменны: RTP 3867, RTCP 4, 4463 KB |
| до 10:54:59.410 включительно | app1 | Продолжаются lease_keepalive после остановки FFmpeg; отрицательные ACK всё ещё отбрасываются |
| 10:55:01.246 / .260 / .313 | app1 | Три audit/revoke события одной lease, `reason=released`, не lease_expired |
| 10:55:01.263 / .315 | app1 HTTP | Два DELETE одной lease → 204 |
| 10:55:01.264 | BFF | WebSocket session finished, `reason=client_release`; затем отдельный DELETE из UI |
| 10:55:02.621 / .626 | app1 / BFF | POST keepalive → 404 на обоих уровнях |

**Уточнение предыдущего анализа:** серверная аренда не исчезла сразу после локального `lease_expired`. Она продолжала продлеваться; наблюдаемый 404 появился после явного release. Потеря события между app1 и BFF также не подтверждается: BFF получил stopped. Доставка и применение этого события браузером ещё требуют проверки.

### Охват проектов и пределы наблюдений

| Проект / runtime | Что проверено | Вывод / ограничение |
|---|---|---|
| app1 / iot-rpc-rest-app | Docker HTTP-логи; `/home/user1/iot-rpc-rest-app/logs/remote_input.log`; runtime `core/remote_input/{schemas,service,leases,publisher}.py` | Подтверждены несовместимая сериализация, отбрасывание ACK, release перед 404 |
| MenuBuilder backend | Docker HTTP/WS-логи | Получил stopped, закрытие client_release, два upstream DELETE, последующий keepalive 404 |
| MenuBuilder frontend | Лог браузера пользователя + локальный код | Сервер не содержит браузерную консоль; точное действие оператора и runtime-бандл не восстановлены |
| l4desk | Лог пользователя + локальный протокол | Нет доступа к Windows-журналу супервизора; причина запусков каждые ~30,8 с до стрима неизвестна |
| l4media-ingress | Docker stats/log | Открытый transport остаётся STREAMING без роста RTP минимум 20 с |
| l4media-janus | Выдержки Docker-лога | Mountpoint уже существовал, был пересоздан; deprecated create API; подробные логи включают PIN. Это не доказанная причина watchdog-stop |
| l4media-nginx, nginx-default, nginx-mutual-legacy-nginx-mutual-1 | Docker-логи выбранных интервалов, log driver json-file | В точечных выборках нет строк. Файловые access/error logs могут быть отдельными; отсутствие stdout не доказывает отсутствие ошибок |
| rabbitmq | Docker-логи | У других SN: client_id/cert mismatch (`_extra`, код 133) и configure access refused для MQTT subscription queue / subscribe_error. Не связывать с 773 без корреляции |
| processing-backend | Docker-логи, контрольная выборка 10:53:50–55 | Payment/gategauge HTTP 200; участие в дефекте аренды не подтверждено. Полный функциональный аудит платежей не выполнялся |
| mcp-pin-server | Docker-логи окна | Строк нет; участие в keepalive не подтверждено. Работоспособность всех PIN-операций не проверялась |

Выборки не являются полным аудитом всех функций всех проектов. Для многословного Janus одна расширенная команда была прервана по времени/лимиту вывода; выводы основаны на сохранённых выдержках, не на утверждении об отсутствии иных ошибок. Для исторического окна не применять `--tail` так, чтобы оно исключало нужные записи. Не сохранять сырые логи с PIN/JWT/cookie в Git.

### Привязка к версиям

Локальный HEAD при сверке: `63ce6a7`; в рабочем дереве были посторонние изменения контекста, они не включены в этот пакет.

| Container | Image ID (SHA256) | StartedAt UTC |
|---|---|---|
| app1 | `b299c14594d3f48a185a5dc8f557eaf16a73571f4f38f0743da5e6ba8cb413da` | 2026-09-11T10:45:44.233841593Z |
| menubuilder-backend | `237b4f56eda058b03c188510ae66a845bfe5c58560344313d3bb827f9c1e42d6` | 2026-09-11T10:09:36.309366004Z |
| l4media-ingress | `d1d6d23200c4b3d5a169e6fac09662d95416fabf0c224e2c534328db2cbd34d8` | 2026-09-07T22:17:26.160768102Z |

У этих трёх контейнеров `RestartCount=0`, `OOMKilled=false` на момент inspect. Это не исключает прежнее пересоздание контейнеров и не объясняет рестарты Windows-агента.

SHA256 runtime-исходников app1: `schemas.py` — `4f140be044080a47354a8c8c1e38504290898f7166151d5fb9fad0fcd3d455f8`; `service.py` — `cc01bdf0f4956b8ed2bb7ccb9a662ae3aed96d7ff6bae50c8fcc324b886a78e8`; `leases.py` — `4d3a12637b65f99fd2e525e6a50aa82224c745033abd39145caa04a494aff3f0`; `publisher.py` — `1994cf1a841255f5d2841041c537dd59804c06b091ae71e2bc57e88b840d36e9`. Git-ревизия внешнего checkout app1 не установлена; определить её до реализации.

## 3. Реестр проблем и владельцев

| ID / приоритет | Подтверждение / вопрос | Владелец |
|---|---|---|
| F1 / P0 | CtlLeaseRenew хранит `cmd_id`; обычный `@property command_id` не попадает в `model_dump(mode="json")`. Publisher передаёт этот dict; agent ожидает `command_id`. В headers идентификатор есть, в ожидаемом поле JSON — нет | app1 + l4desk |
| F2 / P0 | keepalive touch/publish возвращает успех без проверки ACK в этом методе; агент отклоняет команду, app1 отбрасывает ACK с пустым UUID. Server lease alive ≠ local lease renewed | app1 + l4desk |
| F3 / P1 | После client_release общей lease HTTP keepalive остаётся активен. WS release, BFF cleanup и HTTP DELETE дают повторные освобождения | UI + BFF + app1 |
| F4 / P1 | Stopped дошёл до BFF, но незавершённая UI-сессия и stale media могут показывать прежнее состояние; применение события в браузере не доказано | UI + BFF |
| F5 / P1 | STREAMING определяется не свежестью пакетов; RTP-счётчик не растёт при живом соединении | l4media + BFF + UI |
| F6 / P1 | В stream_start expires_at_ms вычисляется из timeout команды; в lease_renew — из expires_at аренды. Назначение поля/TTL нужно согласовать | app1 + l4desk |
| F7 / P2 | Рестарты l4desk до стрима (~30,8 с); причины/exit code/PID супервизора неизвестны | Windows tools |
| F8 / P2 | Отдельные ошибки MQTT client_id/cert и ACL у других терминалов; в том же окне provisioning выставляет ограничительные permissions | Ops + владелец provisioning app1 |
| F9 / P1 | Janus debug выводит PIN; слишком подробный лог мешает корреляции, mountpoint recreate/deprecated API требуют ревизии | l4media + Ops + BFF |

## 4. Изолированные задания

| Проект / стек | Промпт | Основной результат |
|---|---|---|
| iot-rpc-rest-app / Python 3.14, FastAPI, Pydantic, RabbitMQ | [app1](prompt_step4_agent_iot_rpc_rest_app.md) | Wire JSON + подтверждённое продление + lease lifecycle |
| MenuBuilder backend / Python 3.14, FastAPI, httpx | [BFF](prompt_step4_agent_menubuilder_backend.md) | Согласованная HTTP/WS-семантика, scope/owner, события и cleanup |
| MenuBuilder frontend / React 19, TS, Vite | [UI](prompt_step4_agent_menubuilder_frontend.md) | Единый владелец сессии, таймеры, terminal events и честный UI |
| tools/l4desk / C, Win32, MSVC x86/x64 | [Native](prompt_step4_agent_tools_l4desk.md) | Строгий ctl consumer, watchdog, negative fixtures, диагностика restart |
| l4media / ingress, Nginx, Janus, RTP/WebRTC | [Медиа](prompt_step4_agent_l4media.md) | Свежесть RTP, эпохи потока, управление mountpoint, безопасный лог |
| RabbitMQ, Nginx, Compose и наблюдаемость всех проектов | [Ops](prompt_step4_agent_ops_contracts.md) | Корреляция, ACL triage, release/rollback и пробелы логирования |

## 5. Общий контракт, который команды должны согласовать

Это требования следующего этапа, не утверждение, что они уже реализованы. До изменения протокола заполнить таблицу фактическими JSON fixtures producer и consumer, именами полей/типами, обязательностью, default/alias, error/result enum и политикой совместимости.

| Граница | Обязательные решения / инварианты |
|---|---|
| UI → BFF → app1 HTTP/WS | lease_id, доверенные owner/session/org/scope; единый владелец stream/input-аренды; detach input ≠ неявное уничтожение живого stream. Если API не умеет detach/downgrade, согласовать явное завершение всей сессии или расширение API до реализации |
| app1 → l4desk ctl v1 | Каноническое wire-поле `command_id` (UUID); lease_id; v/type; назначение expires_at_ms; SN-binding из доверенного topic; no retain. AMQP `correlation_id` и header `correlationData` не заменяют JSON-поле |
| Command expiry / lease expiry | Разделить validity окна команды, ожидание ACK и deadline локального разрешения; положительный будущий deadline, единицы epoch milliseconds UTC, пределы TTL/skew. При введении поля — версия/совместимость, а не внезапная смена смысла v1 |
| Renew / ACK | Новый command_id на новое продление; QoS-повтор той же команды сохраняет ID. ACK означает принятие конкретного deadline, не только publish/PUBACK. Невалидный ID не превращать в успешный ACK; диагностировать без поддельного UUID |
| Events / status | lease_id и stream_instance_id/эпоха, state + reason; поздний stopped старого потока не завершает новый. Presence не должна воскрешать stopped из устаревшего snapshot |
| Stop / release | Идемпотентный результат для уже остановленного своего потока; не поглощать произвольные 409/403, не уничтожать mountpoint другой/новой аренды. Остановить таймеры до release; запоздалый ответ старой сессии не влияет на новую |
| Media status | transport_connected отдельно от fresh RTP и decoded frames; согласовать deadline stale и приоритет terminal stopped над закэшированным STREAMING |

Не форсировать `stream_mode="desktop"` из одного scope и не считать отсутствие streamMode разрешением ввода. Camera→desktop требует подтверждённого реального переключения источника. Не отключать fail-closed и не увеличивать TTL как замену исправлению F1.

### MQTT scope-gate

Этот пакет **не разрешает изменение MQTT-клиента без обязательного уточнения типа**. Перед такой реализацией спросить: «Какой тип MQTT-клиента создаётся: main_app или extra_service?». Есть расхождение с локальным AGENTS.md, где отдельно описан `svc_desk`: фактический l4desk использует именно его. Явно согласовать это исключение с пользователем; нельзя самостоятельно переводить агент на `extra_service` или менять retained presence-топик. До ответа допускаются read-only ревизия и проектирование тестов. Для выбранного типа обязательны согласованные will до CONNECT, online после CONNACK, offline перед DISCONNECT; команды/ACK/events без retain.

## 6. Порядок выполнения и общая проверка

1. В каждом checkout зафиксировать ревизию, границы и воспроизводящий тест. Перед исправлением показать падение теста на действующем wire-формате, а не только на вручную «правильном» JSON.
2. app1 + native согласуют F1/F2/F6 и публикуют обезличенные golden fixtures. Тестировать сериализованный объект через реальный publisher boundary → parser агента → ACK parser app1.
3. app1 + BFF + UI согласуют F3/F4: lease ownership, detach/release, state/reason, ошибки. Медиа-команда согласует F5/F9. Ops параллельно расследует F8 без ослабления ACL.
4. Прогнать релевантные тесты каждого изменённого проекта и downstream-потребителей; собрать Python/TS/native по их правилам. Нет изменений кода — нет ненужного pytest/сборки приложений.
5. Перед runtime/E2E отдельно согласовать стенд и терминал. Матрица: desktop и camera; просмотр без включённого remote input; ввод без движения мыши; отключение только input; переключение терминала; повторный stop/release; 404/403/409/timeout; late ACK/event старой эпохи; отсутствие/нулевой/прошлый expiry; QoS duplicate; restart/disconnect.
6. Положительная сессия ≥120 с: каждое ожидаемое продление имеет коррелируемый ACK и увеличение локального deadline; нет invalid UUID/lease_expired при действующем продлении; в динамической тестовой сцене растут RTP и decoded frames. Отсутствие движения мыши не должно мешать продлению.
7. Отрицательный сценарий: прекратить renewal на согласованном стенде → stop в документированный deadline + grace, release input, отсутствие recovery. Отдельно unexpected_exit при ещё валидной аренде → только bounded recovery; не убивать все ffmpeg-процессы на машине.
8. UI переводит текущий поток в завершённое состояние после соответствующего stopped; после начала local teardown не запускает новых keepalive старой lease. Допустимый уже отправленный запрос безопасно игнорируется по generation. Новая сессия не затрагивается.
9. Внедрение — только отдельным разрешённым релизом на указанный хост. Образы/бандлы/binary hashes, порядок совместимых версий и rollback согласовать до выкладки; без hot-edit исходников внутри production-контейнера.

## 7. Handoff каждому владельцу

Вернуть: ревизию producer и consumer; diff контракта; воспроизведение до/после; fixtures и реальные команды тестирования с результатами; таблицу выполненных/не выполненных E2E; версии/артефакты; порядок rollout/rollback; оставшиеся блокеры. Обновить авторитетные спецификации при утверждённом изменении контракта. Не объявлять весь этап выполненным по одному HTTP 200, успешной сборке или устаревшей карточке контекста.
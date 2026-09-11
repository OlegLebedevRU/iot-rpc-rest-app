# PROMPT AGENT — шаг 4: tools/l4desk, ctl consumer и безопасность продления

Ты Senior Windows/C Systems инженер: C/Win32, MSVC `/MT`, x86 + x64. Разрешённый проект — `tools/l4desk`, его tests/README/CHANGELOG. `tools/l4superv` — только адресная read-only диагностика запуска при необходимости; изменение супервизора/пакетирования согласовать отдельно. Не трогать backend/frontend/другие утилиты.

Прочитай [общий отчёт](prompt_step4_stacks_overview.md), F1/F2/F6/F7 и [задание app1](prompt_step4_agent_iot_rpc_rest_app.md). До изменения MQTT-клиента пройти обязательный опрос типа клиента из общего отчёта и разрешить конфликт правил main_app/extra_service против фактического svc_desk. Не выбирать тип самостоятельно, не переводить ctl presence на занятый другим сервисом dev/{SN}/svc. До согласования — только ревизия.

## 1. Факты

- На терминале 773 lease_renew приходит с периодом ~5 с, но command_id пуст для parser. Агент останавливает поток по local lease expiry +5 с grace примерно через 20,2 с после старта.
- В runtime app1 DTO сериализует `cmd_id`, тогда как `ctl_protocol.c` извлекает `command_id` и проверяет его до ветки lease_renew.
- Отрицательный ответ агента с пустым command_id app1 отбрасывает как invalid UUID. Не «чинить» это отключением валидации на любой стороне.
- Логи стартов 13:51:42.529 / 13:52:13.306 / 13:52:44.121 дают ~30,8 с; PID/exit reason супервизора неизвестны. Между запуском FFmpeg и lease_expired нового старта агента нет.
- Существующие тесты с вручную заданным корректным command_id не доказывают совместимость producer JSON.

## 2. Задачи после scope-gate

1. Сверить `src/ctl_protocol.c`, `src/ffmpeg_supervisor.c`, `src/mqtt_client.c`, соответствующие test_ctl_protocol/test_orchestrator и документацию. Указать реальную сборку/версию тестируемого бинарника, не доверять только строке v1.0.0.
2. Добавить failing contract fixture из фактического сериализатора app1 (`cmd_id` без command_id), затем согласованный canonical fixture `command_id`. Основное исправление producer принадлежит app1; native не должен без согласования принимать произвольные aliases и навсегда скрывать несовместимость.
3. Проверить обязательные поля renew: UUID, совпадающий lease_id, нужная эпоха, допустимое state, положительный будущий expires_at_ms и верхняя граница по контракту. Missing/zero/past/overflow должны отклоняться, не давать успешный ACK без реального продления.
4. Согласовать command deadline vs local lease deadline и grace. Не добавлять recovery после lease_expired; renew не должен воскрешать stopped/revoked lease или запускать FFmpeg. При допустимом повторе одного ID — повторяемый ответ без новых побочных эффектов; новый renew имеет новый ID. Проверить ordering expiry/dedup и ограничение cache.
5. ACK успешного renew должен коррелироваться с command_id/lease_id и означать принятый local deadline по согласованной схеме. Не отвечать фиктивным UUID на malformed command. Для неидентифицируемого сообщения согласовать безопасную диагностику, не выдавая её за коррелируемый ACK.
6. Добавить диагностический след: command type/ID, lease/epoch, old/new deadline, accepted/rejected reason, supervisor state. Не логировать секреты, PIN, auth и полный MQTT payload. Дубликаты не должны создавать log flood.
7. Проверить fail-closed в running/restarting/backoff, cancel recovery на stop/release, input_release_all, reconcile orphan. Lease expiry и command expiry — не заменять произвольно одинаковыми числами; future/monotonic bounds согласовать с app1.
8. Для F7 подготовить адресную диагностику на согласованном Windows-терминале: PID/parent PID, exit code, supervisor health timeout/restart reason, версия/hash/config fingerprint без секретов, session ID, MQTT client-id conflict. Не объявлять watchdog супервизора причиной лишь по периоду 30 с и не останавливать все процессы по имени.

## 3. Проверки

- Build x86 и x64 через `cmd /c build.cmd all` из `tools/l4desk`; выполнить `cmd /c run_tests.cmd` и все относящиеся к изменению native suites. Проверить, какие архитектуры реально покрывает runner, недостающую проверку выполнить явно.
- Golden producer JSON → реальный C parser → serialized ACK → реальный parser app1. Не заменять этот тест сравнением двух вручную набранных строк.
- Матрица: missing/wrong UUID; неправильная lease; absent/0/past/huge expiry; дубликат; late duplicate после expiry; новая generation; stopped/restarting; renew во время backoff; stop против renewal; reconnect и orphan reconcile.
- На согласованном стенде ≥120 с с регулярным renewal: ACK + наблюдаемый сдвиг local expiry + живой FFmpeg. Затем прекращение renewal → fail-closed и отсутствие restart. Отдельно controlled unexpected_exit **только известного FFmpeg PID тестовой сессии** при ещё валидной lease → bounded recovery.
- Если меняется presence после согласования типа: will до CONNECT, online после CONNACK, offline→DISCONNECT при штатном выходе, LWT при crash; retain только для presence, не для действий/ACK/events.

## 4. Результат

Верни contract fixtures, результат failing/passing теста, бинарные hashes x86/x64, evidence watchdog/recovery, причины и неизвестное по перезапускам. Обнови протокольную документацию после согласования. Доставку/упаковку suite и запуск на рабочем терминале выполнять только отдельным согласованным этапом; нельзя считать локальную сборку доказательством обновления терминала.
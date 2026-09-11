# PROMPT AGENT — шаг 4: app1 / iot-rpc-rest-app, синхронизация ctl и lease lifecycle

Ты Senior Python Backend инженер (Python 3.14, FastAPI, Pydantic v2, async I/O, RabbitMQ). Работай в согласованном checkout `iot-rpc-rest-app`; это отдельный проект, не подкаталог MenuBuilder. Сначала найди его AGENTS.md, ревизию и реальные test/build-команды. Runtime-копия не заменяет разрешённый checkout.

Обязательный контекст: [общий отчёт шага 4](prompt_step4_stacks_overview.md), особенно F1/F2/F3/F6/F8 и общая матрица. Этот промпт разрешает локальную ревизию/исправления в данном проекте, **не production hot-edit, деплой или активные команды терминалам**. Иные проекты — read-only границы; необходимые изменения передай владельцам.

## 1. Подтверждённый дефект

В запущенном app1 на 2026-09-11:
- `core/remote_input/schemas.py:204–215`: `CtlLeaseRenew.cmd_id` — поле; `command_id` — обычный `@property`.
- `publisher.py:49–85`: в transport передаётся `command.model_dump(mode="json")`; `command_id` используется для correlation headers, но не добавляется в JSON.
- `service.py:272–326`: lease touch → publish → успешный LeaseResponse, без ожидания подтверждения агента в этом методе.
- Агент читает `command_id`, получает пустое значение; server `mqtt_bridge:110` отбрасывает ответ `ack.command_id` как invalid UUID. HTTP keepalive при этом успешен.
- `service.py:555–570`: stream_start.expires_at_ms берётся из timeout команды, renew.expires_at_ms — из server lease. Семантика срока требует согласования.

Для 773 server lease `831028de-8f1a-42b9-986a-6a2ee4e5e578` продолжала продлеваться после stopped в 10:53:53Z. В 10:55:01Z зарегистрированы три `released`; следующий keepalive → 404. Не исправлять это как отсутствующий маршрут и не скрывать 404 возвратом 200.

## 2. Ревизия и реализация

1. Воспроизвести F1 до исправления тестом **реального JSON** CtlLeaseRenew на границе publisher. Сравнить поля всех ctl-команд, ACK/NACK, events и WS DTO, а не только одно имя.
2. Сделать каноническим wire-поле `command_id` UUID. Обычный property/AMQP correlation_id недостаточен. Если нужны legacy aliases, согласовать их входную/выходную политику; не отдавать лишние поля strict consumers. Новое продление — новый ID, повтор публикации той же команды — тот же ID.
3. Согласовать с l4desk envelope: обязательные v/type/lease_id/deadline; необходимость sn/issued_at_ms/stream_instance_id; единицы UTC epoch ms; ограничения ttl_sec; command validity vs local lease deadline vs ACK timeout. Не добавлять поле или менять его смысл без compatibility fixture обеих сторон.
4. Определить семантику успешного keepalive: принятие server lease, publish и terminal accepted — разные состояния. Нужны корреляция ACK, timeout/NACK и наблюдаемость applied deadline. Либо API ждёт bounded ACK, либо явно сообщает pending/terminal health; выбор и HTTP/WS DTO согласовать с BFF/UI. Не считать отсутствующий ACK успешным продлением терминала.
5. Проверить ошибки публикации после touch, конкурирующие HTTP/WS renewal, backpressure, поздний ACK, ограничение pending/cache и races release↔renew. Отозванная lease не должна воскресать от touch/ACK. Не превращать timeout в бесконечное продление авторизации.
6. Согласовать владение stream/input lease. Повторное acquire того же владельца и scope upgrade не должны менять фактическую camera mode на desktop по одному scope. Detach управления не должен неожиданно revoke аренду активного просмотра; если split/downgrade не поддержан, явно согласовать продуктовую семантику до реализации.
7. Ревизовать release: повторный вызов для уже завершённой своей lease безопасен; cross-tenant/owner/session по-прежнему запрещены. В audit различать реальный переход и duplicate/no-op, канал HTTP/WS, reason, request_id и generation. Устранить двойные побочные эффекты и гонки, а не только шум логов.
8. Для stream_event stopped/failed очищать только соответствующую эпоху потока; распространять state + reason + IDs в WS/status. Устаревший presence/ACK не должен вернуть прежний running. Отдельно определить, завершается ли server lease или лишь stream state.
9. Невалидный ACK с пустым command_id диагностировать отдельно; не ослаблять UUID-валидацию и не генерировать фиктивный ID для pending resolution. В логах нужны command type, причина rejection, transport, latency, без payload с секретами.
10. По F8 вместе с Ops проверить provisioning MQTT permissions: отказ configure queue и последующее выставление `^$` наблюдались у другого SN. Проверить race/downgrade политики, не добавлять wildcard и не связывать автоматически с 773.

## 3. Проверки

- Обязательная failing-before/passing-after проверка сериализации; fixture, произведённый app1, потребляется native-тестом, native ACK проходит Pydantic parser app1.
- Матрица: HTTP/WS renewal; publish error; ACK timeout/NACK; invalid/missing ID; TTL absent/zero/past/out-of-range; duplicate до/после expiry; late ACK; release+renew race; новая lease после старой; другой tenant/user/session; unknown lease.
- Camera lease + acquire input не должны ложно установить desktop. Stopped старой эпохи не очищает новый stream. Нельзя заявлять идемпотентность на основании подавления всех 409.
- Все релевантные suites в проекте и контрактные downstream-тесты. Python checks через `uv run ruff check`, `uv run ruff format --check`, `uv run pyright`, `uv run pytest` с фактическими source dirs проекта. При исправлении форматирования — штатные ruff fix/format. Не использовать skip ради зелёного отчёта.
- E2E ≥120 с и fail-closed сценарий — только после согласования стенда. HTTP 200/PUBACK без terminal ACK и роста local expiry не является успехом.

## 4. Результат

Верни контрактную таблицу до/после, версии схемы/совместимость, воспроизведение, тестовые fixtures, семантику ошибок и release, remaining risks. Передай BFF/UI DTO/state/reason/health; l4desk — точный JSON и expiry policy; Ops — запрос на адресную ревизию provisioning. Обнови авторитетную документацию в своём проекте, не объявляя production исправленным без отдельной выкладки и проверки.
# PROMPT AGENT — шаг 4: MenuBuilder BFF, HTTP/WS-контракты видеосессии

Ты Senior Python Backend инженер: Python 3.14, FastAPI, SQLAlchemy async, httpx. Изменения ограничены `MenuBuilder/backend` и его тестами/документацией. Не менять ProcessingBackend, shared ORM, внешний app1, frontend или native-клиент; контрактные изменения передавать владельцам.

Прочитай [общий отчёт](prompt_step4_stacks_overview.md), F3/F4/F5/F9 и согласованный результат [app1](prompt_step4_agent_iot_rpc_rest_app.md). Деплой/серверные правки требуют отдельного разрешения. Цель — исправление поведения, не поглощение всех upstream-ошибок.

## 1. Факты и точки ревизии

- `app/routers/video_control.py`, `app/services/iot_client.py`, `app/routers/video.py`, соответствующие schemas/tests.
- 10:53:53.472Z: BFF получил upstream `stopped` для 773, instance `8cbcd134-f05e-48fd-bef7-0db96ffab8ed`.
- 10:55:01.264Z: WS закончился с `reason=client_release`; cleanup вызвал upstream DELETE. Затем UI DELETE вызвал ещё один DELETE.
- 10:55:02.626Z: BFF вернул keepalive 404 от app1 для освобождённой lease. Роут существует, повторный деплой без изменения контракта не решит причину.
- В прошлой правке stream_stop поглощает любой 409. Это требует ревизии: mode/owner/epoch conflict нельзя автоматически считать «уже остановлен» и уничтожать mountpoint нового владельца.
- Ingress может сообщать STREAMING без свежих RTP. Успешный `/stats` не доказывает живое видео.

## 2. Задачи

1. Создать failing reproduction на цепочку WS release → cleanup DELETE + HTTP DELETE → поздний keepalive. Определить, какие вызовы являются допустимым idempotent fallback, а какие вызывают повторные побочные эффекты.
2. Согласовать с app1 и UI одного владельца release/renew общей lease. Различать detach управления, закрытие transport, завершение stream, revoke. Не удалять fallback вслепую: при обрыве сети cleanup обязан оставаться безопасным и ограниченным по времени.
3. Нормализовать типизированный error contract: HTTP status, стабильный code, безопасное message/detail, lease/generation при наличии. `lease_not_found/expired` не равно `route_not_found`; 403 сохраняет auth-смысл; temporary upstream failure не маскируется как успешное продление.
4. Согласовать новое keepalive DTO app1: server accepted/pending/applied или bounded ACK, deadline и terminal health. Не объявлять подтверждение агента по HTTP 200, если API этого не гарантирует. Проверить и HTTP, и WS.
5. Проверить передачу state/reason/lease_id/stream_instance_id в браузер и REST status. Stopped текущей эпохи имеет приоритет над старым cached running; поздний event старой lease не завершает новый stream. Кэши PIN/состояния привязать к владельцу/эпохе, а не только device_id.
6. Ревизовать stop idempotency: известные «уже остановлен/нет активного своего потока» → успешный no-op; invalid owner/session/tenant/epoch и неизвестный конфликт не скрывать. Mountpoint teardown/PIN cleanup только для соответствующего потока; не трогать нового viewer/owner.
7. Совместно с l4media определить session/status: transport connection отдельно от fresh RTP; timestamp/age/epoch отсутствует — состояние unknown, не автоматически live. Не менять публичный DTO без frontend compatibility tests.
8. Добавить структурную корреляцию WS close/release/renew: request_id, lease_id, generation, close reason, upstream code, направление. Не логировать JWT/cookie, PIN, authorization или полный upstream payload. Не менять секреты/производственную конфигурацию в этой задаче.

## 3. Тесты и критерии

- Сначала failing tests; затем все backend suites: `uv run pytest` из `MenuBuilder/backend`. Обязательны `tests/test_video.py`, `tests/test_video_stream_permissions.py` и все найденные WS/session/IoT-client downstream-тесты.
- Для auth использовать внутренний `create_access_token` с коротким TTL; проверять tenant, owner, session и строковый org_id на границе. Не генерировать токены из production-секретов.
- Проверить concurrent/duplicate DELETE, WS unexpected close, timeout, upstream 404/409/403/5xx, delayed response, start новой lease до завершения old cleanup, event out-of-order, camera→input.
- Для stop сохранить действующую защиту от известных idempotent результатов, но добавить отрицательные тесты неизвестного conflict и чужой эпохи. Не ослаблять assertions ради старого поведения.
- Из каталога backend: `uv run ruff check --fix app`; `uv run ruff format app`; `uv run pyright app`; `uv run pytest`. Изменённые тесты проверить по принятым настройкам проекта. Не запускать чужие приложения при отсутствии их изменений/зависимостей.

## 4. Передача

Верни контракт HTTP/WS и обработку каждого кода/close reason, reproduction до/после, тесты, доказательство безопасности cleanup новой lease, согласованные fixtures для frontend/app1. Production/E2E отмечать отдельно: это не выполнено самим фактом локальных тестов. Проверка route без авторизации 401/403 не доказывает успешный renew действующей аренды.
# PROMPT AGENT — шаг 4: Ops, RabbitMQ/Nginx и межпроектная наблюдаемость

Ты DevOps/SRE инженер: Linux, Docker Compose, RabbitMQ MQTT/AMQP, Nginx, TLS, структурные логи. Задача — ревизия инфраструктурных контрактов и подготовка проверяемого плана исправлений, не автоматическое изменение production.

Хост только `ssh -n -i d:\.ssh\id_ed25519 user1@87.242.100.34`. Docker через `sudo -n`. Прочитай [общий отчёт](prompt_step4_stacks_overview.md), F8/F9 и ограничения текущего AGENTS.md. Локальные изменения конфигурации — только в подтверждённом репозитории владельца; серверные правки/деплой/permission changes требуют явного разрешения и согласованного diff + rollback.

## 1. Evidence и независимые проблемы

- Дефект 773: payload cmd_id вместо command_id; lease release в 10:55:01Z, затем keepalive 404. Брокер доставляет renewal; не чинить это расширением ACL или увеличением сетевого timeout.
- RabbitMQ в 10:53:32 и 10:53:37Z отклоняет **другой** SN: cert client_id не совпадает с предоставленным `<SN>_extra`, Connect Reason Code 133.
- В 10:53:32.598Z ещё у другого SN: configure access к `mqtt-subscription-<SN>qos1` запрещён, subscribe_error. В том же окне устанавливаются permissions `^$`, `^$`, `^$`. Причинность и источник provisioning требуют корреляции, не предполагать, что это тот же терминал 773.
- Janus debug включает PIN и большой объём RTP/RTCP; нельзя сохранять raw logs в Git. Route/create конфликт обработан, не доказан как причина fail-closed.
- В точечных Docker-выборках nginx-default, l4media-nginx, nginx-mutual-legacy и mcp-pin-server нет строк. Это пробел наблюдаемости, не заключение «ошибок нет».

## 2. Read-only ревизия

1. Повторить pre-flight ресурсы/связь; при доступном MCP выполнить readiness, иначе `[MCP Ops Readiness: UNAVAILABLE]` и SSH fallback. Пороги RAM >300 MiB, root <90%, load <2.0. Не читать raw `.env`, private keys, secrets из inspect Env/compose config.
2. Зафиксировать имя контейнера, image ID/revision label, StartedAt, RestartCount/OOM, log driver и фактический log destination для всех десяти сервисов из общего отчёта. Не выводить целиком inspect или конфиги с credentials.
3. Для каждого проекта заполнить окно времени, источник stdout/file/journal, покрытие/ротацию/пропуски, время UTC и event/request IDs. Исторические окна выбирать `--since/--until`, не отсекать их произвольным --tail. Большие логи обрабатывать ограниченно и с redaction.
4. Проверить Nginx routing keepalive и WS upgrade на port 3000 без изменения сервера. По наблюдённому 404 путь уже достигает app1; distinguishing upstream_status/request_id важнее повторной проверки наличия роута. При пустом stdout установить безопасный источник access/error log; не копировать query JWT/cookie.
5. Для MQTT cert/client_id mismatch выяснить ожидаемый identity контракт внешнего bridge против localhost svc_desk и фактический client_id источника. Не разрешать arbitrary suffix через снятие cert-binding. Перед изменением любого MQTT-клиента — обязательный вопрос и согласование типа из общего отчёта.
6. Для configure queue denial сверить минимальные resource permissions и topic permissions, имена QoS subscription queues, vhost, provisioning/reconciliation владельца app1. Сопоставить изменения permissions со временем reconnect/subscribe. Не применять `.*`, не расширять права всех tenants и не считать resource ACL равным topic ACL.
7. Проверить критерии health: HTTP liveness, server lease, terminal ACK/local expiry, fresh RTP и viewer frames должны быть раздельными. Подготовить безопасные метрики rejected commands, renewal ACK timeout, duplicate release, stale media, invalid inbound UUID.
8. Согласовать request correlation через Nginx/BFF/app1/MQTT: command_id, lease/stream IDs, UTC timestamp, cause/transport. Убрать тела чувствительных Janus-запросов из будущей production log policy; оценить доступ к уже существующим логам и необходимость отзыва/ротации раскрытых PIN владельцем, не менять их самостоятельно.
9. Для processing-backend и mcp-pin-server подготовить только coverage/health evidence и перечень наблюдённых независимых ошибок. Без подтверждённого дефекта не открывать задачи изменения платежной логики, сертификатов или миграций общей БД.

## 3. Локальные проверки и подготовка релиза

- Для согласованных инфраструктурных diff — штатные syntax/config tests, минимальный ACL test на изолированном broker/vhost, негативный cross-tenant publish/subscribe и неправильный cert/client_id. Без live publish/subscribe на терминал в этой ревизии.
- Проверить redaction синтетическими PIN/JWT markers: в собранных логах значений нет, IDs для корреляции остались. Не брать реальные secrets для тестов.
- Собрать handoff от app1, BFF, UI, native и media: версии контрактов, producer→consumer fixtures, test/build evidence, поддерживаемые пары версий.
- Предложить последовательность совместимого rollout: исправление producer проверяется против deployed consumer; UI/BFF DTO согласованы; изменённые native/media компоненты вводятся по compatibility matrix. Не обновлять consumer/producer вслепую и не обещать, что один restart решит F1–F9.
- Подготовить точный список артефактов/image IDs, штатные команды доставки и возврата на предыдущую **совместимую** пару версий, проверку маршрутов и авторизованную E2E ≥120 с. Выполнение только отдельным разрешённым этапом; frontend live mount не требует restart при изменении только dist.
- Удалять только временные материалы/токены текущей задачи по правилам согласования; не трогать чужие логи, retention, состояния сервисов. Не коммитить scratch-скрипты, сырые дампы и credentials.

## 4. Итоговый отчёт

Таблица по всем проектам: evidence / confirmed defect / independent warning / unknown / owner / next check. Отдельно результаты ACL и logging, без смешения с 773. Указать блокеры (недоступные file logs, отсутствующий browser/terminal trace, неизвестный revision) и состояние каждого этапа. Не заявлять «все сервисы исправны» по отсутствию stderr и не запускать приложения/тесты чужих проектов при документационных изменениях.
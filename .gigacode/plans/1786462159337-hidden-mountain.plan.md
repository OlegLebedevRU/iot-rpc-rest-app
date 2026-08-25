# План: RFC-документ — Безопасная интеграционная шина RabbitMQ

## Цель

Создать архитектурный RFC-документ `docs/integration-bus-rfc.md` описывающий
безопасную шину интеграции через RabbitMQ для внешних доменных приложений
(например, `postamat-domain-service`).

**Без изменений в коде.** Только документ.

## Что включить в RFC

1. **Контекст и мотивация** — граница ответственности платформы vs доменного сервиса.
2. **Текущая архитектура (as-is)** — единый vhost, amq.topic, MQTT plugin, webhooks.
3. **Целевая архитектура (to-be)** — dedicated `integration.topic` exchange + per-org queues + `integration.commands` exchange.
4. **Routing key convention** — `event.raw.<org>.<sn>`, `event.domain.<org>.<sn>`, `snapshot.<org>.<sn>`, `status.<org>.<sn>`, `task.<org>.<sn>`, `error.<org>.<sn>`.
5. **Per-org queues** — автоматическое создание, TTL, durable.
6. **Обратный канал команд** — `integration.commands` exchange, формат сообщения, валидация.
7. **Безопасность** — dedicated RMQ user per tenant, vhost permissions, topic permissions, TLS (username/password + server TLS, mTLS опционально).
8. **Точки интеграции в коде** — где платформа будет публиковать в integration exchange.
9. **Формат сообщений** — JSON envelope с version, type, timestamp, org_id, device_sn, correlation_id, payload.
10. **Управление tenant'ами** — скрипт для создания RMQ user + queues + permissions (API позже).
11. **Пример: postamat-domain-service** — конкретный сценарий использования.
12. **Отклонённые альтернативы** — отдельный vhost, e2e binding на amq.topic, только webhooks, Kafka/NATS.
13. **ASCII-диаграмма** архитектуры.

## Выходной артеф��кт

- `docs/integration-bus-rfc.md` — единственный создаваемый файл.

## Верификация

- Документ соответствует стилю существующих docs/ (markdown, mermaid-диаграммы допустимы).
- Все routing keys, permissions, exchange names — конкретные, copy-paste ready.
- Нет конфликтов с существующей топологией (amq.topic, amq.direct, существующие queues).

# 📚 Документация LEO4

> Навигатор по интерфейсам и контрактам платформы. Основные страницы сверены с реализацией `master` на 09.10.2026.

[← Обзор репозитория](../README.md)

## 🧭 Выберите маршрут

| Кому | Порядок чтения |
| :--- | :--- |
| AI-интегратору | [Руководство AI-агента](ai-agent-integration-guide.md) → [REST API](rest-api.md) |
| Разработчику приложения | [REST API](rest-api.md) → [Задачи](1-task-workflow-doc.md) → [События](2-events-api-format-description.md) → [Webhooks](3-webhooks.md) |
| Разработчику устройства | [MQTT RPC](mqtt-rpc-protocol.md) → [Методы](method-codes-reference.md) → [Корреляция](correlation-data-guide.md) → [События MQTT](event-protocol-mqtt.md) |
| Серверному интегратору | [Руководство интеграции](server-integration-guide.md) → [Межсервисный API](internal-api-contract-v1.md) |
| Инженеру сопровождения | [Диагностика](remote-diagnostics-protocol.md) → [Сеансы и ввод](remote-input-protocol.md) → [Файловый менеджер v2](file-manager-v2.md) |

## 📡 Команды и результаты

| Документ | Содержание |
| :--- | :--- |
| [MQTT RPC](mqtt-rpc-protocol.md) | Топики, Trigger/Polling, конверты сообщений, повторы и результаты |
| [Клиентский поток](mqtt-rpc-client-flow.md) | Алгоритм устройства и диаграммы обмена |
| [Сквозной сценарий](sequence.md) | REST → MQTT → результат → событие |
| [Состояния задачи](task_states.md) | Значения статусов и переходы |
| [TTL](TTL.md) | Срок действия, порядок выборки и поздние результаты |
| [Correlation Data](correlation-data-guide.md) | Формат UUID и совместимость транспортных полей |
| [Матрица корреляции](mqtt-rpc-correlation-matrix.md) | Идентификаторы для каждого сообщения |
| [Реестр методов](method-codes-reference.md) | Команды и совместимость устройств |
| [Карта топиков](mqtt_topic_rules.md) | RPC, события, управление и файловый менеджер |

## 📨 События и REST

| Документ | Содержание |
| :--- | :--- |
| [Обзор REST API](rest-api.md) | Публичные ресурсы, авторизация и граница internal API |
| [Задачи REST](1-task-workflow-doc.md) | Создание, чтение, поиск и удаление задач |
| [События MQTT](event-protocol-mqtt.md) | Метаданные, payload, дедупликация, EVA и gauges |
| [События REST](2-events-api-format-description.md) | История, инкрементальное чтение и извлечение тегов |
| [Webhooks](3-webhooks.md) | Настройка подписок, HTTP-конверт и повторная доставка |
| [Типы событий](event-types-reference.md) · [Теги](event-property-tags.md) | Справочники payload, включая 75, 76 и 900–999 |
| [История пользовательских событий](user-event-history-iot-handoff.md) | Поиск событий 900–999 во внутреннем API |
| [Глоссарий](glossary.md) | Термины и различия между идентификаторами |

## 🛠️ Специализированные интерфейсы

| Контракт | Назначение |
| :--- | :--- |
| [Remote Diagnostics](remote-diagnostics-protocol.md) | Управление диагностикой через RPC и поток `out` |
| [Remote Input](remote-input-protocol.md) | Удалённый ввод и управление сеансом через `ctl` |
| [L4FM v2](file-manager-v2.md) | RPC запуска/продления/передачи и `fmc`/`fmr` для навигации и остановки |
| [Channel Probe](channel-probe.md) | Отдельная проверка транспорта на существующих топиках |
| [Межсервисный API](internal-api-contract-v1.md) | Закрытый control plane платформы |
| [Подключения и аудит](api-device-connection-and-audit-guide.md) | Контроль соединений устройств |

## 🚀 Эксплуатация и дополнительные материалы

[Выпуск app1](manual-app1-deploy-runbook.md) · [Инфраструктура RabbitMQ](manual-infra-and-rmq-deploy-runbook.md) · [Восстановление ACL](rabbitmq-acl-recovery.md) · [Отладка RPC](server-rpc-debug-runbook.md) · [Безопасность](../SECURITY.md) · [Разработка](../CONTRIBUTING.md).

Handoff, планы реализации, RFC и материалы в `exceptions/` сохраняют контекст отдельных работ. Для интеграции начинайте с текущих контрактов выше; исторические SHA и результаты проверок в handoff относятся к указанному в них выпуску.

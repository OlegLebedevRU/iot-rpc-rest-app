# Выпуск app1 в production

**Артефакт выпуска** — образ app1 из принятого SHA master. [Карта платформы](production-architecture.md) показывает, какие сервисы участвуют в проверке после переключения.

## Подготовка

Записать SHA, digest и ID работающего контейнера, перечень overlays, версию схемы IoT и состояние очередей. Проверить миграции между исходной и целевой ревизиями. При старте app1 выполняется Alembic upgrade; возврат контейнера оставляет новую схему в базе.

## Сборка на builder

Использовать чистый checkout принятого SHA. [registry_app1.py](../deploy/registry_app1.py) запускает проверки locked-окружения, публикует образ с уникальным тегом и записывает revision, tag и OCI digest. Для повторного запуска того же SHA скрипт проверяет сохранённый артефакт.

```sh
python3 deploy/registry_app1.py \
  --registry "$L4_IMAGE_REGISTRY" \
  --artifact-dir "$L4_RELEASE_ARTIFACT_DIR"
```

## Переключение одного сервиса

Сопоставить revision и digest в manifest с принятым SHA. На production использовать штатный deployer Etran либо адресный helper из общего runbook. Он подтягивает образ по digest, сверяет label и исходный контейнер, сохраняет действующие параметры, mounts и сети, затем выполняет адресное пересоздание. У сервиса остаётся его приватный env_file.

| Этап проверки | Ожидаемый результат |
|---|---|
| Образ и запуск | Ожидаемый revision и image ID, миграции прошли, внутренний `/docs` возвращает 200 |
| Доставка | FastStream подключён к RabbitMQ; команда тестового устройства получила ответ с ожидаемой корреляцией |
| Внешний потребитель | MenuBuilder видит разрешённое состояние, а подписчик получает изменения |
| Откат | Вернуть проверенный предыдущий digest с прежними overlays, если он совместим с текущей схемой. Повторить проверку RPC. |

[Общий порядок выпуска](https://github.com/OlegLebedevRU/etranprocessing/blob/main/docs/ops_run-production-stack.md) · [Инфраструктура и RabbitMQ](manual-infra-and-rmq-deploy-runbook.md) · [Восстановление ACL](rabbitmq-acl-recovery.md)

В ранней схеме образ собирали на целевом хосте или доставляли из GHCR. Прежние примеры команд доступны в [архивной редакции](https://github.com/OlegLebedevRU/iot-rpc-rest-app/blob/a1ab67c/docs/manual-app1-deploy-runbook.md).

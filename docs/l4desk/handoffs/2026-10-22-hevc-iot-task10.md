# TASK-10: локальная реализация IoT control plane

Дата: 2026-10-22. Ветка: `feat/hevc-iot-control-v2`.
Рабочая копия: `D:/.codex/worktrees/hevc-iot-task10`.

Runtime/source commit: `ac0410ae6352e2d9b50a3bd2f1b17f89c8b35bbb`.
Он содержит код, тесты, OpenAPI и документацию runtime-контракта.
Интеграционная база: `36814a1705216520bb841b6e52e57bdde07f9de7` (`origin/master`
после fetch). Включён immutable G0 commit
`e1cc22d6b5fc49bd3558402f9a8ca12247e6a97e` через cherry-pick
`7b5f1224666362ecb71f390057ed3ba863cf1ff6`.
Пакет G0 не менялся: revision `hevc-contract/2.0.0`, digest
`f065b967cd10c2c709fb394ef9e6c2ecf74f77de060d88c9a821cc9069766ac4`.

Уровень доказательства: **unit / ASGI / fakeredis**, не deployed/real-hardware.
**P1a не объявляется закрытым:** воспроизводимая контейнерная сборка ещё не
подтверждена, image digest отсутствует. Локальный Docker daemon недоступен
(`//./pipe/docker_engine`: file not found). Production/release builder по runbook
принимает только принятый `origin/master`; этот барьер не обходился ради feature
ветки. Сервисы production, registry и GitHub Actions не менялись; ветка локальная.

SHA-256 `git archive` runtime commit, два одинаковых независимых вычисления:
`32e6b9603dbe452c6160ea8e644813bbaa3f1798197adf71e6a1bc376ed65a17`.
Это воспроизводимость исходного архива, **не** digest контейнерного образа.

## Результат

Реальные CTL handlers читают v1/v2 раздельно. Добавлены типизированные wire-модели
и проверка нормативной schema, неизвестных полей, duplicate keys и 32768-byte
лимита v2. V1 модели и MQTT topics/client type `svc_desk` не изменены.
Capability требует live nonce/SN, свежего положительного probe, matching
agent/revision/source/geometry/session и серверной готовности HEVC. Startup любого
worker вращает общую negotiation generation; transport reconnect/offline и
изменение presence binding инвалидируют capability. Номер EXE не даёт HEVC.

Concrete descriptor фиксирован на эпоху; idempotency включает codec/profile/source,
полный descriptor, delivery и identities. Redis WATCH сериализует starts и
защищает от конфликтов/повторного использования stream/operation IDs. Старый
ранний `already_running` теперь сравнивает profile; несовместимый живой publisher
получает conflict. Ошибка HEVC завершает поток, сохраняет полный error до REST/BFF,
делает capability temporarily_unavailable и уведомляет подписчиков, в том числе
других Redis workers. Автоматического restart/fallback нет. STOP/cleanup адресует
свою эпоху, сохраняет первую terminal reason и ограничивает ожидание публикации.

Состояние v2 отделено от legacy Redis namespaces. Lease serialization дополнена
profile/version с defaults для старых записей и CAS updates. Продление использует
авторитетный lease deadline и v2 lease_renew, без выдуманного terminal ACK.
Изменений software inventory event75, сертификатных/billing/EVA контрактов,
SQL migration или etran ORM нет. Обобщённый durable session feed не расширялся:
полный video descriptor/error доступен через отдельное авторизованное video-state.

Новые/расширенные маршруты, flags, v1/v2 examples, хранение и drain/rollback:
[runtime contract](../contracts/video-control-v2.md),
[OpenAPI](../contracts/video-control-v2.openapi.json).
Оба feature gate выключены по умолчанию. HEVC chain gate нельзя включать до
TASK-40 только на основании unit tests.

Основные изменения: `core/remote_input/video_{models,wire,control,api}.py`,
runtime `video.schema.json`; `schemas.py` v1 оставлен без изменений;
`service.py`, `mqtt_bridge.py`, `leases.py`, `presence.py`, `publisher.py`;
`api/internal_v1/remote_input.py`, `core/config.py`, startup в `create_api_app.py`
и отдельная invalidation в transport connection handler `fs_queues.py`.
Тесты: `test_video_v2.py`, regression изменения live-source conflict в
`test_service.py`. Экспортёр: `deploy/export_video_openapi.py`.

## Проверки

* `uv sync --frozen`: PASS, Python3.14.7 и неизменённый uv.lock.
* `uv run --frozen pytest -q`: **737 passed, 7 skipped**. Все 7 skips — прежние
  тесты; новых skips не добавлено. Есть прежние deprecation/AsyncMock warnings.
* Новые tests: **78 passed**. Продуктовый resolver выполняет все24 PREPARE
  vectors; реальные handlers — все7 IoT lifecycle vectors (2 media_start vectors
  принадлежат TASK-20). Проверены schema fixtures в IoT scope, ASGI response/error,
  nonce/timeout/pre-query cache, legacy bootstrap-reader simulation, duplicate
  starts, mismatched READY, late error/STOP, lease/tenant/owner/session/source,
  Redis serialization/revoke и fan-out двух Redis workers/трёх подписчиков.
* Frozen verifier с digest pin и `--iot-source`: PASS, все30 schema fixtures,
  6 legacy fixtures, 24 PREPARE +9 lifecycle oracle cases, 61 unknown-property
  mutations. Actual unchanged v1 models совпадают со snapshots.
* `uv run python deploy/export_video_openapi.py --check`: PASS.
* Black для всех16 изменённых Python файлов: PASS. `black --check .` остаётся
  красным на23 прежних файлах; baseline G0 также содержит ровно23 таких файла.
* Ruff новых modules/tests/exporter: PASS. Полный `ruff check .`:772 замечание
  против777 на baseline G0; новых диагностик при сравнении file/code/message нет.
  Чужой lint debt не объявлен green и не исправлялся массово.
* Ty новых modules: PASS. По всей затронутой группе:36 прежних диагностик,
  столько же на baseline, без новых диагностик. В проекте не было отдельного
  настроенного type-check pipeline; использован `ty check --python .venv
  --extra-search-path app-service`.
* Compileall, git diff check и staged secret-pattern scan20 файлов: PASS.
* Docker/image build: **не выполнен**, daemon недоступен. Runtime broker/real Redis,
  Janus, BFF deployment/browser decode, x86/x64 native и real GPU: **не проверены**.

Внешние evidence logs находятся в `D:/.codex/hevc-plan/task10-*`;
`TASK-10-ARTIFACT.json` содержит runtime/source SHA и archive digest.

## Admission и взаимодействие с MenuBuilder

Read-only проверена закреплённая MenuBuilder база
`3e236dc5b3b92afc83d49b022b38d07bccfa82c4`:
`backend/app/routers/video_control.py` сохраняет owner checks перед WS (1682–1698)
и не освобождает stream/input lease по простому disconnect (1954–1964).
IoT one-active-lease/SN и owner/session checks сохранены и покрыты тестами;
чужая publisher/input lease не присваивается.

TASK-30 остаётся обязан исправить существующий frontend `streamInstanceId:"viewer"`
(`video-surveillance.tsx:666`) и отделить viewer detach от общего
`onReleaseRequest`, вызывающего stopDeviceStream (`:301`).
`sessionLifecycle.ts:144` фильтрует события по stream UUID, поэтому подстановка
реального publisher ID обязательна. Это статический cross-repo аудит, не совместная
runtime-приёмка нового MenuBuilder. Ни новых independent viewer leases, ни обхода
admission в TASK-10 нет. Отдельный дизайн:
[follow-up](hevc-viewer-admission-follow-up.md).

## Следующие шаги и откат

Для review использовать runtime SHA выше; для продолжения — текущую локальную
ветку с этим handoff. Переносить фиксированный G0 digest без регенерации manifest.
После принятия изменений выполнить установленный build/release runbook на builder,
зафиксировать image digest и завершить P1a gate. Существующий общий lint/type debt
должен оставаться явно виден при приёмке, без неявного exemption.

TASK-20/30 могут использовать опубликованные в repo schemas/mocks и endpoint
контракт. TASK-40 проверяет реальные routes, deployment, 1/3 подписки по прежнему
admission, decoded frames, legacy H.264 и drain. TASK-50/51 не начинать до
G-SERVER-READY. Native agent в рамках этой задачи не запускался.

Откат: запретить новые v2 starts, оставить v2 readers/STOP/event handlers до drain;
остановить каждый собственный HEVC epoch, дождаться producer deadline/route cleanup;
сохранить terminal records отдельно, очистить только drained v2 records/cache и
lease markers, затем вернуть прежний reader/image по immutable digest. Простого
отката контейнера при живом HEVC publisher недостаточно.

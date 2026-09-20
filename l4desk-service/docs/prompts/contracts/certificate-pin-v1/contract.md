# Certificate PIN — самостоятельный контракт для L4D-06B-IOT-FIX-01

Версия документационного контракта: `1.0.0`. Producer step: `L4D-06A-PB-CONTRACT-01`;
scope: `l4desk-service` (экспорт документации контроллером по поручению пользователя).
Реализация provider: `ProcessingBackend`, commit `083138f223b723098e9a188803e3fc802e8a6011`.
Историческое основание: `H-L4D-06A-PB-v1`. Это не новая версия приложения и не повторная
приёмка production. Чтение исходников provider потребителем не требуется и не разрешается.

## Состав и назначение

- `schemas.json` — JSON Schema Draft 2020-12: запрос, ответ, business/auth error и validation error.
- `examples.json` — синтетические положительные/отрицательные примеры; не результаты live smoke.
- `verification.md` — происхождение, проверка документов и пределы доказательств.

Все ссылки между этими документами локальны. Внешних `$ref` нет. Точные commit, SHA-256
и immutable URLs каждого файла указаны в новом handoff. Эта спецификация самодостаточна
для service-to-service PIN API; терминальные XML enrollment API не входят в предметный
scope FIX и данным экспортом не переопределяются.

## Транспорт и авторизация

JSON API, базовый URL берётся из конфигурации развёртывания, не из примеров.
`Content-Type: application/json` для POST. Оба маршрута используют один service credential,
не пользовательский JWT и не сертификат терминала. Передавать credential только по защищённому
внутреннему каналу; не отдавать PIN API напрямую браузеру/терминалу.

Приоритет входного credential:
1. `Authorization`, начинающийся с точного `Bearer `; значение после префикса очищается `strip`.
2. Иначе присутствующий `X-Service-Token`, значение очищается `strip`.
3. Иначе присутствующий `X-Internal-Service-Key`, значение очищается `strip`.

Неверный/пустой credential в заголовке более высокого приоритета не заменяется нижним.
Имена HTTP-заголовков регистронезависимы, префикс `Bearer ` регистрозависим.
Provider выбирает `SERVICE_AUTH_TOKEN`, иначе `INTERNAL_SERVICE_KEY`, сравнивая constant-time.
Если выбранный серверный credential непустой, неверный/отсутствующий даёт 401.
Если оба серверных значения пусты, текущая реализация **пропускает запрос** (local-dev fallback).
Это ограничение безопасности, а не разрешение экспонировать незакрытый API.
Настройка production-токена этим документом не подтверждается. Проверка 401 требует
настроенного credential; consumer не вправе отключать auth или объявлять smoke успешным без него.

Credential не содержит tenant identity. Consumer самостоятельно проверяет права пользователя,
связь tenant/terminal/SN и ownership операции. GET по operation_id не принимает tenant-фильтр.
Service credential и plaintext PIN никогда не включать в логи, evidence или git.

## POST /api/certificates/pins/issue

Запрос — `$defs.IssueRequest` из `schemas.json`:

| Поле | Обязательность и ограничения |
|---|---|
| operation_id | Обязательно, строка 1..128; не UUID-only, без trim/нормализации |
| tenant_id | Обязательно, integer, ID организации; схема не задаёт положительный минимум |
| terminal_id | Обязательно, integer, business terminal ID, не device_id |
| sn | Обязательно, строка 1..100, точное регистрозависимое совпадение |
| correlation_id | Необязательно, null или строка до 128, default null |
| ttl_seconds | Необязательно, integer 60..2592000, default 86400; null запрещён |
| actor | Необязательно, null или строка до 128, default system; пустое/null в audit заменяется system |

Дополнительные поля игнорируются. Consumer отправляет типизированный JSON согласно схеме;
провайдер использует нестрогую Pydantic-валидацию, поэтому coercion строковых чисел и bool
не является переносимой гарантией wire-контракта. Не расширять допустимый запрос consumer
на основании такого coercion. Локальные более строгие ограничения consumer допустимы.

Порядок после авторизации/валидации:
1. Поиск audit `certificate_pin_issued` по глобальному operation_id.
2. При существующей операции: сравнить **только tenant_id, terminal_id, sn**; различие — 409.
   TTL, actor, correlation_id не участвуют в конфликте и не обновляют старый PIN/срок.
3. Если операции нет: отсутствие terminal — 404; иной tenant — 403; иной SN — 400 (именно такой порядок).
4. Истечь все прежние pending PIN этого terminal, создать новый шестизначный числовой PIN,
   сохранить PIN и audit одной транзакцией; обновить pin_state существующей L4Desk-записи.
   Не создаёт terminal, device, лицензию и не списывает деньги.
5. Новая выдача — 201, `replayed=false`. Повтор завершённой операции — 200, `replayed=true`.

Новая operation_id для того же terminal — новая выдача, старый pending PIN истекает.
Повтор старой operation_id не должен создавать новую выдачу: возвращается текущее состояние
старого PIN, а не неизменный ответ первоначального запроса.

## GET /api/certificates/pins/by-operation/{operation_id}

Без тела запроса. operation_id — URL-encoded один сегмент пути. Рекомендуется UUID, чтобы
избежать неоднозначности слешей/прокси; POST не ограничен UUID. Неизвестная операция — 404.
Успех — 200 с тем же ответом, `replayed=true` даже для первого GET. GET может пометить
просроченный pending PIN как expired в БД. Отдельной проверки tenant ownership на GET нет.
Consumer обязан проверять принадлежность операции **до** вызова и не раскрывать результат
для чужого tenant. Текущий SN читается из terminal, при его отсутствии — из audit.

## Ответ и состояние

`$defs.IssueResponse`: operation_id, correlation_id, tenant_id, terminal_id, sn, pin,
pin_masked, status, expires_at, created_at, replayed. Даты — ISO 8601 UTC с timezone;
допустимы `Z` и `+00:00`, точность долей секунды не фиксирована.

| status | pin | Значение |
|---|---|---|
| issued | Шесть цифр строкой, сохраняющей ведущие нули | pending и expires_at > now |
| consumed | null | PIN использован |
| expired | null | срок прошёл, запись expired/иная либо PIN утрачен, но audit сохранился |

`pin_masked` обычно `***` + последние три цифры, при отсутствии сохранённого PIN/mask
возможен `***`. Это не plaintext PIN. В успешных ответах присутствуют все поля.
Первичная correlation_id — значение запроса (включая null/пустую строку); audit использует
непустую correlation_id, иначе operation_id. Replay POST возвращает непустую correlation_id
текущего запроса, иначе audit; GET возвращает audit. Поэтому ответы могут различаться в
correlation_id, replayed, status и pin без конфликта/новой выдачи.

## Ошибки

Business/auth ошибки имеют **обёртку** `{"detail": {...}}`, не плоский error DTO.
`message` — диагностический текст, не машинный discriminator. Использовать HTTP status
и `detail.error_code`. Business error включает operation_id; auth error его не включает.

| Маршрут | HTTP | detail.error | detail.error_code |
|---|---|---|---|
| Оба | 401 | unauthorized | SERVICE_AUTH_FAILED |
| POST | 404 | terminal_not_found | TERMINAL_NOT_FOUND |
| POST | 403 | tenant_ownership_mismatch | TENANT_OWNERSHIP_MISMATCH |
| POST | 400 | serial_number_mismatch | SERIAL_NUMBER_MISMATCH |
| POST | 409 | operation_id_conflict | OPERATION_ID_CONFLICT |
| GET | 404 | operation_not_found | OPERATION_NOT_FOUND |

Невалидный JSON/поля POST дают стандартный FastAPI 422: `detail` — массив с `loc`, `msg`,
`type` и необязательными `input`, `ctx`; это **не** business error. `ctx` и тексты не стабильны.
Infrastructure/unhandled errors могут быть 5xx с не-JSON телом: фиксированной схемы нет.
Consumer не должен выдавать успех при неизвестном ответе, автоматически создавать новый
operation_id при timeout/5xx или бесконечно повторять запрос.

## Идемпотентность, восстановление и границы доказательств

Audit и PIN хранятся в БД. Завершённый повтор ищется по operation_id, не по памяти процесса.
При неоднозначном сетевом исходе допускается GET той же операции, не выдача с новым ID.
При lookup fallback реализация использует первые 90 символов operation_id; consumer следует
использовать уникальные UUID operation_id, а не разные длинные строки с общим префиксом.

Последовательный replay описан и проверялся исходными тестами. Атомарная дедупликация двух
**одновременных первых** POST не доказана этим экспортом: в issuance handler нет отдельной
блокировки по operation_id; тест row-locking относится к terminal enrollment, не issuance.
Не заявлять новую гарантию exactly-once/concurrent PIN issuance и не ослаблять требование
идемпотентности provisioning внутри iot-rpc-rest-app. FIX проверяет собственное приложение;
provider runtime-дефект требует отдельной задачи, а не изменения чужого кода.

Коммерческие данные и PIN не отправляются в Agent/MQTT/event feed. Этот PIN API не определяет
provisioning API iot-rpc-rest-app и не требует добавлять вызов provider в FIX ради проверки входа.
Новый пакет дополняет исторический 06A самостоятельным описанием и явными ограничениями,
не отзывает его и не подтверждает текущую production-конфигурацию или live smoke.
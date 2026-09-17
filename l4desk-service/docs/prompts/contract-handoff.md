# Единый журнал передачи контрактов L4Desk

**Назначение:** единственный источник фактически зафиксированных межагентных контрактов каскада.  
**Режим:** append-only после секции «Принятые handoff-блоки».  
**Начальное состояние:** `READY_FOR_00A`.  
**Версия формата:** `1.0.0`.

Ни архитектурный документ, ни исходный код соседнего проекта, ни deployed endpoint, ни память агента не заменяют запись в этом журнале. Если требуемого принятого блока нет, агент не предполагает контракт и возвращает `BLOCKED_CONTRACT`.

## 1. Однозначное чтение входного контракта

Для каждого `required_handoff_id`, указанного в локальном промпте, агент обязан:

1. Искать точную пару HTML-маркеров:
   - `<!-- HANDOFF:<required_handoff_id>:BEGIN -->`;
   - `<!-- HANDOFF:<required_handoff_id>:END -->`.
2. Требовать ровно одну пару маркеров. Ноль или более одной пары означает `BLOCKED_CONTRACT`.
3. Разбирать только YAML-блок между маркерами; окружающий текст не является контрактом.
4. Проверять одновременно:
   - `handoff_id` точно совпадает с искомым;
   - `status` равен `ACCEPTED`;
   - `consumers` содержит текущий `prompt_id` либо точное значение `ALL_FOLLOWING`;
   - `contract_version` не пуст;
   - `contract_kinds` — непустой список разрешённых значений;
   - `artifact_paths` и `artifact_sha256` имеют одинаковое ненулевое число элементов, если `contract_kinds` не состоит только из `SEQUENCE_GATE`;
   - отсутствуют `TBD`, `TODO`, `UNKNOWN`, незаполненные обязательные поля;
   - `accepted_at_utc`, `producer_commit`, `producer_report_path` заполнены;
   - `deployment_status` соответствует требованию локального prompt;
   - блок не отозван более поздним `REVOCATION` и не заменён несовместимой записью `supersedes`.
5. Зафиксировать `handoff_id`, `contract_version` и digest артефактов в отчёте до начала реализации.
6. Не объединять конфликтующие версии самостоятельно. При конфликте остановиться.

`artifact_paths` — пути или immutable URL, доступные агенту без просмотра исходного кода чужого проекта. Digest считается по байтам опубликованного артефакта. Текст `contract_payload` может содержать краткую нормативную семантику, но крупные OpenAPI/JSON Schema/golden fixtures передаются отдельными immutable artifacts.

## 2. Кто пишет журнал

- Runtime-агент с `scope_project`, отличным от `l4desk-service`, **не редактирует этот файл**. Он помещает полностью заполненный candidate-блок в отчёт своего проекта.
- Контроллер каскада независимо проверяет отчёт, commit, push, deploy и smoke, затем добавляет candidate-блок в конец этого файла одной append-only операцией.
- Агент `l4desk-service` может сам добавить свой блок, потому что файл находится в его единственном scope.
- Принятый блок не исправляется на месте. Ошибка оформляется новым `REVOCATION`, затем новым handoff с новым идентификатором/версией и явным `supersedes`.
- До фактического появления принятого блока следующий агент не запускается.

## 3. Канонический формат принятого handoff

````text
<!-- HANDOFF:H-L4D-XX-v1:BEGIN -->
```yaml
handoff_id: H-L4D-XX-v1
status: ACCEPTED
contract_kinds:
  - API
  - EVENT
producer_prompt_id: L4D-XX-SCOPE
producer_scope_project: exact-project-name
producer_report_path: immutable/path/or/url/to/report.md
producer_branch: l4desk/l4d-xx-scope
producer_commit: full-commit-sha
accepted_at_utc: 2026-09-17T12:00:00Z
contract_version: exact-semver-or-revision
schema_revision: exact-revision-or-N/A
artifact_version: exact-version-or-N/A
artifact_paths:
  - immutable/path/or/url/to/artifact
artifact_sha256:
  - lowercase-sha256
compatibility:
  backward_compatible_with:
    - exact-version
  breaking_changes: false
  notes: exact-normative-notes
deployment_status: DEPLOYED | PUBLISHED | DOCS_PUBLISHED
deployed_environment: production | artifact-registry | documentation
feature_flags:
  exact_flag: disabled | shadow | enabled
contract_payload:
  identifiers: exact identifiers or N/A
  operations_events: exact operations/events or N/A
  errors: exact error model or N/A
  invariants: exact normative invariants
supersedes: []
known_risks: []
consumers:
  - L4D-NEXT-PROMPT
next_prompt_id: L4D-NEXT-PROMPT
```
<!-- HANDOFF:H-L4D-XX-v1:END -->
````

В реальном блоке внешняя ограда Markdown вокруг YAML не добавляется: между HTML-маркерами размещается один fenced `yaml` block. Маркеры и `handoff_id` должны совпадать посимвольно.

## 4. Формат отзыва

````text
<!-- REVOCATION:H-L4D-XX-v1:BEGIN -->
```yaml
handoff_id: H-L4D-XX-v1
status: REVOKED
revoked_at_utc: 2026-09-17T13:00:00Z
reason: точная причина
replacement_handoff_id: H-L4D-XX-v2 | NONE
controller_commit: full-commit-sha
```
<!-- REVOCATION:H-L4D-XX-v1:END -->
````

Отозванный handoff запрещено использовать, даже если replacement ещё не принят.

## 5. Правила candidate-блока агента

Candidate обязан быть готов к дословной вставке и содержать только факты завершённой работы. Агенту запрещено:

- ставить `ACCEPTED` до зелёных проверок, push, deploy/publish и smoke;
- указывать несуществующий artifact path или вычислять digest «на глаз»;
- передавать секреты;
- описывать незавершённую семантику словами «будет», `TBD` или `TODO`;
- расширять `consumers` без необходимости;
- менять входной контракт внутри выходного блока.

Если контракт не создаётся, шаг всё равно выпускает handoff с `contract_kinds: [SEQUENCE_GATE]` либо `[REPORT]` и immutable отчётом с digest, чтобы следующий prompt мог доказать соблюдение последовательности.

## 6. Bootstrap

Каскад ещё не запускался. Единственный prompt, разрешённый без входного handoff: `L4D-00A-TOOLS`. После его принятия каждый следующий prompt обязан иметь как минимум handoff непосредственно предыдущего шага.

## 7. Принятые handoff-блоки

Новые блоки добавляются только ниже этой строки в порядке каскада. На момент создания журнала принятых runtime-контрактов нет.

# 🟠 Интеграция · Kotlin и Spring

> Пример server-side REST-клиента для создания задачи и чтения результата. Прикладной сценарий — в общем руководстве интеграции.

[← Документация](README.md) · [Серверная интеграция](server-integration-guide.md) · [REST задач](1-task-workflow-doc.md)

## 🔑 Конфигурация

Передайте URL API и исходный ключ организации через конфигурацию приложения. Header — `x-api-key: <organization-api-key>`, без префикса `ApiKey`.

Пример предполагает настроенный Spring WebClient и Jackson Kotlin module. Выберите совместимые зависимости в своём проекте; это фрагмент интеграции, а не самостоятельный Spring-проект.

## 📦 Клиент и DTO

```kotlin
import com.fasterxml.jackson.databind.JsonNode
import org.springframework.web.reactive.function.client.WebClient
import reactor.core.publisher.Mono
import java.util.UUID

data class TaskCreate(
    val ext_task_id: String,
    val device_id: Int,
    val method_code: Int,
    val priority: Int = 0,
    val ttl: Int = 1,
    val payload: Map<String, Any>? = null
)

data class TaskCreated(val id: UUID, val created_at: Long)

data class TaskHeader(
    val ext_task_id: String,
    val device_id: Int,
    val method_code: Int,
    val priority: Int,
    val ttl: Int
)

data class TaskResult(
    val id: Long,
    val ext_id: Int,
    val status_code: Int,
    val result: JsonNode?
)

data class TaskDetails(
    val id: UUID,
    val created_at: Long,
    val header: TaskHeader,
    val status: Int,
    val pending_at: Long?,
    val locked_at: Long?,
    val payload: JsonNode?,
    val results: List<TaskResult>
)

class Leo4Client(baseUrl: String, apiKey: String) {
    private val http = WebClient.builder()
        .baseUrl(baseUrl.trimEnd('/') + "/api/v1")
        .defaultHeader("x-api-key", apiKey)
        .build()

    fun openCell(deviceId: Int, cell: Int, requestId: String): Mono<TaskCreated> =
        http.post().uri("/device-tasks/")
            .bodyValue(TaskCreate(
                ext_task_id = requestId,
                device_id = deviceId,
                method_code = 51,
                priority = 1,
                ttl = 5,
                payload = mapOf("dt" to listOf(mapOf("cl" to cell)))
            ))
            .retrieve().bodyToMono(TaskCreated::class.java)

    fun getTask(id: UUID): Mono<TaskDetails> =
        http.get().uri("/device-tasks/{id}", id)
            .retrieve().bodyToMono(TaskDetails::class.java)
}
```

Перед использованием настройте connect/read timeout в HTTP connector своего приложения. `retrieve()` передаёт HTTP-ошибку в reactive pipeline: обрабатывайте её на уровне сценария. Не добавляйте безусловный retry к `openCell`: повторный POST создаёт ещё одну задачу.

## 🚦 Обработка результата

Сохраните UUID из `TaskCreated`. При `status=3` проверьте `results[].status_code` и содержимое результата; состояние DONE не гарантирует успех. `4` — EXPIRED, `5` — DELETED, а `6/7` зарезервированы.

Для физического открытия отдельно читайте свежие события `13` с тегом `304` или принимайте event webhook. Начинайте ожидание события вместе с отправкой команды: оно может прийти раньше RES. [История и fields](2-events-api-format-description.md).

## 🔔 Приём webhooks

| Подписка | Приёмник |
| :--- | :--- |
| `msg-task-result` | `POST {configured_path}/{task_uuid}`; тело — один результат, metadata в `x-result-id`, `x-status-code`, `x-device-id` |
| `msg-event` | `POST {configured_path}/{device_id}`; тело — JSON `101/102/200/300` |

Проверяйте настроенный секрет headers, сохраняйте уведомление идемпотентно и отвечайте `2xx`. Для восстановления используйте REST. Полная настройка и retry — [Webhooks](3-webhooks.md).

Пример использует текущий REST-контракт `master`, сверенный на 09.10.2026. Фрагмент Kotlin не запускался как отдельное приложение в этом репозитории.

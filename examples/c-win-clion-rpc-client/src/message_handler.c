/**
 * @file message_handler.c
 * @brief Маршрутизация и обработка входящих MQTT 5 сообщений.
 *
 * Обработка топиков:
 *   srv/<SN>/tsk — анонс задачи (Trigger mode)
 *   srv/<SN>/rsp — параметры задачи
 *   srv/<SN>/cmt — подтверждение получения результата
 *   srv/<SN>/eva — подтверждение события
 */

#include "message_handler.h"
#include "device_client.h"
#include "config.h"

#include <stdio.h>
#include <string.h>
#include <stdlib.h>

/* ── Вспомогательные функции ───────────────────────────────── */

/**
 * Извлекает correlation data из свойств MQTT 5 сообщения.
 */
static const char *get_correlation_data(MQTTAsync_message *msg,
                                        char *buf, size_t buf_len)
{
    if (msg->properties.count > 0) {
        MQTTProperty *props = msg->properties.array;
        for (int i = 0; i < msg->properties.count; i++) {
            if (props[i].identifier == MQTTPROPERTY_CODE_CORRELATION_DATA) {
                int len = props[i].value.data.len;
                if (len <= 0 || (size_t)len >= buf_len) {
                    buf[0] = '\0';
                    return buf;
                }
                memcpy(buf, props[i].value.data.data, (size_t)len);
                buf[len] = '\0';
                return buf;
            }
        }
    }
    buf[0] = '\0';
    return buf;
}

/**
 * Извлекает значение User Property по имени.
 */
static const char *get_user_property(MQTTAsync_message *msg,
                                     const char *name,
                                     char *buf, size_t buf_len)
{
    if (msg->properties.count > 0) {
        MQTTProperty *props = msg->properties.array;
        for (int i = 0; i < msg->properties.count; i++) {
            if (props[i].identifier == MQTTPROPERTY_CODE_USER_PROPERTY) {
                if (props[i].value.data.len > 0 &&
                    strncmp(props[i].value.data.data, name,
                            (size_t)props[i].value.data.len) == 0) {
                    int vlen = props[i].value.value.len;
                    if (vlen <= 0 || (size_t)vlen >= buf_len) {
                        buf[0] = '\0';
                        return buf;
                    }
                    memcpy(buf, props[i].value.value.data, (size_t)vlen);
                    buf[vlen] = '\0';
                    return buf;
                }
            }
        }
    }
    buf[0] = '\0';
    return buf;
}

/* ── Обработчики по топикам ────────────────────────────────── */

/**
 * Обработка анонса задачи (TSK) от сервера (Trigger mode).
 */
static void handle_task_announcement(MessageHandlerCtx *ctx,
                                     const char *corr_data,
                                     MQTTAsync_message *msg)
{
    char method_code[32];
    get_user_property(msg, "method_code", method_code, sizeof(method_code));

    printf("[TSK] Task announcement: correlation=%s, method=%s\n",
           corr_data, method_code);

    /* Подтверждение получения (опционально) */
    device_client_send_ack(ctx->client, ctx->serial_number, corr_data);

    /* Запрос параметров задачи */
    device_client_send_request(ctx->client, ctx->serial_number, corr_data);
}

/**
 * Обработка ответа сервера с параметрами задачи (RSP).
 */
static void handle_task_response(MessageHandlerCtx *ctx,
                                 const char *corr_data,
                                 MQTTAsync_message *msg)
{
    char method_code[32];
    get_user_property(msg, "method_code", method_code, sizeof(method_code));

    char payload[MAX_PAYLOAD_LEN] = {0};
    if (msg->payloadlen > 0 && (size_t)msg->payloadlen < sizeof(payload)) {
        memcpy(payload, msg->payload, (size_t)msg->payloadlen);
        payload[msg->payloadlen] = '\0';
    }

    printf("[RSP] Task parameters received: method=%s, correlation=%s\n",
           method_code, corr_data);
    printf("[RSP] Payload: %s\n", payload);

    /*
     * ⚠️ ЗДЕСЬ РЕАЛИЗУЙТЕ ВАШУ БИЗНЕС-ЛОГИКУ!
     * Парсинг payload (JSON) и выполнение задачи.
     */
    printf("[EXEC] Executing task: method=%s\n", method_code);

    /* Имитация результата */
    const char *result = "{\"status\":\"completed\",\"data\":\"success\"}";

    /* Отправка результата */
    device_client_send_result(ctx->client, ctx->serial_number,
                              corr_data, result);
}

/**
 * Обработка подтверждения получения результата (CMT) от сервера.
 */
static void handle_commit(const char *corr_data, MQTTAsync_message *msg)
{
    char result_id[64];
    get_user_property(msg, "result_id", result_id, sizeof(result_id));

    printf("[CMT] Confirmation received: result_id=%s, correlation=%s\n",
           result_id, corr_data);
    printf("[CMT] RPC cycle completed successfully!\n");
}

/**
 * Обработка подтверждения события (EVA) от сервера.
 */
static void handle_event_ack(const char *corr_data)
{
    printf("[EVA] Event confirmation received: correlation=%s\n",
           corr_data);
}

/* ── Публичный API ─────────────────────────────────────────── */

void msg_handler_init(MessageHandlerCtx *ctx, const char *sn,
                      MQTTAsync client)
{
    memset(ctx, 0, sizeof(*ctx));
    snprintf(ctx->serial_number, sizeof(ctx->serial_number), "%s", sn);

    snprintf(ctx->topic_rsp, sizeof(ctx->topic_rsp), "srv/%s/rsp", sn);
    snprintf(ctx->topic_tsk, sizeof(ctx->topic_tsk), "srv/%s/tsk", sn);
    snprintf(ctx->topic_cmt, sizeof(ctx->topic_cmt), "srv/%s/cmt", sn);
    snprintf(ctx->topic_eva, sizeof(ctx->topic_eva), "srv/%s/eva", sn);

    ctx->client = client;
}

void msg_handler_on_message(MessageHandlerCtx *ctx,
                            const char *topic, int topic_len,
                            MQTTAsync_message *message)
{
    char corr_buf[MAX_CORR_DATA_LEN];
    const char *corr_data = get_correlation_data(message,
                                                  corr_buf, sizeof(corr_buf));

    printf("[MSG] Message received: %.*s | Correlation: %s\n",
           topic_len, topic, corr_data);

    if (strncmp(topic, ctx->topic_tsk, (size_t)topic_len) == 0) {
        handle_task_announcement(ctx, corr_data, message);
    } else if (strncmp(topic, ctx->topic_rsp, (size_t)topic_len) == 0) {
        handle_task_response(ctx, corr_data, message);
    } else if (strncmp(topic, ctx->topic_cmt, (size_t)topic_len) == 0) {
        handle_commit(corr_data, message);
    } else if (strncmp(topic, ctx->topic_eva, (size_t)topic_len) == 0) {
        handle_event_ack(corr_data);
    } else {
        printf("[WARN] Unknown topic: %.*s\n", topic_len, topic);
    }
}

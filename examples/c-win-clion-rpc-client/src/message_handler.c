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
#include <ctype.h>

/* ── Вспомогательные функции ───────────────────────────────── */

/**
 * Returns the actual topic length.
 */
static size_t resolve_topic_len(const char *topic, int topic_len)
{
    if (topic_len > 0) {
        return (size_t)topic_len;
    }

    return topic ? strlen(topic) : 0;
}

static int topic_equals(const char *topic, size_t topic_len,
                        const char *expected_topic)
{
    size_t expected_len = strlen(expected_topic);
    return topic_len == expected_len && memcmp(topic, expected_topic, topic_len) == 0;
}

static int is_printable_ascii(const unsigned char *data, size_t len)
{
    for (size_t i = 0; i < len; i++) {
        if (!isprint((int)data[i])) {
            return 0;
        }
    }

    return 1;
}

static void format_binary_for_log(const unsigned char *data, size_t len,
                                  char *buf, size_t buf_len)
{
    size_t pos = 0;

    if (!buf_len) {
        return;
    }

    buf[0] = '\0';

    if (!data || len == 0) {
        snprintf(buf, buf_len, "<empty>");
        return;
    }

    if (is_printable_ascii(data, len)) {
        snprintf(buf, buf_len, "\"%.*s\"", (int)len, (const char *)data);
        return;
    }

    pos += (size_t)snprintf(buf + pos, buf_len - pos, "0x");
    for (size_t i = 0; i < len && pos + 3 < buf_len; i++) {
        pos += (size_t)snprintf(buf + pos, buf_len - pos, "%02X", data[i]);
    }

    if (pos >= buf_len) {
        buf[buf_len - 1] = '\0';
    }
}

static void format_payload_preview(MQTTAsync_message *msg,
                                   char *buf, size_t buf_len)
{
    size_t preview_len;

    if (!buf_len) {
        return;
    }

    buf[0] = '\0';

    if (!msg->payload || msg->payloadlen <= 0) {
        snprintf(buf, buf_len, "<empty>");
        return;
    }

    preview_len = (size_t)msg->payloadlen > 160 ? 160 : (size_t)msg->payloadlen;

    if (is_printable_ascii((const unsigned char *)msg->payload, preview_len)) {
        snprintf(buf, buf_len, "%.*s%s",
                 (int)preview_len, (const char *)msg->payload,
                 (size_t)msg->payloadlen > preview_len ? "..." : "");
        return;
    }

    format_binary_for_log((const unsigned char *)msg->payload, preview_len,
                          buf, buf_len);
}

/**
 * Extracts MQTT 5 Correlation Data as binary bytes.
 */
static int get_correlation_data(MQTTAsync_message *msg,
                                unsigned char *buf, size_t buf_len,
                                CorrDataView *corr_data)
{
    corr_data->data = NULL;
    corr_data->len = 0;

    if (msg->properties.count > 0) {
        MQTTProperty *props = msg->properties.array;
        for (int i = 0; i < msg->properties.count; i++) {
            if (props[i].identifier == MQTTPROPERTY_CODE_CORRELATION_DATA) {
                int len = props[i].value.data.len;
                if (len <= 0) {
                    return 0;
                }

                if ((size_t)len > buf_len) {
                    fprintf(stderr,
                            "[MSG] correlation_data is too large: len=%d, buffer=%zu\n",
                            len, buf_len);
                    return -1;
                }

                memcpy(buf, props[i].value.data.data, (size_t)len);
                corr_data->data = buf;
                corr_data->len = (size_t)len;
                return 1;
            }
        }
    }

    return 0;
}

/**
 * Извлекает значение User Property по имени.
 */
static const char *get_user_property(MQTTAsync_message *msg,
                                     const char *name,
                                     char *buf, size_t buf_len)
{
    size_t name_len = strlen(name);

    if (msg->properties.count > 0) {
        MQTTProperty *props = msg->properties.array;
        for (int i = 0; i < msg->properties.count; i++) {
            if (props[i].identifier == MQTTPROPERTY_CODE_USER_PROPERTY) {
                if (props[i].value.data.len == (int)name_len &&
                    memcmp(props[i].value.data.data, name, name_len) == 0) {
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

static void log_user_properties(MQTTAsync_message *msg)
{
    if (msg->properties.count <= 0) {
        printf("[MSG] Properties: none\n");
        return;
    }

    printf("[MSG] Properties (%d):\n", msg->properties.count);

    for (int i = 0; i < msg->properties.count; i++) {
        MQTTProperty *prop = &msg->properties.array[i];

        if (prop->identifier == MQTTPROPERTY_CODE_USER_PROPERTY) {
            printf("[MSG]   user_property[%d]: %.*s=%.*s\n",
                   i,
                   prop->value.data.len, prop->value.data.data,
                   prop->value.value.len, prop->value.value.data);
        } else if (prop->identifier == MQTTPROPERTY_CODE_CORRELATION_DATA) {
            char corr_buf[160];
            format_binary_for_log((const unsigned char *)prop->value.data.data,
                                  (size_t)prop->value.data.len,
                                  corr_buf, sizeof(corr_buf));
            printf("[MSG]   correlation_data[%d]: len=%d, value=%s\n",
                   i, prop->value.data.len, corr_buf);
        } else {
            printf("[MSG]   property[%d]: id=%d\n", i, prop->identifier);
        }
    }
}

static void log_incoming_message(const char *topic, size_t topic_len,
                                 MQTTAsync_message *msg,
                                 const CorrDataView *corr_data)
{
    char corr_buf[160];
    char payload_buf[256];

    format_binary_for_log(corr_data ? corr_data->data : NULL,
                          corr_data ? corr_data->len : 0,
                          corr_buf, sizeof(corr_buf));
    format_payload_preview(msg, payload_buf, sizeof(payload_buf));

    printf("[MSG] Received: topic=%.*s, payload_len=%d, qos=%d, retained=%d, dup=%d\n",
           (int)topic_len, topic, msg->payloadlen, msg->qos,
           msg->retained, msg->dup);
    printf("[MSG] correlation_data: len=%zu, value=%s\n",
           corr_data ? corr_data->len : 0, corr_buf);
    printf("[MSG] payload preview: %s\n", payload_buf);
    log_user_properties(msg);
}

/* ── Обработчики по топикам ────────────────────────────────── */

/**
 * Обработка анонса задачи (TSK) от сервера (Trigger mode).
 */
static void handle_task_announcement(MessageHandlerCtx *ctx,
                                     const CorrDataView *corr_data,
                                     MQTTAsync_message *msg)
{
    char method_code[32];
    get_user_property(msg, "method_code", method_code, sizeof(method_code));

    printf("[TSK] Task announcement received: method_code=%s\n",
           method_code[0] ? method_code : "<missing>");

    if (!corr_data || !corr_data->data || corr_data->len == 0) {
        fprintf(stderr,
                "[TSK] Skip ACK/REQ: task announcement does not contain correlation_data.\n");
        return;
    }

    /* Acknowledge the task announcement. */
    device_client_send_ack(ctx->client, ctx->serial_number, corr_data);

    /* Request task parameters. */
    device_client_send_request(ctx->client, ctx->serial_number, corr_data);
}

/**
 * Обработка ответа сервера с параметрами задачи (RSP).
 */
static void handle_task_response(MessageHandlerCtx *ctx,
                                 const CorrDataView *corr_data,
                                 MQTTAsync_message *msg)
{
    char method_code[32];
    get_user_property(msg, "method_code", method_code, sizeof(method_code));

    char payload[MAX_PAYLOAD_LEN] = {0};
    if (msg->payloadlen > 0 && (size_t)msg->payloadlen < sizeof(payload)) {
        memcpy(payload, msg->payload, (size_t)msg->payloadlen);
        payload[msg->payloadlen] = '\0';
    }

    printf("[RSP] Task response received: method_code=%s\n",
           method_code[0] ? method_code : "<missing>");
    printf("[RSP] Payload: %s\n", payload[0] ? payload : "<empty>");

    if (strcmp(method_code, "0") == 0) {
        printf("[RSP] No pending task on server (method_code=0). Result publish skipped.\n");
        return;
    }

    if (!corr_data || !corr_data->data || corr_data->len == 0) {
        fprintf(stderr,
                "[RSP] Skip result publish: response does not contain correlation_data.\n");
        return;
    }

    /*
     * ⚠️ ЗДЕСЬ РЕАЛИЗУЙТЕ ВАШУ БИЗНЕС-ЛОГИКУ!
     * Парсинг payload (JSON) и выполнение задачи.
     */
    printf("[EXEC] Executing task: method_code=%s\n", method_code);

    /* Имитация результата */
    const char *result = "{\"status\":\"completed\",\"data\":\"success\"}";

    /* Отправка результата */
    device_client_send_result(ctx->client, ctx->serial_number,
                              corr_data, result);
}

/**
 * Обработка подтверждения получения результата (CMT) от сервера.
 */
static void handle_commit(const CorrDataView *corr_data, MQTTAsync_message *msg)
{
    char result_id[64];
    get_user_property(msg, "result_id", result_id, sizeof(result_id));

    (void)corr_data;
    printf("[CMT] Result confirmation received: result_id=%s\n",
           result_id[0] ? result_id : "<missing>");
    printf("[CMT] RPC cycle completed successfully.\n");
}

/**
 * Обработка подтверждения события (EVA) от сервера.
 */
static void handle_event_ack(const CorrDataView *corr_data)
{
    (void)corr_data;
    printf("[EVA] Event confirmation received.\n");
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
    unsigned char corr_buf[MAX_CORR_DATA_LEN];
    CorrDataView corr_data;
    size_t actual_topic_len = resolve_topic_len(topic, topic_len);

    (void)get_correlation_data(message, corr_buf, sizeof(corr_buf), &corr_data);

    log_incoming_message(topic, actual_topic_len, message, &corr_data);

    if (topic_equals(topic, actual_topic_len, ctx->topic_tsk)) {
        handle_task_announcement(ctx, &corr_data, message);
    } else if (topic_equals(topic, actual_topic_len, ctx->topic_rsp)) {
        handle_task_response(ctx, &corr_data, message);
    } else if (topic_equals(topic, actual_topic_len, ctx->topic_cmt)) {
        handle_commit(&corr_data, message);
    } else if (topic_equals(topic, actual_topic_len, ctx->topic_eva)) {
        handle_event_ack(&corr_data);
    } else {
        printf("[WARN] Unknown topic: %.*s\n", (int)actual_topic_len, topic);
    }
}

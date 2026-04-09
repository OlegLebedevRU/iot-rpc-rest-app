/**
 * @file device_client.c
 * @brief Реализация IoT RPC Device Client на чистом C.
 *
 * Используется Eclipse Paho MQTT Async C Client с поддержкой MQTT 5.0.
 * TLS настраивается через Paho SSL options (OpenSSL).
 *
 * Фоновые циклы (polling, healthcheck) реализованы через потоки:
 *  - Windows: _beginthreadex
 *  - POSIX:   pthread_create
 */

#include "device_client.h"
#include "message_handler.h"
#include "cert_utils.h"
#include "config.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <ctype.h>

#ifdef _WIN32
#  include <windows.h>
#  include <process.h>    /* _beginthreadex */
#else
#  include <pthread.h>
#  include <unistd.h>
#endif

/* ── Глобальное состояние ──────────────────────────────────── */

static volatile int g_running = 1;      /* флаг для фоновых потоков    */
static MQTTAsync    g_client  = NULL;
static char         g_sn[MAX_SN_LEN];   /* серийный номер устройства   */

/* Топики публикации (device → server) */
static char g_topic_req[MAX_TOPIC_LEN];
static char g_topic_res[MAX_TOPIC_LEN];
static char g_topic_evt[MAX_TOPIC_LEN];
static char g_topic_ack[MAX_TOPIC_LEN];

/* Обработчик входящих сообщений */
static MessageHandlerCtx g_msg_handler;

/* ── Нормализация адреса брокера ────────────────────────────── */

static int build_server_uri(const char *raw_host,
                            int port,
                            char *out_uri,
                            size_t out_uri_len)
{
    char host_only[192];
    const char *host = raw_host;
    const char *scheme = strstr(raw_host ? raw_host : "", "://");

    if (!raw_host || !raw_host[0]) {
        fprintf(stderr, "[FATAL] BROKER_HOST is empty\n");
        return -1;
    }

    if (scheme) {
        size_t scheme_len = (size_t)(scheme - raw_host);
        if (scheme_len > 0) {
            printf("[WARN] BROKER_HOST contains scheme '%.*s://', it will be ignored.\n",
                   (int)scheme_len, raw_host);
        }
        host = scheme + 3;
    }

    size_t i = 0;
    while (host[i] && host[i] != '/' && !isspace((unsigned char)host[i]) && i + 1 < sizeof(host_only)) {
        host_only[i] = host[i];
        i++;
    }
    host_only[i] = '\0';

    if (!host_only[0]) {
        fprintf(stderr, "[FATAL] Invalid BROKER_HOST: '%s'\n", raw_host);
        return -1;
    }

    if (strchr(host_only, ':')) {
        if (snprintf(out_uri, out_uri_len, "mqtts://%s", host_only) >= (int)out_uri_len) {
            fprintf(stderr, "[FATAL] Broker URI is too long\n");
            return -1;
        }
    } else {
        if (snprintf(out_uri, out_uri_len, "mqtts://%s:%d", host_only, port) >= (int)out_uri_len) {
            fprintf(stderr, "[FATAL] Broker URI is too long\n");
            return -1;
        }
    }

    return 0;
}

/* ── Генерация UUID v4 (упрощённая) ────────────────────────── */

static void generate_uuid(char *buf, size_t len)
{
    /* Формат: xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx */
    static const char hex[] = "0123456789abcdef";
    static int seeded = 0;
    if (!seeded) {
        srand((unsigned)time(NULL));
        seeded = 1;
    }

    const char *fmt = "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx";
    size_t fi = 0;
    size_t bi = 0;
    while (fmt[fi] && bi + 1 < len) {
        char c = fmt[fi];
        if (c == 'x') {
            buf[bi] = hex[rand() % 16];
        } else if (c == 'y') {
            buf[bi] = hex[(rand() % 4) + 8]; /* 8, 9, a, b */
        } else {
            buf[bi] = c;
        }
        fi++;
        bi++;
    }
    buf[bi] = '\0';
}

/* ── Публикация с MQTT 5 свойствами ────────────────────────── */

/**
 * Создаёт MQTTProperties с CorrelationData.
 */
static MQTTProperties make_props_with_corr(const char *corr_data)
{
    MQTTProperties props = MQTTProperties_initializer;

    if (corr_data && corr_data[0]) {
        MQTTProperty prop;
        prop.identifier = MQTTPROPERTY_CODE_CORRELATION_DATA;
        prop.value.data.data = (char *)corr_data;
        prop.value.data.len  = (int)strlen(corr_data);
        MQTTProperties_add(&props, &prop);
    }

    return props;
}

/**
 * Добавляет User Property к существующим свойствам.
 */
static void add_user_property(MQTTProperties *props,
                              const char *key, const char *value)
{
    MQTTProperty prop;
    prop.identifier = MQTTPROPERTY_CODE_USER_PROPERTY;
    prop.value.data.data  = (char *)key;
    prop.value.data.len   = (int)strlen(key);
    prop.value.value.data = (char *)value;
    prop.value.value.len  = (int)strlen(value);
    MQTTProperties_add(props, &prop);
}

/* ── Публичные функции публикации ──────────────────────────── */

void device_client_send_request(MQTTAsync client, const char *sn,
                                const char *correlation_data)
{
    char topic[MAX_TOPIC_LEN];
    snprintf(topic, sizeof(topic), "dev/%s/req", sn);

    const char *corr = (correlation_data && correlation_data[0])
                       ? correlation_data : ZERO_UUID;

    MQTTProperties props = make_props_with_corr(corr);

    MQTTAsync_message msg = MQTTAsync_message_initializer;
    msg.payload    = (void *)"";
    msg.payloadlen = 0;
    msg.qos        = 1;
    msg.properties = props;

    MQTTAsync_sendMessage(client, topic, &msg, NULL);
    MQTTProperties_free(&props);

    printf("[REQ] Request sent: correlation=%s\n", corr);
}

void device_client_send_ack(MQTTAsync client, const char *sn,
                            const char *correlation_data)
{
    char topic[MAX_TOPIC_LEN];
    snprintf(topic, sizeof(topic), "dev/%s/ack", sn);

    MQTTProperties props = make_props_with_corr(correlation_data);

    MQTTAsync_message msg = MQTTAsync_message_initializer;
    msg.payload    = (void *)"";
    msg.payloadlen = 0;
    msg.qos        = 1;
    msg.properties = props;

    MQTTAsync_sendMessage(client, topic, &msg, NULL);
    MQTTProperties_free(&props);

    printf("[ACK] ACK sent: correlation=%s\n", correlation_data);
}

void device_client_send_result(MQTTAsync client, const char *sn,
                               const char *correlation_data,
                               const char *result_json)
{
    char topic[MAX_TOPIC_LEN];
    snprintf(topic, sizeof(topic), "dev/%s/res", sn);

    MQTTProperties props = make_props_with_corr(correlation_data);
    add_user_property(&props, "status_code", "200");
    add_user_property(&props, "ext_id", "12345");

    MQTTAsync_message msg = MQTTAsync_message_initializer;
    msg.payload    = (void *)result_json;
    msg.payloadlen = (int)strlen(result_json);
    msg.qos        = 1;
    msg.properties = props;

    MQTTAsync_sendMessage(client, topic, &msg, NULL);
    MQTTProperties_free(&props);

    printf("[RES] Result sent: correlation=%s\n", correlation_data);
}

void device_client_send_event(MQTTAsync client, const char *sn,
                              int event_type_code,
                              const char *event_json)
{
    char topic[MAX_TOPIC_LEN];
    snprintf(topic, sizeof(topic), "dev/%s/evt", sn);

    char uuid_buf[48];
    generate_uuid(uuid_buf, sizeof(uuid_buf));

    MQTTProperties props = make_props_with_corr(uuid_buf);

    char code_str[16];
    snprintf(code_str, sizeof(code_str), "%d", event_type_code);
    add_user_property(&props, "event_type_code", code_str);
    add_user_property(&props, "dev_event_id", "1001");

    char ts_str[32];
    snprintf(ts_str, sizeof(ts_str), "%lld", (long long)time(NULL));
    add_user_property(&props, "dev_timestamp", ts_str);

    MQTTAsync_message msg = MQTTAsync_message_initializer;
    msg.payload    = (void *)event_json;
    msg.payloadlen = (int)strlen(event_json);
    msg.qos        = 1;
    msg.properties = props;

    MQTTAsync_sendMessage(client, topic, &msg, NULL);
    MQTTProperties_free(&props);

    printf("[EVT] Event sent: type=%d, correlation=%s\n",
           event_type_code, uuid_buf);
}

/* ── Callback-и Paho ───────────────────────────────────────── */

static void on_connect_failure(void *context, MQTTAsync_failureData5 *response)
{
    (void)context;
    fprintf(stderr, "[MQTT] Connection failed, code=%d\n",
            response ? response->code : -1);
    g_running = 0;
}

static void on_subscribe_success(void *context, MQTTAsync_successData5 *response)
{
    (void)context;
    if (response) {
        printf("[MQTT] Subscription acknowledged: reason=%d, token=%d\n",
               (int)response->reasonCode, response->token);
    } else {
        printf("[MQTT] Topic subscription completed.\n");
    }
}

static void on_subscribe_failure(void *context, MQTTAsync_failureData5 *response)
{
    (void)context;
    if (response) {
        fprintf(stderr,
                "[MQTT] Subscription failed, code=%d (%s), reason=%d, packet=%d, token=%d, msg=%s\n",
                response->code,
                MQTTAsync_strerror(response->code) ? MQTTAsync_strerror(response->code) : "unknown",
                (int)response->reasonCode,
                response->packet_type,
                response->token,
                response->message ? response->message : "-");
    } else {
        fprintf(stderr, "[MQTT] Subscription failed, code=-1\n");
    }
}

static int on_message_arrived(void *context, char *topicName, int topicLen,
                              MQTTAsync_message *message)
{
    (void)context;
    msg_handler_on_message(&g_msg_handler, topicName, topicLen, message);
    MQTTAsync_freeMessage(&message);
    MQTTAsync_free(topicName);
    return 1; /* сообщение обработано */
}

static void on_connection_lost(void *context, char *cause)
{
    (void)context;
    fprintf(stderr, "[MQTT] Connection lost: %s\n",
            cause ? cause : "unknown");
}

static void on_connected(void *context, char *cause)
{
    (void)context;
    (void)cause;
    printf("[MQTT] Connected to MQTT broker!\n");

    /* Подписка на входящие топики по одному: так проще диагностировать сбойный топик. */
    const char *topics[] = {
        g_msg_handler.topic_rsp,
        g_msg_handler.topic_tsk,
        g_msg_handler.topic_cmt,
        g_msg_handler.topic_eva
    };

    for (size_t i = 0; i < (sizeof(topics) / sizeof(topics[0])); i++) {
        MQTTAsync_responseOptions opts = MQTTAsync_responseOptions_initializer;
        opts.onSuccess5 = on_subscribe_success;
        opts.onFailure5 = on_subscribe_failure;

        int rc = MQTTAsync_subscribe(g_client, topics[i], 1, &opts);
        if (rc != MQTTASYNC_SUCCESS) {
            fprintf(stderr,
                    "[MQTT] Failed to send SUBSCRIBE for '%s': rc=%d (%s)\n",
                    topics[i], rc,
                    MQTTAsync_strerror(rc) ? MQTTAsync_strerror(rc) : "unknown");
        } else {
            printf("[MQTT] SUBSCRIBE sent: %s\n", topics[i]);
        }
    }
}

/* ── Фоновые потоки ────────────────────────────────────────── */

static void sleep_seconds(int seconds)
{
#ifdef _WIN32
    Sleep((DWORD)seconds * 1000);
#else
    sleep((unsigned)seconds);
#endif
}

#ifdef _WIN32
static unsigned __stdcall polling_thread(void *arg)
#else
static void *polling_thread(void *arg)
#endif
{
    (void)arg;
    printf("[POLL] Polling loop started (interval: %d sec)\n",
           REQ_POLL_INTERVAL);

    while (g_running) {
        device_client_send_request(g_client, g_sn, NULL);
        sleep_seconds(REQ_POLL_INTERVAL);
    }

#ifdef _WIN32
    return 0;
#else
    return NULL;
#endif
}

#ifdef _WIN32
static unsigned __stdcall healthcheck_thread(void *arg)
#else
static void *healthcheck_thread(void *arg)
#endif
{
    (void)arg;
    printf("[HEALTH] Healthcheck loop started (interval: %d sec)\n",
           HEALTHCHECK_INTERVAL);

    while (g_running) {
        /*
         * Healthcheck event (event_type_code = 44).
         * Payload имитирует реальные данные устройства.
         */
        const char *hc_json =
            "{"
            "\"101\":1047,"
            "\"102\":\"2024-08-12T10:31:57Z\","
            "\"200\":44,"
            "\"300\":[{\"310\":\"1.04.025\",\"311\":13}]"
            "}";

        device_client_send_event(g_client, g_sn, 44, hc_json);
        sleep_seconds(HEALTHCHECK_INTERVAL);
    }

#ifdef _WIN32
    return 0;
#else
    return NULL;
#endif
}

/* ── Точка входа модуля ────────────────────────────────────── */

int device_client_run(void)
{
    int rc;

    /* 1. Извлечение SN из сертификата */
    printf("[START] Initializing DeviceClient...\n");
    if (extract_cn_from_cert(CLIENT_CERT_PATH, g_sn, sizeof(g_sn)) != 0) {
        fprintf(stderr, "[FATAL] Failed to extract SN from certificate\n");
        return 1;
    }
    printf("[SN] Device serial number: %s\n", g_sn);

    /* 2. Формирование топиков публикации */
    snprintf(g_topic_req, sizeof(g_topic_req), "dev/%s/req", g_sn);
    snprintf(g_topic_res, sizeof(g_topic_res), "dev/%s/res", g_sn);
    snprintf(g_topic_evt, sizeof(g_topic_evt), "dev/%s/evt", g_sn);
    snprintf(g_topic_ack, sizeof(g_topic_ack), "dev/%s/ack", g_sn);

    printf("[TOPICS] REQ: %s, RES: %s, EVT: %s\n",
           g_topic_req, g_topic_res, g_topic_evt);

    /* 3. Создание MQTT-клиента (MQTTv5) */
    char server_uri[256];
    if (build_server_uri(BROKER_HOST, BROKER_PORT,
                         server_uri, sizeof(server_uri)) != 0) {
        return 1;
    }

    MQTTAsync_createOptions create_opts = MQTTAsync_createOptions_initializer5;
    create_opts.MQTTVersion = MQTTVERSION_5;

    rc = MQTTAsync_createWithOptions(&g_client, server_uri, g_sn,
                                     MQTTCLIENT_PERSISTENCE_NONE, NULL,
                                     &create_opts);
    if (rc != MQTTASYNC_SUCCESS) {
        fprintf(stderr, "[FATAL] MQTTAsync_create failed: %d\n", rc);
        return 1;
    }

    /* Инициализация обработчика сообщений */
    msg_handler_init(&g_msg_handler, g_sn, g_client);

    /* Callback-и */
    MQTTAsync_setCallbacks(g_client, NULL,
                           on_connection_lost,
                           on_message_arrived,
                           NULL);
    MQTTAsync_setConnected(g_client, NULL, on_connected);

    /* 4. Настройка TLS (mTLS) */
    MQTTAsync_SSLOptions ssl_opts = MQTTAsync_SSLOptions_initializer;
    ssl_opts.trustStore     = CA_CERT_PATH;
    ssl_opts.keyStore       = CLIENT_CERT_PATH;
    ssl_opts.privateKey     = CLIENT_KEY_PATH;
    ssl_opts.enabledCipherSuites = NULL;
    ssl_opts.enableServerCertAuth = 1;
    ssl_opts.sslVersion     = MQTT_SSL_VERSION_TLS_1_2;

    /* 5. Параметры подключения */
    MQTTAsync_connectOptions conn_opts = MQTTAsync_connectOptions_initializer5;
    conn_opts.keepAliveInterval = BROKER_KEEPALIVE;
    conn_opts.cleanstart        = 1;
    conn_opts.MQTTVersion       = MQTTVERSION_5;
    conn_opts.ssl               = &ssl_opts;
    conn_opts.onFailure5        = on_connect_failure;
    conn_opts.automaticReconnect = 1;
    conn_opts.minRetryInterval   = 2;
    conn_opts.maxRetryInterval   = 60;

    /* 6. Подключение */
    printf("[MQTT] Connecting to %s...\n", server_uri);
    rc = MQTTAsync_connect(g_client, &conn_opts);
    if (rc != MQTTASYNC_SUCCESS) {
        fprintf(stderr, "[FATAL] MQTTAsync_connect failed: %d\n", rc);
        MQTTAsync_destroy(&g_client);
        return 1;
    }

    /* 7. Запуск фоновых потоков */
#ifdef _WIN32
    HANDLE h_poll, h_health;
    h_poll   = (HANDLE)_beginthreadex(NULL, 0, polling_thread, NULL, 0, NULL);
    h_health = (HANDLE)_beginthreadex(NULL, 0, healthcheck_thread, NULL, 0, NULL);
#else
    pthread_t t_poll, t_health;
    pthread_create(&t_poll, NULL, polling_thread, NULL);
    pthread_create(&t_health, NULL, healthcheck_thread, NULL);
#endif

    printf("[MQTT] Background tasks started.\n");

    /* 8. Ожидание ввода для завершения */
    printf("\n");
    printf("================================================================\n");
    printf("  Client is running. Press Enter to exit.\n");
    printf("================================================================\n");
    printf("\n");

    (void)getchar();

    /* 9. Остановка */
    printf("[STOP] Stopping DeviceClient...\n");
    g_running = 0;

    /* Даём потокам завершиться */
    sleep_seconds(1);

    if (MQTTAsync_isConnected(g_client)) {
        MQTTAsync_disconnect(g_client, NULL);
    }
    MQTTAsync_destroy(&g_client);

    printf("[STOP] DeviceClient stopped.\n");
    return 0;
}

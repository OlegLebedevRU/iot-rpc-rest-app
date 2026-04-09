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

    printf("[REQ] Отправлен запрос: correlation=%s\n", corr);
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

    printf("[ACK] Отправлен ACK: correlation=%s\n", correlation_data);
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

    printf("[RES] Результат отправлен: correlation=%s\n", correlation_data);
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

    printf("[EVT] Событие отправлено: type=%d, correlation=%s\n",
           event_type_code, uuid_buf);
}

/* ── Callback-и Paho ───────────────────────────────────────── */

static void on_connect_failure(void *context, MQTTAsync_failureData5 *response)
{
    (void)context;
    fprintf(stderr, "[MQTT] Ошибка подключения, code=%d\n",
            response ? response->code : -1);
    g_running = 0;
}

static void on_subscribe_success(void *context, MQTTAsync_successData5 *response)
{
    (void)context;
    (void)response;
    printf("[MQTT] Подписка на топики выполнена.\n");
}

static void on_subscribe_failure(void *context, MQTTAsync_failureData5 *response)
{
    (void)context;
    fprintf(stderr, "[MQTT] Ошибка подписки, code=%d\n",
            response ? response->code : -1);
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
    fprintf(stderr, "[MQTT] Соединение потеряно: %s\n",
            cause ? cause : "unknown");
}

static void on_connected(void *context, char *cause)
{
    (void)context;
    (void)cause;
    printf("[MQTT] Подключено к MQTT-брокеру!\n");

    /* Подписка на входящие топики */
    char *topics[] = {
        g_msg_handler.topic_rsp,
        g_msg_handler.topic_tsk,
        g_msg_handler.topic_cmt
    };
    int qos[] = { 1, 1, 1 };

    MQTTAsync_responseOptions opts = MQTTAsync_responseOptions_initializer;
    opts.onSuccess5 = on_subscribe_success;
    opts.onFailure5 = on_subscribe_failure;

    MQTTAsync_subscribeMany(g_client, 3, topics, qos, &opts);
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
    printf("[POLL] Запущен цикл поллинга (интервал: %d сек)\n",
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
    printf("[HEALTH] Запущен цикл healthcheck (интервал: %d сек)\n",
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
    printf("[START] Инициализация DeviceClient...\n");
    if (extract_cn_from_cert(CLIENT_CERT_PATH, g_sn, sizeof(g_sn)) != 0) {
        fprintf(stderr, "[FATAL] Не удалось извлечь SN из сертификата\n");
        return 1;
    }
    printf("[SN] Серийный номер устройства: %s\n", g_sn);

    /* 2. Формирование топиков публикации */
    snprintf(g_topic_req, sizeof(g_topic_req), "dev/%s/req", g_sn);
    snprintf(g_topic_res, sizeof(g_topic_res), "dev/%s/res", g_sn);
    snprintf(g_topic_evt, sizeof(g_topic_evt), "dev/%s/evt", g_sn);
    snprintf(g_topic_ack, sizeof(g_topic_ack), "dev/%s/ack", g_sn);

    printf("[TOPICS] REQ: %s, RES: %s, EVT: %s\n",
           g_topic_req, g_topic_res, g_topic_evt);

    /* 3. Создание MQTT-клиента (MQTTv5) */
    char server_uri[256];
    snprintf(server_uri, sizeof(server_uri), "ssl://%s:%d",
             BROKER_HOST, BROKER_PORT);

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
    conn_opts.cleansession      = 1;
    conn_opts.MQTTVersion       = MQTTVERSION_5;
    conn_opts.ssl               = &ssl_opts;
    conn_opts.onFailure5        = on_connect_failure;
    conn_opts.automaticReconnect = 1;
    conn_opts.minRetryInterval   = 2;
    conn_opts.maxRetryInterval   = 60;

    /* 6. Подключение */
    printf("[MQTT] Подключение к %s...\n", server_uri);
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

    printf("[MQTT] Фоновые задачи запущены.\n");

    /* 8. Ожидание ввода для завершения */
    printf("\n");
    printf("================================================================\n");
    printf("  Клиент запущен и работает. Нажмите Enter для выхода.\n");
    printf("================================================================\n");
    printf("\n");

    (void)getchar();

    /* 9. Остановка */
    printf("[STOP] Остановка DeviceClient...\n");
    g_running = 0;

    /* Даём потокам завершиться */
    sleep_seconds(1);

    if (MQTTAsync_isConnected(g_client)) {
        MQTTAsync_disconnect(g_client, NULL);
    }
    MQTTAsync_destroy(&g_client);

    printf("[STOP] DeviceClient остановлен.\n");
    return 0;
}

/**
 * @file config.h
 * @brief Конфигурация IoT RPC Device Client (C / Windows 10+ / CLion).
 *
 * Все настраиваемые параметры собраны в одном месте.
 * Измените значения под ваше окружение перед сборкой.
 */

#ifndef IOT_RPC_CONFIG_H
#define IOT_RPC_CONFIG_H

/* ── MQTT Broker ─────────────────────────────────────────────── */
#define BROKER_HOST         "dev.leo4.ru"
#define BROKER_PORT         8883
#define BROKER_KEEPALIVE    60          /* секунды */

/* ── Сертификаты (TLS / Mutual Auth) ────────────────────────── */
#define CA_CERT_PATH        "certificates\\ca_cert.pem"
#define CLIENT_CERT_PATH    "certificates\\client_cert.pem"
#define CLIENT_KEY_PATH     "certificates\\client_key.pem"

/* ── Таймеры (секунды) ──────────────────────────────────────── */
#define REQ_POLL_INTERVAL   60          /* Опрос на наличие задач  */
#define HEALTHCHECK_INTERVAL 300        /* Keep-alive healthcheck  */

/* ── Прочее ─────────────────────────────────────────────────── */
#define MAX_TOPIC_LEN       128
#define MAX_PAYLOAD_LEN     4096
#define MAX_SN_LEN          64
#define MAX_CORR_DATA_LEN   64

/* Zero UUID используется при поллинге */
#define ZERO_UUID           "00000000-0000-0000-0000-000000000000"

#endif /* IOT_RPC_CONFIG_H */

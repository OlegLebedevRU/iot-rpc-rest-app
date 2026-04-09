/**
 * @file device_client.h
 * @brief IoT RPC Device Client — MQTT 5.0 / TLS / Mutual Auth (C).
 *
 * Основной модуль MQTT-клиента:
 *  - Подключение к брокеру с TLS (mTLS)
 *  - Подписка на srv/<SN>/tsk, rsp, cmt
 *  - Публикация в dev/<SN>/req, res, evt, ack
 *  - Фоновые циклы: polling и healthcheck
 */

#ifndef IOT_RPC_DEVICE_CLIENT_H
#define IOT_RPC_DEVICE_CLIENT_H

#include <stddef.h>

#include "MQTTAsync.h"

/**
 * Binary-safe view of MQTT 5 Correlation Data.
 * The payload is not required to be a null-terminated string.
 */
typedef struct {
    const unsigned char *data;
    size_t len;
} CorrDataView;

/**
 * Запускает IoT RPC-клиент.
 * Блокирует вызывающий поток до нажатия Enter (или Ctrl+C).
 *
 * @return 0 при нормальном завершении, != 0 при ошибке.
 */
int device_client_run(void);

/* ── Функции публикации (используются из message_handler) ──── */

/**
 * Отправляет REQ (запрос параметров задачи / поллинг).
 */
void device_client_send_request(MQTTAsync client, const char *sn,
                                const CorrDataView *correlation_data);

/**
 * Отправляет ACK (подтверждение получения tsk).
 */
void device_client_send_ack(MQTTAsync client, const char *sn,
                            const CorrDataView *correlation_data);

/**
 * Отправляет RES (результат выполнения задачи).
 */
void device_client_send_result(MQTTAsync client, const char *sn,
                               const CorrDataView *correlation_data,
                               const char *result_json);

/**
 * Отправляет EVT (асинхронное событие).
 */
void device_client_send_event(MQTTAsync client, const char *sn,
                              int event_type_code,
                              const char *event_json);

#endif /* IOT_RPC_DEVICE_CLIENT_H */

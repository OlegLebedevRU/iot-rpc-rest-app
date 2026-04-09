/**
 * @file message_handler.h
 * @brief Обработчик входящих MQTT-сообщений (маршрутизация по топикам).
 */

#ifndef IOT_RPC_MESSAGE_HANDLER_H
#define IOT_RPC_MESSAGE_HANDLER_H

#include <stddef.h>

#include "config.h"
#include "device_client.h"
#include "MQTTAsync.h"

#ifdef _WIN32
#  include <windows.h>
#else
#  include <pthread.h>
#endif

/**
 * Контекст обработчика сообщений.
 * Содержит топики подписки и callback-и для ответных действий.
 */
typedef struct {
    /* Серийный номер устройства */
    char serial_number[64];

    /* Топики подписки (сервер → устройство) */
    char topic_rsp[128];
    char topic_tsk[128];
    char topic_cmt[128];
    char topic_eva[128];

    /* Указатель на MQTT-клиент для отправки ответов */
    MQTTAsync client;

    /* Активный RPC corr_id, чтобы polling REQ(UUID0) не перебивал trigger/payload flow */
    unsigned char active_corr_data[MAX_CORR_DATA_LEN];
    size_t active_corr_len;
    int active_task;

#ifdef _WIN32
    CRITICAL_SECTION state_lock;
#else
    pthread_mutex_t state_lock;
#endif
} MessageHandlerCtx;

/**
 * Инициализирует контекст обработчика.
 *
 * @param ctx   Контекст для инициализации.
 * @param sn    Серийный номер устройства.
 * @param client MQTT-клиент.
 */
void msg_handler_init(MessageHandlerCtx *ctx, const char *sn, MQTTAsync client);

/** Освобождает ресурсы контекста. */
void msg_handler_cleanup(MessageHandlerCtx *ctx);

/** Возвращает 1, если клиент уже обрабатывает активную RPC-задачу. */
int msg_handler_has_active_task(MessageHandlerCtx *ctx);

/**
 * Обрабатывает входящее MQTT-сообщение.
 *
 * @param ctx       Контекст обработчика.
 * @param topic     Топик сообщения.
 * @param topic_len Длина топика.
 * @param message   MQTT-сообщение.
 */
void msg_handler_on_message(MessageHandlerCtx *ctx,
                            const char *topic, int topic_len,
                            MQTTAsync_message *message);

#endif /* IOT_RPC_MESSAGE_HANDLER_H */

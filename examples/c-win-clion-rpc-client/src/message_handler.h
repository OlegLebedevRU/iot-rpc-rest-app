/**
 * @file message_handler.h
 * @brief Обработчик входящих MQTT-сообщений (маршрутизация по топикам).
 */

#ifndef IOT_RPC_MESSAGE_HANDLER_H
#define IOT_RPC_MESSAGE_HANDLER_H

#include "MQTTAsync.h"

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
} MessageHandlerCtx;

/**
 * Инициализирует контекст обработчика.
 *
 * @param ctx   Контекст для инициализации.
 * @param sn    Серийный номер устройства.
 * @param client MQTT-клиент.
 */
void msg_handler_init(MessageHandlerCtx *ctx, const char *sn, MQTTAsync client);

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

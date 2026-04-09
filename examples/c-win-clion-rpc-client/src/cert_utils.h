/**
 * @file cert_utils.h
 * @brief Утилиты для работы с X.509 сертификатами (OpenSSL).
 */

#ifndef IOT_RPC_CERT_UTILS_H
#define IOT_RPC_CERT_UTILS_H

#include <stddef.h>

/**
 * Извлекает значение CN (Common Name) из PEM-сертификата клиента.
 *
 * @param cert_path  Путь к PEM-файлу сертификата.
 * @param cn_buf     Буфер для результата (SN).
 * @param cn_buf_len Размер буфера.
 * @return 0 при успехе, -1 при ошибке.
 */
int extract_cn_from_cert(const char *cert_path, char *cn_buf, size_t cn_buf_len);

#endif /* IOT_RPC_CERT_UTILS_H */

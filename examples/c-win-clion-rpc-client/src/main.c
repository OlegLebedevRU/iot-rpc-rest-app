/**
 * @file main.c
 * @brief Точка входа IoT RPC Device Client (C / Windows 10+ / CLion).
 */

#include "device_client.h"

#include <stdio.h>
#include <locale.h>

#ifdef _WIN32
#  include <windows.h>
#endif

int main(void)
{
#ifdef _WIN32
    /* Настраиваем UTF-8 и для вывода, и для ввода в консоли Windows. */
    if (!SetConsoleOutputCP(CP_UTF8)) {
        fprintf(stderr, "[WARN] Failed to set UTF-8 output (SetConsoleOutputCP).\n");
    }
    if (!SetConsoleCP(CP_UTF8)) {
        fprintf(stderr, "[WARN] Failed to set UTF-8 input (SetConsoleCP).\n");
    }
#endif

    if (!setlocale(LC_ALL, ".UTF-8")) {
        /* Fallback на системную локаль, если UTF-8 недоступен. */
        setlocale(LC_ALL, "");
    }

    printf("\n");
    printf("================================================================\n");
    printf("       IoT RPC Device Client  (C / Paho MQTT 5.0)\n");
    printf("       Windows 10+ | TLS 1.2 | Mutual Auth | CLion\n");
    printf("================================================================\n");
    printf("\n");

    return device_client_run();
}

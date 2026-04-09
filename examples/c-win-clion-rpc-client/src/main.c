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
    /* Корректный вывод UTF-8 в консоли Windows */
    SetConsoleOutputCP(65001);
#endif
    setlocale(LC_ALL, "");

    printf("\n");
    printf("================================================================\n");
    printf("       IoT RPC Device Client  (C / Paho MQTT 5.0)\n");
    printf("       Windows 10+ | TLS 1.2 | Mutual Auth | CLion\n");
    printf("================================================================\n");
    printf("\n");

    return device_client_run();
}

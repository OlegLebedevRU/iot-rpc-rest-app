cmake_minimum_required(VERSION 3.16)
project(iot_rpc_device_client C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

# ═══════════════════════════════════════════════════════════════
# Опции сборки
# ═══════════════════════════════════════════════════════════════
option(USE_VCPKG "Использовать vcpkg для зависимостей" OFF)

# ═══════════════════════════════════════════════════════════════
# Зависимости
# ═══════════════════════════════════════════════════════════════

# --- OpenSSL ------------------------------------------------
find_package(OpenSSL REQUIRED)

# --- Eclipse Paho MQTT C ------------------------------------
# Вариант 1: Через vcpkg / find_package (если USE_VCPKG=ON)
# Вариант 2: Через FetchContent (по умолчанию)
if(USE_VCPKG)
    find_package(eclipse-paho-mqtt-c CONFIG REQUIRED)
    set(PAHO_TARGET eclipse-paho-mqtt-c::paho-mqtt3as)
else()
    include(FetchContent)
    FetchContent_Declare(
        paho_mqtt_c
        GIT_REPOSITORY https://github.com/eclipse-paho/paho.mqtt.c.git
        GIT_TAG        v1.3.14
    )
    set(PAHO_WITH_SSL      ON  CACHE BOOL "" FORCE)
    set(PAHO_BUILD_SHARED  OFF CACHE BOOL "" FORCE)
    set(PAHO_BUILD_STATIC  ON  CACHE BOOL "" FORCE)
    set(PAHO_ENABLE_TESTING OFF CACHE BOOL "" FORCE)
    set(PAHO_HIGH_PERFORMANCE ON CACHE BOOL "" FORCE)
    FetchContent_MakeAvailable(paho_mqtt_c)
    set(PAHO_TARGET paho-mqtt3as-static)
endif()

# ═══════════════════════════════════════════════════════════════
# Исполняемый файл
# ═══════════════════════════════════════════════════════════════
add_executable(${PROJECT_NAME}
    src/main.c
    src/device_client.c
    src/device_client.h
    src/message_handler.c
    src/message_handler.h
    src/cert_utils.c
    src/cert_utils.h
    src/openssl_applink.c
    src/config.h
)

target_include_directories(${PROJECT_NAME} PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/src
)

target_link_libraries(${PROJECT_NAME} PRIVATE
    ${PAHO_TARGET}
    OpenSSL::SSL
    OpenSSL::Crypto
)

# Windows-специфичные библиотеки
if(WIN32)
    target_link_libraries(${PROJECT_NAME} PRIVATE ws2_32 crypt32)

    # CLion часто запускает exe без PATH к OpenSSL/bin, поэтому
    # копируем runtime DLL рядом с исполняемым файлом.
    set(OPENSSL_RUNTIME_DLLS)
    if(OPENSSL_ROOT_DIR AND EXISTS "${OPENSSL_ROOT_DIR}/bin")
        file(GLOB OPENSSL_RUNTIME_DLLS
            "${OPENSSL_ROOT_DIR}/bin/libssl*.dll"
            "${OPENSSL_ROOT_DIR}/bin/libcrypto*.dll"
        )
    endif()

    list(REMOVE_DUPLICATES OPENSSL_RUNTIME_DLLS)

    if(OPENSSL_RUNTIME_DLLS)
        add_custom_command(TARGET ${PROJECT_NAME} POST_BUILD
            COMMAND ${CMAKE_COMMAND} -E copy_if_different
                ${OPENSSL_RUNTIME_DLLS}
                $<TARGET_FILE_DIR:${PROJECT_NAME}>
            COMMAND_EXPAND_LISTS
            COMMENT "Копирование OpenSSL DLL рядом с выходным файлом"
        )
    endif()
endif()

# Копирование папки certificates рядом с бинарником
add_custom_command(TARGET ${PROJECT_NAME} POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_directory
        "${CMAKE_CURRENT_SOURCE_DIR}/certificates"
        "$<TARGET_FILE_DIR:${PROJECT_NAME}>/certificates"
    COMMENT "Копирование сертификатов в выходную директорию"
)

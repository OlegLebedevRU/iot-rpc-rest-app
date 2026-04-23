FROM debian:bookworm-slim

# Установка Nginx и OpenSSL (legacy.so входит в libssl3)
RUN apt-get update && \
    apt-get install -y nginx openssl && \
    rm -rf /var/lib/apt/lists/*

# Создаём директории
RUN mkdir -p /crt /usr/lib/ssl

# Копируем файлы
COPY crt/legacy_cert_dev_leo4_ru.crt /crt/legacy_cert_dev_leo4_ru.crt
COPY crt/key_0000.pem /crt/server_key.pem
COPY crt/ca_legacy.crt /crt/ca_legacy.crt

# Конфигурация OpenSSL встроена в образ (без файла в build-context):
# включаем legacy provider и опускаем SECLEVEL до 0 — это основная задача
# контура nginx-mutual (mTLS со старыми/слабыми клиентскими сертификатами).
COPY <<` /etc/ssl/openssl.cnf
[openssl_init]
providers = provider_sect

[provider_sect]
default = default_sect
legacy = legacy_sect

[default_sect]
activate = 1

[legacy_sect]
activate = 1
library = /usr/lib/x86_64-linux-gnu/ossl-modules/legacy.so


[system_default_sect]
MinProtocol = TLSv1.0
CipherString = DEFAULT@SECLEVEL=0
`
RUN ln -sf /etc/ssl/openssl.cnf /usr/lib/ssl/openssl.cnf

# Переменная окружения
ENV OPENSSL_CONF=/etc/ssl/openssl.cnf

# Копируем конфиг Nginx
COPY nginx-configs/dev_leo4_ru/internal_ssl.conf /etc/nginx/conf.d/internal_ssl.conf

# Проверка
RUN nginx -t

EXPOSE 4443

CMD ["nginx", "-g", "daemon off;"]
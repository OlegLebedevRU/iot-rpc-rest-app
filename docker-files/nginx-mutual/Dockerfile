FROM debian:bookworm-slim

# Установка Nginx и OpenSSL с legacy провайдером
RUN apt-get update && \
    apt-get install -y nginx openssl libssl3-contrib && \
    rm -rf /var/lib/apt/lists/*

# Создаём директории
RUN mkdir -p /crt /usr/lib/ssl

# Копируем файлы
COPY crt/legacy_cert_dev_leo4_ru.crt /crt/legacy_cert_dev_leo4_ru.crt
COPY crt/key_0000.pem /crt/server_key.pem
COPY crt/ca_legacy.crt /crt/ca_legacy.crt

# Копируем конфигурацию OpenSSL
COPY crt/openssl.cnf /etc/ssl/openssl.cnf
RUN ln -sf /etc/ssl/openssl.cnf /usr/lib/ssl/openssl.cnf

# Переменная окружения
ENV OPENSSL_CONF=/etc/ssl/openssl.cnf

# Копируем конфиг Nginx
COPY nginx-configs/dev_leo4_ru/internal_ssl.conf /etc/nginx/conf.d/internal_ssl.conf

# Проверка
RUN nginx -t

EXPOSE 4443

CMD ["nginx", "-g", "daemon off;"]
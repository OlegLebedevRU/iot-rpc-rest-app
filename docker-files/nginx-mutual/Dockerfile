FROM nginx:alpine

# Установка OpenSSL и legacy провайдера — КРИТИЧЕСКИ ВАЖНО
RUN apk --no-cache add openssl && \
    apk --no-cache add --repository=http://dl-cdn.alpinelinux.org/alpine/edge/community openssl-legacy-provider


# Создаём директорию /crt и /usr/lib/ssl (если не существует)
RUN mkdir -p /crt && mkdir -p /usr/lib/ssl

# Копируем файлы на этапе сборки — гарантируем наличие
COPY crt/legacy_cert_dev_leo4_ru.crt /crt/legacy_cert_dev_leo4_ru.crt
COPY crt/key_0000.pem /crt/server_key.pem
COPY crt/ca_legacy.crt /crt/ca_legacy.crt

# Копируем конфигурацию OpenSSL
COPY crt/openssl.cnf /etc/ssl/openssl.cnf
RUN ln -sf /etc/ssl/openssl.cnf /usr/lib/ssl/openssl.cnf

ENV OPENSSL_CONF=/etc/ssl/openssl.cnf

# Копируем конфиг Nginx
COPY nginx-configs/dev_leo4_ru/internal_ssl.conf /etc/nginx/conf.d/internal_ssl.conf

# Проверка
RUN nginx -t

CMD ["nginx", "-g", "daemon off;"]
FROM nginx:alpine

# Установка OpenSSL и утилит для работы с легаси CA
RUN apk --no-cache add \
    openssl \
    curl \
    ca-certificates

# Создаём директорию для модулей OpenSSL
RUN mkdir -p /usr/lib/ssl/engines-3
# Создаём директорию /crt (на всякий случай, чтобы избежать конфликта)
RUN mkdir -p /crt

# Копируем файлы на этапе сборки — гарантируем наличие
COPY crt/legacy_cert_dev_leo4_ru.crt /crt/legacy_cert_dev_leo4_ru.crt
COPY crt/key_0000.pem /crt/server_key.pem
COPY crt/ca_legacy.crt /crt/ca_legacy.crt
# Копируем конфигурацию OpenSSL на этапе сборки
COPY crt/openssl.cnf /etc/ssl/openssl.cnf

# Создаём симлинк в OPENSSLDIR (на случай, если используется)
RUN ln -sf /etc/ssl/openssl.cnf /usr/lib/ssl/openssl.cnf

# Экспорт переменной окружения
ENV OPENSSL_CONF=/etc/ssl/openssl.cnf

# Копируем конфиг Nginx
COPY nginx-configs/dev_leo4_ru/internal_ssl.conf /etc/nginx/conf.d/internal_ssl.conf
WORKDIR /

# Копируем конфиг Nginx
COPY <<` /etc/nginx/nginx.conf
daemon off;
user  nginx;
worker_processes  auto;

error_log  /dev/stderr notice;
pid        /var/run/nginx.pid;



events {
    worker_connections  1024;
}

http {
    include       /etc/nginx/mime.types;
    default_type  application/octet-stream;
    log_format custom '$remote_addr - $remote_user [$time_local] "$request" $status $body_bytes_sent "$http_referer" "$http_user_agent"';
    log_format ssl_debug '$remote_addr - $remote_user [$time_local] "$request" '
                        'ssl_verify:$ssl_client_verify '
                        'ssl_dn:"$ssl_client_s_dn" '
                        'ssl_issuer:"$ssl_client_i_dn" '
                        'status:$status '
                        'body_bytes_sent:$body_bytes_sent '
                        '"$http_referer" "$http_user_agent"';

    include /etc/nginx/conf.d/*.conf;
}
`
# Проверка конфигурации
RUN nginx -t

# Запуск
CMD ["nginx", "-g", "daemon off;"]
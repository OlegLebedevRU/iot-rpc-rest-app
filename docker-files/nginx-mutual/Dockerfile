FROM nginx:alpine

# Установка OpenSSL и утилит для работы с легаси CA
RUN apk --no-cache add \
    openssl \
    curl \
    ca-certificates

# Создаём директорию для модулей OpenSSL
RUN mkdir -p /usr/lib/ssl/engines-3

# Копируем конфигурацию OpenSSL на этапе сборки
COPY crt/openssl.cnf /etc/ssl/openssl.cnf

# Создаём симлинк в OPENSSLDIR (на случай, если используется)
RUN ln -sf /etc/ssl/openssl.cnf /usr/lib/ssl/openssl.cnf

# Экспорт переменной окружения
ENV OPENSSL_CONF=/etc/ssl/openssl.cnf

# Копируем конфиг Nginx
COPY nginx-configs/dev_leo4_ru/internal_ssl.conf /etc/nginx/conf.d/internal_ssl.conf

# Проверка конфигурации
RUN nginx -t

# Запуск
CMD ["nginx", "-g", "daemon off;"]
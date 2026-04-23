FROM debian:bookworm-slim

# Установка базовых пакетов
RUN <<`
  set -e
  apt-get update
  apt-get upgrade -y
  apt-get install -y \
    less nano \
    libjansson4 libjwt0 \
    curl gnupg2 ca-certificates \
    lsb-release debian-archive-keyring \
    openssl
`

# nginx-jwt работает с современными сертификатами и стандартным OpenSSL
# из debian:bookworm-slim. Никакой настройки legacy provider / SECLEVEL=0
# здесь не требуется — оставляем дефолтную конфигурацию /etc/ssl/openssl.cnf.
# Контур для legacy-сертификатов вынесен в отдельный образ nginx-mutual.

# Добавляем ключ Nginx
RUN <<`
  set -e
  curl https://nginx.org/keys/nginx_signing.key | gpg --dearmor > /usr/share/keyrings/nginx-archive-keyring.gpg
  printf "deb [signed-by=/usr/share/keyrings/nginx-archive-keyring.gpg] http://nginx.org/packages/mainline/debian $(lsb_release -cs) nginx\n" > /etc/apt/sources.list.d/nginx.list
  printf "Package: *\nPin: origin nginx.org\nPin: release o=nginx\nPin-Priority: 900\n" > /etc/apt/preferences.d/99nginx
`

# Установка Nginx
RUN <<`
  set -e
  apt-get update
  apt-get install -y nginx=1.29.4*
`

WORKDIR /usr/lib/nginx/modules

# Установка JWT модуля
RUN curl -Ls https://github.com/TeslaGov/ngx-http-auth-jwt-module/releases/download/2.4.0/ngx-http-auth-jwt-module-2.4.0_libjwt-1.15.3_nginx-1.29.4.tgz | tar -zx > ngx_http_auth_jwt_module.so

# Симлинк для libjwt
RUN ln -s /usr/lib/x86_64-linux-gnu/libjwt.so.0 /usr/lib/x86_64-linux-gnu/libjwt.so.2

WORKDIR /

# Копируем конфиг Nginx
COPY <<` /etc/nginx/nginx.conf
daemon off;
user  nginx;
worker_processes  auto;

error_log  /dev/stderr notice;
pid        /var/run/nginx.pid;

load_module /usr/lib/nginx/modules/ngx_http_auth_jwt_module.so;

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

RUN nginx -t

CMD ["nginx"]
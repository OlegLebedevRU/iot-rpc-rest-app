ARG CONF_FILE="./nginx-configs/local-light/nginx.conf"
FROM debian:bookworm-slim

RUN <<`
  set -e
  apt-get update
  apt-get upgrade -y
  apt-get install -y less nano libjansson4 libjwt0 curl gnupg2 ca-certificates lsb-release debian-archive-keyring
`

RUN <<`
  set -e
  curl https://nginx.org/keys/nginx_signing.key | gpg --dearmor > /usr/share/keyrings/nginx-archive-keyring.gpg
  printf "deb [signed-by=/usr/share/keyrings/nginx-archive-keyring.gpg] http://nginx.org/packages/mainline/debian `lsb_release -cs` nginx\n" > /etc/apt/sources.list.d/nginx.list
  printf "Package: *\nPin: origin nginx.org\nPin: release o=nginx\nPin-Priority: 900\n" > /etc/apt/preferences.d/99nginx
`

RUN <<`
  set -e
  apt-get update
  apt-get install -y nginx=1.27.4*
`

WORKDIR /usr/lib/nginx/modules

RUN curl -Ls https://github.com/TeslaGov/ngx-http-auth-jwt-module/releases/download/2.3.1/ngx-http-auth-jwt-module-2.3.1_libjwt-1.15.3_nginx-1.27.4.tgz | tar -zx > ngx_http_auth_jwt_module.so

RUN ln -s /usr/lib/x86_64-linux-gnu/libjwt.so.0 /usr/lib/x86_64-linux-gnu/libjwt.so.2

WORKDIR /

RUN --mount=type=bind,source=${PWD}/iot-rpc-rest-app/nginx-configs/local-light/nginx.test.conf,target=/etc/nginx/nginx.conf
# ${CONF_FILE}
#COPY <<` /etc/nginx/nginx.conf
#daemon off;
#user  nginx;
#worker_processes  auto;
#
#error_log  /dev/stderr notice;
#pid        /var/run/nginx.pid;
#
#load_module /usr/lib/nginx/modules/ngx_http_auth_jwt_module.so;
#
#events {
#    worker_connections  1024;
#}
#
#http {
#    include       /etc/nginx/mime.types;
#    default_type  application/octet-stream;
#
#    auth_jwt_enabled off;
#    resolver 127.0.0.11;
#    upstream app {
#    server app1:3031;
#    }
#    server {
#      listen 80;
#
#      location / {
#        proxy_pass http://app;
#      }
#    }
#}
#`

RUN nginx -t

CMD ["nginx", "-g", "daemon off;"]
# sudo docker network create -d bridge net1
# sudo docker run --name=ngx --network=net1 --network-alias ngx -p 80:80 'ngx'

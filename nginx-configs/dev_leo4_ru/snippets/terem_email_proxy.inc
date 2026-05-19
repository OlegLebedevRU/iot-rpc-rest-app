auth_jwt_enabled off;

if ($terem_device_id = "") {
    return 403 "Forbidden: client certificate OU is required\n";
}

proxy_pass https://terem_email_gateway/backend-api/v1/send-email/$terem_device_id$is_args$args;
proxy_http_version 1.1;
proxy_set_header Host d5dbnvm0kd5ames2tb0o.apigw.yandexcloud.net;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto https;
proxy_set_header X-SSL-Client-Verify $ssl_client_verify;
proxy_set_header X-SSL-Client-Subject $ssl_client_s_dn;
proxy_set_header X-Device-Id $terem_device_id;
proxy_ssl_server_name on;
proxy_ssl_name d5dbnvm0kd5ames2tb0o.apigw.yandexcloud.net;
proxy_request_buffering off;
proxy_buffering off;

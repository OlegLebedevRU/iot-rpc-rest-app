import json
import logging
import random
import urllib.parse
from datetime import datetime

from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import APIRouter, Request, Response

from core import settings

log = logging.getLogger(__name__)

legacy_router = APIRouter(
    prefix=settings.api.v1.devices,
    tags=["Legacy"],
    include_in_schema=False,
)

# Константа platform
PLATFORM = "4"


def generate_device_sn(device_number: int) -> str:
    """
    Генерирует серийный номер устройства в формате:
    a{platform}b{device_part}c{random_part}d{date_part}
    Пример: a4b0000123c58392d290825
    """
    # Поле между b и c: 7 цифр, дополненных слева нулями
    device_part = f"{device_number:07d}"

    # Поле между c и d: 5 случайных цифр, первая не ноль
    rand_first = str(random.randint(1, 9))
    rand_rest = "".join([str(random.randint(0, 9)) for _ in range(4)])
    random_part = rand_first + rand_rest

    # Дата после d: ddmmyy
    date_part = datetime.now().strftime("%d%m%y")

    # Формируем строку с разделителями b, c, d
    return f"a{PLATFORM}b{device_part}c{random_part}d{date_part}"


def parse_cert(pem_data: str) -> dict:
    """
    Парсит PEM-сертификат и возвращает словарь с данными.
    """
    try:
        cert = x509.load_pem_x509_certificate(pem_data.encode(), default_backend())
        subject = cert.subject
        issuer = cert.issuer
        serial = cert.serial_number

        def get_attr(oid):
            attrs = subject.get_attributes_for_oid(oid)
            return attrs[0].value if attrs else None

        cn = get_attr(x509.NameOID.COMMON_NAME)
        ou = get_attr(x509.NameOID.ORGANIZATIONAL_UNIT_NAME)
        o = get_attr(x509.NameOID.ORGANIZATION_NAME)

        return {
            "subject": str(subject),
            "issuer": str(issuer),
            "cn": cn,
            "ou": ou,
            "o": o,
            "serial": serial,
        }
    except Exception as e:
        log.error("Failed to parse certificate: %s", e)
        return {"error": "Invalid or malformed certificate", "details": str(e)}


def generate_key_and_csr(device_sn: str) -> tuple[str, str]:
    """
    Генерирует RSA-ключ (2048 бит) и CSR с CN=устройства.
    Возвращает кортеж: (private_key_pem, csr_pem)
    """
    # Генерация закрытого ключа
    private_key = rsa.generate_private_key(
        public_exponent=65537, key_size=2048, backend=default_backend()
    )

    # Сериализация закрытого ключа в PEM (без шифрования)
    private_key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    # Извлекаем device_part из device_sn для заполнения OU, email и DNS
    device_part = device_sn.split("b")[1].split("c")[0]  # извлекаем 7-значный номер

    # Создание Subject для CSR: CN остаётся как device_sn (по текущей логике)
    subject = x509.Name(
        [
            x509.NameAttribute(x509.NameOID.COMMON_NAME, device_sn),
            x509.NameAttribute(x509.NameOID.ORGANIZATION_NAME, "Leo4"),  # O = Leo4
            x509.NameAttribute(
                x509.NameOID.ORGANIZATIONAL_UNIT_NAME, device_part
            ),  # OU = device_part
            x509.NameAttribute(x509.NameOID.COUNTRY_NAME, "RU"),
        ]
    )

    # Добавляем альтернативные имена (SAN)
    alt_names = [
        x509.DNSName(f"Leo4-{device_part}.ru"),  # DNS.1
        x509.RFC822Name(f"{device_part}@leo4.ru"),  # emailAddress
    ]

    # Создание CSR с расширением subjectAltName
    builder = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(subject)
        .add_extension(
            x509.SubjectAlternativeName(alt_names),
            critical=False,
        )
    )

    csr = builder.sign(private_key, hashes.SHA256(), default_backend())

    # Сериализация CSR в PEM
    csr_pem = csr.public_bytes(serialization.Encoding.PEM).decode("utf-8")

    return private_key_pem.strip(), csr_pem.strip()


@legacy_router.get("/map_legacy_crt/")
async def map_cert(request: Request):
    """
    Принимает X-SSL-Client-Cert, декодирует и возвращает информацию о сертификате.
    Добавляет:
    - device_sn — сгенерированный серийный номер
    - private_key — закрытый ключ в формате PEM
    - csr — запрос на подпись сертификата (CSR) в формате PEM
    """
    escaped_cert = request.headers.get("X-SSL-Client-Cert")
    if not escaped_cert:
        return Response(
            content="No client certificate provided",
            status_code=400,
            media_type="text/plain",
        )

    try:
        # Декодируем URL-encoded PEM
        pem_cert = urllib.parse.unquote(escaped_cert)
        cert_info = parse_cert(pem_cert)

        # Проверяем наличие ошибки
        if "error" in cert_info:
            return Response(
                content=json.dumps(cert_info),
                status_code=400,
                media_type="application/json",
            )

        # Извлекаем device_number из поля "ou"
        ou_value = cert_info.get("ou")
        device_number = 0
        if ou_value and isinstance(ou_value, str):
            digits = "".join(filter(str.isdigit, ou_value))
            device_number = int(digits) if digits else 0

        # Генерируем device_sn
        device_sn = generate_device_sn(device_number=device_number)

        # Генерируем закрытый ключ и CSR
        private_key_pem, csr_pem = generate_key_and_csr(device_sn)

        # Добавляем новые поля в ответ
        cert_info.update(
            {"device_sn": device_sn, "private_key": private_key_pem, "csr": csr_pem}
        )

        return Response(content=json.dumps(cert_info), media_type="application/json")
    except Exception as e:
        log.error("Error processing certificate or generating key/csr: %s", e)
        return Response(
            content=f"Error: {str(e)}", status_code=500, media_type="text/plain"
        )


#
# @legacy_router.get("/certificates/")
# async def legacy(
#     function: Annotated[str, Query],
#     pin: Annotated[str, Query],
#     tosign: Annotated[str, Query],
#     request: Request,
# ):
#     log.info("get certificates req %s, %s", request.url, request.query_params)
#     return Response(
#         content="""<?xml version = \"1.0\" encoding = \"windows-1251\"?>
# <Response>
#     <Result>OK</Result>
#     <code>0</code>
#     <CERTDATA>
#         <catype>SubCA</catype>
#         <prov>Microsoft Enhanced Cryptographic Provider v1.0</prov>
#         <dn>CN=34360826,O=509,OU=1003002,S=msk,C=ru,L=2913,E=1.terminal@forpay.ru</dn>
#         <pin>J31AG2</pin>
#         <sign>04C518FFE1B924CEB2F6A0BF2C73939D</sign>
#     </CERTDATA>
# </Response>
#     """,
#         media_type="application/xml",
#     )
#
#
# @legacy_router.post("/certificates/")
# async def legacy1(
#     function: Annotated[str, Query],
#     pin: Annotated[str, Query],
#     cpserial: Annotated[str, Query],
#     request: Request,
# ):
#     body = await request.body()
#
#     log.info("post certificates %s", body)
#     log.info("post certificates header %s", request.headers)
#     return Response(
#         media_type="application/xml",
#         content="""<?xml version = \"1.0\" encoding = \"windows-1251\"?><Response><Result>OK</Result><code>0</code><CERTDATA>MIIHMQYJKoZIhvcNAQcCoIIHIjCCBx4CAQExADALBgkqhkiG9w0BBwGgggcGMIID
# HTCCAgUCFAHwtCMAppNJg4LFRKJCdHH7D4ZCMA0GCSqGSIb3DQEBCwUAMH8xCzAJ
# BgNVBAYTAlJVMQ8wDQYDVQQIDAZNb3Njb3cxDzANBgNVBAcMBk1vc2NvdzENMAsG
# A1UECgwETGVvNDELMAkGA1UECwwCQ0ExEDAOBgNVBAMMB2NlcnRzcnYxIDAeBgkq
# hkiG9w0BCQEWEWxlZ2FjeV9jYUBsZW80LnJ1MB4XDTI1MTAwNDE5Mjg0MFoXDTI1
# MTIwMzE5Mjg0MFowgZoxIzAhBgkqhkiG9w0BCQEWFDEudGVybWluYWxAZm9ycGF5
# LnJ1MQ0wCwYDVQQHDAQyOTEzMQswCQYDVQQGEwJydTEMMAoGA1UECAwDbXNrMRAw
# DgYDVQQLDAcxMDAzMDAyMQwwCgYDVQQKDAM1MDkxKTAnBgNVBAMMIDA0QzUxOEZG
# RTFCOTI0Q0VCMkY2QTBCRjJDNzM5MzlEMIGfMA0GCSqGSIb3DQEBAQUAA4GNADCB
# iQKBgQC9Cn36/JhRfyY2UyQa6YjtFajyKohNBpaeA9EXJ7Lp/7RStOrOIN0NXExM
# tzcHNjDWe45LC7CbBf7t17agpaaEU6+zHfEcq/wVzcwpQJCZNkNmMrWL15VqlUaW
# IlITWQG5L/lP6d79zEv9QeEeGp3C27Sg2Jd58zQ2LaLH/KkWzQIDAQABMA0GCSqG
# SIb3DQEBCwUAA4IBAQBtu4XBpKBgUguES5wi9gyrSQf2PA2Qq3NYIeS/TRnmP+sP
# biPwdMXPCJiQpw4L+CnUlgIWYKdyYtpf/ZHX582ZULMLN6X6PBZrI/gZy5RMF2p6
# 8xBSnL55eGacp9DGyCPLnmZJkjqCXUuuvm4K114f67NYGaH+GWwkfQsvJQCuLF9a
# q83SQJa8LyzcdKr2uUY75g+OHmqE88zEsFFiT3k1lIrMgbG05O0EspAD4VXD5/vl
# jIfCmBYqnq2YMwOpza5KggEpV7fhf9ZqPJjPXq38wbp3za++94Mv9TYMZROEStOf
# 8mEbOYZSPFgzoyDyJumc2SE8LALdD7FUl+7vXI14MIID4TCCAsmgAwIBAgIUOk5A
# ZrJxVjGjDBLmsY2exoMZ1nIwDQYJKoZIhvcNAQELBQAwfzELMAkGA1UEBhMCUlUx
# DzANBgNVBAgMBk1vc2NvdzEPMA0GA1UEBwwGTW9zY293MQ0wCwYDVQQKDARMZW80
# MQswCQYDVQQLDAJDQTEQMA4GA1UEAwwHY2VydHNydjEgMB4GCSqGSIb3DQEJARYR
# bGVnYWN5X2NhQGxlbzQucnUwIBcNMjUxMDA0MTg1MzQyWhgPMjA1NTA5MjcxODUz
# NDJaMH8xCzAJBgNVBAYTAlJVMQ8wDQYDVQQIDAZNb3Njb3cxDzANBgNVBAcMBk1v
# c2NvdzENMAsGA1UECgwETGVvNDELMAkGA1UECwwCQ0ExEDAOBgNVBAMMB2NlcnRz
# cnYxIDAeBgkqhkiG9w0BCQEWEWxlZ2FjeV9jYUBsZW80LnJ1MIIBIjANBgkqhkiG
# 9w0BAQEFAAOCAQ8AMIIBCgKCAQEA606ml3Cjn54vv7dMuIVLuXAQJ2TaDmhWG9Iv
# Dyzre7U0iJ4+oq48DoLfEF/svd9MQMqW4k4nGpI7Pij5vGCwNYOqo/viqGaUc1PR
# rrUYBJbBls2bOjml8w8vU05fleJFZ+7sywOb1X/VIhBr0np5iXJfiCIkS8sK5Sxv
# Rf1xBJ0318r5IzOIVESSL49/zEOrNfucQdKS8HcxZkh8AUBP27Slj3KbdUPZaiKS
# 6w5+FmJumP/jIYjUmqH/Jcxom6dwSoSTohGPdo1fD1EQeN7jCB/L+K1Ho0KtuvTx
# QtwRzp/vmPEXnKwcswIOml0RmzWRFkrJYhpOh2uEIH7AMgisSQIDAQABo1MwUTAd
# BgNVHQ4EFgQUC6p/vcnhcyNCpKoD4suO8UXIh60wHwYDVR0jBBgwFoAUC6p/vcnh
# cyNCpKoD4suO8UXIh60wDwYDVR0TAQH/BAUwAwEB/zANBgkqhkiG9w0BAQsFAAOC
# AQEAvOwmRfqoZyluerluqu5M/9B30Ds5MjDBN+SVsK6/I1VmEhIatMlEMw7FbEAt
# 8AVVcGX2RitXOebrTQ70Mo/BGHVYIzaSbDCh1XF0F2fvNyf5W0EBWIGGIJDk355L
# CZiZirKiffmSYWS80T+5qEKigtmXHYDvYlT1fkg9iuq4wSiXS9d9kKCLYdM7EOhE
# WhKpVhzwHtiXTvlBgN76TNRm8+UWrB9lwUoXHdEnHGoDSdcXe3E8BaqdZumubBof
# Iwhyxw+N7cidSAkMpADPD3xNRZXWfA63L1hVR+LRH1Zbc11ud7TISE09Zfwk10KV
# ntMthogBXjOtAXyT85oPUAKDdDEA
# </CERTDATA></Response>""",
#     )

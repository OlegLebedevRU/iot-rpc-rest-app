# services/legacy.py
import logging
import random
import urllib.parse
from datetime import datetime, timedelta
from typing import Dict, Tuple

import httpx
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy.ext.asyncio import AsyncSession

from core import settings
from core.crud.device_repo import DeviceRepo

log = logging.getLogger(__name__)

PLATFORM = "4"


def generate_device_sn(device_number: int) -> str:
    device_part = f"{device_number:07d}"
    rand_first = str(random.randint(1, 9))
    rand_rest = "".join([str(random.randint(0, 9)) for _ in range(4)])
    random_part = rand_first + rand_rest
    date_part = datetime.now().strftime("%d%m%y")
    return f"a{PLATFORM}b{device_part}c{random_part}d{date_part}"


def parse_cert(pem_data: str) -> dict:
    try:
        cert = x509.load_pem_x509_certificate(pem_data.encode(), default_backend())
        subject = cert.subject
        issuer = cert.issuer
        serial = cert.serial_number

        def get_attr(oid):
            attrs = subject.get_attributes_for_oid(oid)
            return attrs[0].value if attrs else None

        return {
            "subject": str(subject),
            "issuer": str(issuer),
            "cn": get_attr(x509.NameOID.COMMON_NAME),
            "ou": get_attr(x509.NameOID.ORGANIZATIONAL_UNIT_NAME),
            "o": get_attr(x509.NameOID.ORGANIZATION_NAME),
            "serial": serial,
        }
    except Exception as e:
        log.error("Failed to parse certificate: %s", e)
        return {"error": "Invalid or malformed certificate", "details": str(e)}


def generate_key_and_csr(device_sn: str) -> Tuple[str, str]:
    private_key = rsa.generate_private_key(
        public_exponent=65537, key_size=2048, backend=default_backend()
    )

    private_key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    device_part = device_sn.split("b")[1].split("c")[0]

    subject = x509.Name(
        [
            x509.NameAttribute(x509.NameOID.COMMON_NAME, device_sn),
            x509.NameAttribute(x509.NameOID.ORGANIZATION_NAME, "Leo4"),
            x509.NameAttribute(x509.NameOID.ORGANIZATIONAL_UNIT_NAME, device_part),
            x509.NameAttribute(x509.NameOID.COUNTRY_NAME, "RU"),
        ]
    )

    alt_names = [
        x509.DNSName(f"Leo4-{device_part}.ru"),
        x509.RFC822Name(f"{device_part}@leo4.ru"),
    ]

    builder = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(subject)
        .add_extension(x509.SubjectAlternativeName(alt_names), critical=False)
    )

    csr = builder.sign(private_key, hashes.SHA256(), default_backend())
    csr_pem = csr.public_bytes(serialization.Encoding.PEM).decode("utf-8")

    return private_key_pem.strip(), csr_pem.strip()


async def fetch_signed_certificate(csr_pem: str) -> dict:
    encoded_csr = urllib.parse.quote(csr_pem)
    headers = {
        "X-SSL-Client-CSR": encoded_csr,
        "X-SSL-Client-Exp-Days": "365",
    }

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            str(settings.leo4.cert_url), headers=headers, timeout=10.0
        )

    if resp.status_code != 200:
        return {
            "error": "Failed to get certificate from CA",
            "details": resp.text,
            "status_code": resp.status_code,
        }

    cert_response = resp.json()

    if "cert" in cert_response:
        cert_response["cert"] = urllib.parse.unquote(cert_response["cert"])

    try:
        not_valid_before_str = cert_response.get("not_valid_before")
        valid_days = cert_response.get("valid_days", 0)
        if not_valid_before_str and isinstance(valid_days, int):
            not_valid_before = datetime.strptime(
                not_valid_before_str, "%Y-%m-%d %H:%M:%S"
            )
            expiration_date = not_valid_before + timedelta(days=valid_days)
            today = datetime.now()
            days_left = (expiration_date - today).days
            cert_response["days_left"] = days_left
    except Exception as e:
        log.warning("Failed to calculate days_left: %s", e)
        cert_response["days_left"] = None

    return cert_response


async def process_legacy_certificate(escaped_cert: str, session: AsyncSession) -> Dict:
    if not escaped_cert:
        return {"error": "No client certificate provided"}

    try:
        pem_cert = urllib.parse.unquote(escaped_cert)
        cert_info = parse_cert(pem_cert)
        if "error" in cert_info:
            return cert_info

        ou_value = cert_info.get("ou")
        device_number = 0
        if ou_value and isinstance(ou_value, str):
            digits = "".join(filter(str.isdigit, ou_value))
            device_number = int(digits) if digits else 0

        if not device_number:
            return {"error": "Could not extract device_number from certificate OU"}

        # Проверяем, существует ли устройство
        existing_sn = await DeviceRepo.get_device_sn(session, device_id=device_number)

        if existing_sn:
            device_sn = existing_sn
            log.info(f"Using existing SN for device_id={device_number}: {device_sn}")

            # Полная обработка: генерация ключа, CSR, получение сертификата
            private_key_pem, csr_pem = generate_key_and_csr(device_sn)
            cert_data = await fetch_signed_certificate(csr_pem)
            if "error" in cert_data:
                return cert_data

            cert_info.update(
                {
                    "device_sn": device_sn,
                    "private_key": private_key_pem,
                    "csr": csr_pem,
                    "cert_data": cert_data,
                }
            )
            return cert_info

        else:
            # Устройство не существует — регистрируем новое
            device_sn = generate_device_sn(device_number)
            log.info(f"Registering new device_id={device_number} with SN: {device_sn}")

            await DeviceRepo.add_devices(
                session,
                [
                    {
                        "device_id": device_number,
                        "serial_number": device_sn,
                        "org_id": 0,
                    }
                ],
            )

            # Возвращаем упрощённый ответ без ключей и CSR
            return {
                "status": "device_registered",
                "device_id": device_number,
                "device_sn": device_sn,
                "message": "Device registered. Certificate issuance pending on next request.",
                "code": 206,
            }

    except Exception as e:
        log.error("Unexpected error in legacy service: %s", e)
        return {"error": "Internal server error", "details": str(e)}

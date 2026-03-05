import logging
import urllib.parse
from datetime import datetime, UTC
from typing import Annotated

from cryptography import x509
from cryptography.hazmat.backends import default_backend
from fastapi import APIRouter, Query, Request, Response

from core import settings

log = logging.getLogger(__name__)

legacy_router = APIRouter(
    prefix=settings.api.v1.devices,
    tags=["Legacy"],
    include_in_schema=False,
)


def parse_cert(pem_data: str) -> dict:
    """
    Парсит PEM-сертификат и возвращает словарь с данными.
    """
    try:
        cert = x509.load_pem_x509_certificate(pem_data.encode(), default_backend())
        subject = cert.subject
        issuer = cert.issuer
        not_valid_before = cert.not_valid_before
        not_valid_after = cert.not_valid_after
        serial = cert.serial_number

        def get_attr(oid):
            attrs = subject.get_attributes_for_oid(oid)
            return attrs[0].value if attrs else None

        cn = get_attr(x509.NameOID.COMMON_NAME)
        ou = get_attr(x509.NameOID.ORGANIZATIONAL_UNIT_NAME)
        o = get_attr(x509.NameOID.ORGANIZATION_NAME)
        # email = get_attr(x509.EmailAddressOID.EMAIL_ADDRESS)

        return {
            "subject": str(subject),
            "issuer": str(issuer),
            "cn": cn,
            "ou": ou,
            "o": o,
            # "email": email,
            "serial": serial,
            "not_valid_before": not_valid_before.isoformat(),
            "not_valid_after": not_valid_after.isoformat(),
            "expired": datetime.now(UTC) > not_valid_after,
            "pem": pem_data.strip(),
        }
    except Exception as e:
        log.error("Failed to parse certificate: %s", e)
        return {"error": "Invalid or malformed certificate", "details": str(e)}


@legacy_router.get("/map_legacy_crt/")
async def map_cert(request: Request):
    """
    Принимает X-SSL-Client-Cert, декодирует и возвращает информацию о сертификате.
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
        return Response(content=str(cert_info), media_type="text/plain")
    except Exception as e:
        log.error("Error processing certificate: %s", e)
        return Response(
            content=f"Error: {str(e)}", status_code=500, media_type="text/plain"
        )


@legacy_router.get("/certificates/")
async def legacy(
    function: Annotated[str, Query],
    pin: Annotated[str, Query],
    tosign: Annotated[str, Query],
    request: Request,
):
    # log.info("get certificates path = %s", path)
    log.info("get certificates req %s, %s", request.url, request.query_params)
    return Response(
        content="""<?xml version = \"1.0\" encoding = \"windows-1251\"?>
<Response>
    <Result>OK</Result>
    <code>0</code>
    <CERTDATA>
        <catype>SubCA</catype>
        <prov>Microsoft Enhanced Cryptographic Provider v1.0</prov>
        <dn>CN=34360826,O=509,OU=1003002,S=msk,C=ru,L=2913,E=1.terminal@forpay.ru</dn>
        <pin>J31AG2</pin>
        <sign>04C518FFE1B924CEB2F6A0BF2C73939D</sign>
    </CERTDATA>
</Response>
    """,
        media_type="application/xml",
    )


@legacy_router.post("/certificates/")
async def legacy1(
    function: Annotated[str, Query],
    pin: Annotated[str, Query],
    cpserial: Annotated[str, Query],
    request: Request,
):
    body = await request.body()

    log.info("post certificates %s", body)
    log.info("post certificates header %s", request.headers)
    return Response(
        media_type="application/xml",
        content="""<?xml version = \"1.0\" encoding = \"windows-1251\"?><Response><Result>OK</Result><code>0</code><CERTDATA>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
ntMthogBXjOtAXyT85oPUAKDdDEA
</CERTDATA></Response>""",
    )

from pydantic import BaseModel, Field, field_validator
import re


class LegacyCertRequest(BaseModel):
    client_cert: str = Field(
        ..., description="URL-escaped PEM certificate from X-SSL-Client-Cert header"
    )

    @field_validator("client_cert")
    @classmethod
    def validate_client_cert(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("X-SSL-Client-Cert header is required and cannot be empty")

        v = v.strip()

        if len(v) < 50:
            raise ValueError("Client certificate appears to be too short or invalid")

        # Проверка на наличие URL-encoded или частично закодированного PEM-формата
        pem_pattern = r"-----BEGIN(?:\+|(%20)|\s)+CERTIFICATE(?:\+|(%20)|\s)+-----.*?-----END(?:\+|(%20)|\s)+CERTIFICATE(?:\+|(%20)|\s)+-----"
        if not re.search(pem_pattern, v, re.DOTALL | re.IGNORECASE):
            raise ValueError(
                "Client certificate must be a valid URL-encoded PEM certificate "
                "and contain '-----BEGIN CERTIFICATE-----' and '-----END CERTIFICATE-----' (can be URL-encoded)"
            )

        return v

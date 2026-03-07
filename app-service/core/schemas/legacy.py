from pydantic import BaseModel, Field, field_validator
from urllib.parse import unquote


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

        # Декодируем URL-escaped строку
        try:
            decoded = unquote(v)
        except Exception as e:
            raise ValueError(f"Invalid URL encoding in certificate: {e}")

        # Проверяем PEM-маркеры
        if "-----BEGIN CERTIFICATE-----" not in decoded:
            raise ValueError(
                "Client certificate must contain '-----BEGIN CERTIFICATE-----'"
            )
        if "-----END CERTIFICATE-----" not in decoded:
            raise ValueError(
                "Client certificate must contain '-----END CERTIFICATE-----'"
            )

        return v

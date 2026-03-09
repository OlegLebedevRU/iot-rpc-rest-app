from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509 import load_pem_x509_certificate


def create_pfx(
    private_key_pem: str, cert_pem: str, ca_pem: str, password: str
) -> bytes:
    """
    Создаёт PKCS#12 (.pfx) файл с цепочкой доверия.
    """
    private_key = serialization.load_pem_private_key(
        private_key_pem.encode(), password=None
    )
    cert = load_pem_x509_certificate(cert_pem.encode())
    ca_cert = load_pem_x509_certificate(ca_pem.encode())

    pfx = pkcs12.serialize_key_and_certificates(
        name=b"device-cert",
        key=private_key,
        cert=cert,
        cas=[ca_cert],
        encryption_algorithm=serialization.BestAvailableEncryption(password.encode()),
    )
    return pfx

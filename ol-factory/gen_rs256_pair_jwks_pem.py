from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwk, constants
import json

key = rsa.generate_private_key(
    public_exponent=65537,
    key_size=2048,
    backend=default_backend()
)
public_key = key.public_key().public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo
)
private_key = key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.TraditionalOpenSSL,
    encryption_algorithm=serialization.NoEncryption()
)
private_key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    )
#public_pem = key.public_key().public_bytes(serialization.Encoding.PEM)

print(json.dumps(jwk.RSAKey(algorithm=constants.Algorithms.RS256, key=public_key.decode('utf-8')).to_dict()))
print(json.dumps(jwk.RSAKey(algorithm=constants.Algorithms.RS256, key=private_key.decode('utf-8')).to_dict()))
print(private_key_pem)
print(public_key)
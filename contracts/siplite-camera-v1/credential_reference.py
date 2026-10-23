"""Portable credential-envelope oracle, not a deployed vault or device key API.

Only ciphertext is a cloud RPC input. Local authenticated RPC may use plaintext.
Keys and plaintext produced by this reference must never be written to evidence.
"""
from __future__ import annotations

import base64
import json
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ALGORITHM = "RSA-OAEP-256+A256GCM"
LABEL = b"siplite-camera-credentials/v1"
HEADER = ("v", "alg", "sn", "operation_id", "recipient_cert_sha256", "expires_at_ms", "wrapped_key")


def encode(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def decode(value: str) -> bytes:
    return base64.b64decode(value, validate=True)


def aad(envelope: dict) -> bytes:
    return json.dumps({key: envelope[key] for key in HEADER}, sort_keys=True,
                      separators=(",", ":"), ensure_ascii=True).encode("ascii")


def validate_plaintext(value: dict) -> None:
    if set(value) != {"username", "password"}:
        raise ValueError("invalid_credential_fields")
    for key, limit in (("username", 64), ("password", 128)):
        text = value[key]
        if not isinstance(text, str) or not 0 < len(text.encode("utf-8")) <= limit:
            raise ValueError("invalid_credential_length")
        if any(ord(char) < 32 or ord(char) == 127 for char in text) or key == "username" and ":" in text:
            raise ValueError("invalid_credential_characters")


def seal(public_key, plaintext: dict, metadata: dict, now_ms: int) -> dict:
    validate_plaintext(plaintext)
    if public_key.key_size not in (2048, 3072, 4096):
        raise ValueError("unsupported_recipient_key")
    if not now_ms < metadata["expires_at_ms"] <= now_ms + 60000:
        raise ValueError("invalid_credential_deadline")
    content_key = os.urandom(32)
    result = dict(metadata, v=1, alg=ALGORITHM)
    result["wrapped_key"] = encode(public_key.encrypt(content_key, padding.OAEP(
        mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=LABEL)))
    nonce = os.urandom(12)
    raw = json.dumps(plaintext, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    encrypted = AESGCM(content_key).encrypt(nonce, raw, aad(result))
    return dict(result, nonce=encode(nonce), ciphertext=encode(encrypted[:-16]), tag=encode(encrypted[-16:]))


def unseal(private_key, envelope: dict, *, sn: str, operation_id: str,
           recipient_cert_sha256: str, now_ms: int) -> dict:
    if (envelope["v"] != 1 or envelope["alg"] != ALGORITHM
            or envelope["sn"] != sn or envelope["operation_id"] != operation_id
            or envelope["recipient_cert_sha256"] != recipient_cert_sha256
            or not now_ms < envelope["expires_at_ms"] <= now_ms + 60000):
        raise ValueError("credential_binding_or_deadline")
    nonce, tag = decode(envelope["nonce"]), decode(envelope["tag"])
    if len(nonce) != 12 or len(tag) != 16:
        raise ValueError("invalid_credential_encoding")
    content_key = private_key.decrypt(decode(envelope["wrapped_key"]), padding.OAEP(
        mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=LABEL))
    plaintext = AESGCM(content_key).decrypt(nonce, decode(envelope["ciphertext"]) + tag, aad(envelope))
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_credential_field")
            result[key] = value
        return result
    value = json.loads(plaintext, object_pairs_hook=unique)
    validate_plaintext(value)
    return value

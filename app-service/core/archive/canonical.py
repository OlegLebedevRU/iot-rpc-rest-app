from __future__ import annotations

import gzip
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable

import jsonschema

# Load canonical manifest schema
SCHEMA_DIR = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "l4desk-service"
    / "docs"
    / "prompts"
    / "contracts"
    / "archive-manifest-v1"
)
SCHEMA_PATH = SCHEMA_DIR / "archive-manifest.schema.json"

_MANIFEST_SCHEMA: dict[str, Any] | None = None

SENSITIVE_KEY_PATTERNS = (
    "password",
    "secret",
    "token",
    "key",
    "auth",
    "credential",
    "private",
    "pin",
    "jwt",
)


def get_manifest_schema() -> dict[str, Any]:
    global _MANIFEST_SCHEMA
    if _MANIFEST_SCHEMA is None:
        if not SCHEMA_PATH.is_file():
            raise FileNotFoundError(
                f"Archive manifest schema file not found at: {SCHEMA_PATH}"
            )
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            _MANIFEST_SCHEMA = json.load(f)
    return _MANIFEST_SCHEMA


def scrub_secrets(value: Any) -> Any:
    """Recursively scrub sensitive keys and credentials from archive payloads."""
    if isinstance(value, dict):
        scrubbed = {}
        for k, v in value.items():
            k_lower = str(k).lower()
            if any(pat in k_lower for pat in SENSITIVE_KEY_PATTERNS):
                scrubbed[k] = "[SCRUBBED]"
            else:
                scrubbed[k] = scrub_secrets(v)
        return scrubbed
    if isinstance(value, list):
        return [scrub_secrets(item) for item in value]
    return value


def serialize_record_envelope(record: dict[str, Any]) -> str:
    """Serialize record envelope deterministically: sorted keys, compact separators, UTF-8 LF."""
    clean_payload = scrub_secrets(record.get("payload", {}))
    normalized_record = {
        "record_type": record["record_type"],
        "record_id": str(record["record_id"]),
        "occurred_at_utc": record["occurred_at_utc"],
        "cursor": record.get("cursor"),
        "tenant_id": record.get("tenant_id"),
        "terminal_id": record.get("terminal_id"),
        "sn": record.get("sn"),
        "session_id": record.get("session_id"),
        "source_project": record.get("source_project", "iot-rpc-rest-app"),
        "payload": clean_payload,
    }
    dumped = json.dumps(
        normalized_record,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return dumped + "\n"


def compute_file_sha256(file_path: Path, chunk_size: int = 65536) -> str:
    """Compute SHA-256 hash of a file streaming in chunks."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(chunk_size):
            hasher.update(chunk)
    return hasher.hexdigest()


def write_deterministic_jsonl_gz(
    records: Iterable[dict[str, Any]],
    output_file_path: Path,
) -> tuple[int, int, str]:
    """Write records to a gzip-compressed JSONL file with deterministic headers (mtime=0.0).

    Returns:
        (record_count, total_bytes_written, file_sha256)
    """
    record_count = 0
    output_file_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file_path, "wb") as raw_f:
        # mtime=0.0 and filename="" guarantee byte-for-byte reproducibility
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw_f, mtime=0.0) as gz_f:
            for rec in records:
                line = serialize_record_envelope(rec)
                gz_f.write(line.encode("utf-8"))
                record_count += 1
            gz_f.flush()
        raw_f.flush()
        os.fsync(raw_f.fileno())

    file_size = output_file_path.stat().st_size
    file_sha256 = compute_file_sha256(output_file_path)
    return record_count, file_size, file_sha256


def format_checksum_content(sha256_hex: str, filename: str = "data.jsonl.gz") -> str:
    """Standard sha256sum format: hash followed by two spaces and filename."""
    return f"{sha256_hex}  {filename}\n"


def write_manifest_file(
    manifest_data: dict[str, Any], manifest_file_path: Path
) -> None:
    """Validate and write canonical manifest.json."""
    validate_manifest_data(manifest_data)
    manifest_json = (
        json.dumps(
            manifest_data,
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )
    with open(manifest_file_path, "w", encoding="utf-8") as f:
        f.write(manifest_json)
        f.flush()
        os.fsync(f.fileno())


def validate_manifest_data(manifest_data: dict[str, Any]) -> None:
    """Validate manifest data against canonical JSON Schema."""
    schema = get_manifest_schema()
    validator_cls = jsonschema.validators.validator_for(schema)
    validator = validator_cls(schema)
    errors = sorted(validator.iter_errors(manifest_data), key=lambda e: e.path)
    if errors:
        first = errors[0]
        path_str = ".".join(str(p) for p in first.path) or "root"
        raise jsonschema.ValidationError(
            f"Manifest schema validation error at '{path_str}': {first.message}"
        )

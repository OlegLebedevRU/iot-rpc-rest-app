"""Offline packet consistency and semantic vectors, without application setup."""

import hashlib
import json
import runpy
from pathlib import Path
from uuid import UUID

from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

packet = Path(__file__).resolve().parent
root = packet.parents[1]
module = runpy.run_path(str(root / "app-service/core/camera/quality_contract.py"))
raw = (packet / "schema.json").read_bytes()
manifest = json.loads((packet / "manifest.json").read_text(encoding="utf-8"))
if hashlib.sha256(raw).hexdigest() != manifest["schema_sha256"]:
    raise ValueError("candidate_schema_pin_mismatch")
media = (root / "contracts/l4-media-v3/media.schema.json").read_bytes()
if hashlib.sha256(media).hexdigest() != manifest["media_schema_sha256"]:
    raise ValueError("common_media_schema_pin_mismatch")
schema = json.loads(raw)
if schema != module["protocol_schema"]():
    raise ValueError("candidate_schema_model_drift")
Draft202012Validator.check_schema(schema)
validator = Draft202012Validator(schema, format_checker=FormatChecker())
uid = UUID("00000000-0000-4000-8000-000000000001")
for target in (
    {"target_bitrate_kbps": 8000},
    {"target_bitrate_kbps": 99},
    {"target_bitrate_kbps": 0, "target_fps": 0, "size": ""},
    {"size": "2048x1536"},
    {"preset_id": "5MP", "target_bitrate_kbps": 6000},
    {"target_fps": 29.97},
    {"rate_control": "avbr", "gop_seconds": 1.5},
):
    request = module["QualityRequest"](
        quality_revision=module["REVISION"],
        stream_instance_id=uid,
        writer_key=uid,
        target=target,
    )
    validator.validate(request.model_dump(mode="json", exclude_none=True))
for target in ({}, {"target_bitrate_kbps": True}, {"size": "0x1080"}):
    try:
        module["QualityTarget"](**target)
    except ValidationError:
        pass
    else:
        raise AssertionError("negative_vector_accepted")
deadline = module["command_deadline"](1000, 200, 5000)
if deadline != 1200 or deadline - 1150 != 50:
    raise AssertionError("delayed_delivery_budget_restarted")
print(
    "candidate schema/model pins and 11 offline vectors passed; runtime not exercised"
)

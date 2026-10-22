"""Export the internal video API without starting broker/DB connections."""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    # Synthetic documentation-only defaults; never read or export private .env.
    for key, value in {
        "FASTSTREAM__URL": "amqp://docs:docs@localhost:5672//",
        "DB__URL": "postgresql+asyncpg://docs:docs@localhost/docs",
        "AUTH__API_KEYS": "docs:1",
        "LEO4__URL": "http://localhost",
        "LEO4__API_KEY": "docs",
        "LEO4__ADMIN_URL": "http://localhost",
    }.items():
        os.environ.setdefault(f"APP_CONFIG__{key}", value)
    sys.path.insert(0, str(root / "app-service"))
    from api.internal_v1.remote_input import router
    from core.remote_input.video_wire import SCHEMA
    from fastapi.openapi.utils import get_openapi

    suffixes = (
        "/stream/start",
        "/stream/stop",
        "/video-capabilities",
        "/video-state",
        "/video-stop",
    )
    routes = [
        copy.copy(route) for route in router.routes if route.path.endswith(suffixes)
    ]
    for route in routes:
        route.include_in_schema = True
    document = get_openapi(
        title="Internal IoT video control",
        version="hevc-contract/2.0.0",
        openapi_version="3.1.0",
        routes=routes,
    )
    components = document["components"]["schemas"]
    # Pydantic cannot express every frozen allOf condition in its generated schema.
    # Publish the normative schema for wire requests, including these conditions.
    definitions = json.loads(
        json.dumps(SCHEMA["$defs"]).replace("#/$defs/", "#/components/schemas/G0_")
    )
    components.update({f"G0_{name}": schema for name, schema in definitions.items()})
    for name, definition in (("Start", "start"), ("Stop", "stop")):
        components[name] = definitions[definition]
    document["info"]["description"] = (
        "Service authentication and trusted X-Org-Id/X-User-Id/X-Session-Id headers are required. "
        "V2 starts require video_v2_enabled; HEVC also requires video_hevc_chain_ready. "
        "Legacy requests and responses retain their original shapes. Agent-ready does not prove decoded frames."
    )
    target = root / "docs/l4desk/contracts/video-control-v2.openapi.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    if args.check:
        if target.read_text(encoding="utf-8") != content:
            raise SystemExit("Internal video OpenAPI snapshot differs; regenerate it")
    else:
        target.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()

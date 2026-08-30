from __future__ import annotations

import json
from pathlib import Path
import re
import pytest


def _get_project_root() -> Path:
    # app-service/tests/core/test_rmq_infra_config.py -> project root
    p = Path(__file__).resolve().parent.parent.parent.parent
    if (p / "rmq").is_dir() and (p / "compose.yaml").is_file():
        return p
    # Fallback if running inside docker container or non-standard working dir
    for candidate in [Path("/app/.."), Path("/home/user1/iot-rpc-rest-app")]:
        if (candidate / "rmq").is_dir() and (candidate / "compose.yaml").is_file():
            return candidate.resolve()
    return p


def test_definitions_json_etran_service():
    """Verify definitions.json contains valid etran_service user and permissions."""
    root = _get_project_root()
    defs_path = root / "rmq" / "definitions.json"
    if not defs_path.is_file():
        pytest.skip(f"definitions.json not found at {defs_path} (isolated container run)")

    data = json.loads(defs_path.read_text(encoding="utf-8"))

    # 1. User check
    users = {u["name"]: u for u in data.get("users", [])}
    assert "etran_service" in users, "etran_service user missing in definitions.json"
    etran_user = users["etran_service"]
    assert etran_user["hashing_algorithm"] == "rabbit_password_hashing_sha256"
    assert "password_hash" in etran_user
    assert etran_user["password_hash"], "password_hash should not be empty"

    # 2. Permissions check
    permissions = [p for p in data.get("permissions", []) if p.get("user") == "etran_service"]
    assert len(permissions) == 1, "etran_service permissions missing or duplicated"
    perm = permissions[0]
    assert perm.get("vhost") == "/"
    assert perm.get("configure") == ""
    assert perm.get("write") == "^(amq\\.topic|telemetry\\..*)"
    assert perm.get("read") == "^(amq\\.topic|telemetry\\..*)"

    # 3. Topic Permissions check
    topic_perms = [
        tp for tp in data.get("topic_permissions", [])
        if tp.get("user") == "etran_service" and tp.get("exchange") == "amq.topic"
    ]
    assert len(topic_perms) == 1, "etran_service topic_permissions on amq.topic missing"
    tp = topic_perms[0]
    assert tp.get("vhost") == "/"
    assert tp.get("write") == r"^dev\..*\.gauge\..*"
    assert tp.get("read") == r"^dev\..*\.gauge\..*"


def test_rabbitmq_conf_listeners_and_mqtt():
    """Verify rmq/rabbitmq.conf has correct listeners and MQTT configuration."""
    root = _get_project_root()
    conf_path = root / "rmq" / "rabbitmq.conf"
    if not conf_path.is_file():
        pytest.skip(f"rabbitmq.conf not found at {conf_path} (isolated container run)")

    content = conf_path.read_text(encoding="utf-8")

    # Check that listeners are configured without comments
    assert re.search(r"^\s*listeners\.tcp\.default\s*=\s*5672", content, re.MULTILINE), "AMQP 5672 listener missing"
    assert re.search(r"^\s*mqtt\.listeners\.ssl\.default\s*=\s*8883", content, re.MULTILINE), "MQTT SSL 8883 listener missing"
    assert re.search(r"^\s*mqtt\.listeners\.tcp\.default\s*=\s*1883", content, re.MULTILINE), "Plain MQTT 1883 listener missing"

    # Check MQTT options
    assert re.search(r"^\s*mqtt\.allow_anonymous\s*=\s*false", content, re.MULTILINE), "mqtt.allow_anonymous=false missing"
    assert re.search(r"^\s*mqtt\.vhost\s*=\s*/", content, re.MULTILINE), "mqtt.vhost=/ missing"
    assert re.search(r"^\s*mqtt\.exchange\s*=\s*amq\.topic", content, re.MULTILINE), "mqtt.exchange=amq.topic missing"
    assert re.search(r"^\s*mqtt\.max_session_expiry_interval_seconds\s*=\s*86400", content, re.MULTILINE), "mqtt.max_session_expiry_interval_seconds=86400 missing"


def test_compose_yaml_rabbitmq_network():
    """Verify compose.yaml specifies shared iot_rabbitmq_network and does not expose 1883 on host."""
    root = _get_project_root()
    compose_path = root / "compose.yaml"
    if not compose_path.is_file():
        pytest.skip(f"compose.yaml not found at {compose_path} (isolated container run)")

    content = compose_path.read_text(encoding="utf-8")

    # Check rabbitmq_network name: iot_rabbitmq_network
    network_block_match = re.search(r"rabbitmq_network:\s*\n\s*name:\s*iot_rabbitmq_network\s*\n\s*driver:\s*bridge", content)
    assert network_block_match, "rabbitmq_network with name 'iot_rabbitmq_network' and driver 'bridge' not found in compose.yaml"

    # Check ports for rabbitmq service: 1883 should NOT be in ports section
    assert not re.search(r'["\']?1883:1883["\']?', content), "Port 1883 must not be exposed to host in compose.yaml"

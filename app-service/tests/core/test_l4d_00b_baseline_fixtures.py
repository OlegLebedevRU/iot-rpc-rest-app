from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path
from uuid import UUID

import pytest

from core.diagnostics.commands import (
    CMD_DIAG_CANCEL,
    CMD_DIAG_EXEC,
    CMD_DIAG_STREAM_CONTROL,
)
from core.diagnostics.schemas import (
    CancelDiagnosticMessage,
    DeviceOutputEnvelope,
    DiagCancelPayload,
    DiagExecPayload,
    OutputKind,
)
from core.remote_input.schemas import (
    InventoryGetCommand,
    KeyEventCommand,
    MouseClickCommand,
    ShortcutActionCommand,
    StreamStartCommand,
    StreamStopCommand,
)

FIXTURES_DIR = Path(
    r"D:\repo\platerra\Public\etranprocessing\tools\docs\l4desk\fixtures"
)

EXPECTED_DIGESTS = {
    "rpc_7001_exec.json": "4007bbf50a5280abfaf747f7c8a28344a4f61e2ac4f2a60a0c80aec5018578bf",
    "rpc_7000_stream_control.json": "dba8ff769f12239765c2317b96a8fa2e8f60cdccbc0de00113b9d4ce7e54b9b8",
    "baseline_capabilities.json": "375412eaa61e31e72b2ea5f002862a1d1f02becdd4626a71af31d9400df560cb",
    "rpc_7002_cancel.json": "2965f6e24d8c88b82b08b6dec892c271750a91f1a89f82cc8eb1b19fa8779d22",
    "mqtt_presence_lifecycle.json": "f6a59507fc9cbed6c2f4bf707360affedb6344cac01b7f49b12d8cf3cff08e28",
    "l4rtp_wire_protocol.json": "eb8500895d8f679cd0baa59e150c8b94e8a78d8eca5b7c9f086654c066c35277",
}


def _load_fixture(filename: str) -> dict:
    filepath = FIXTURES_DIR / filename
    if not filepath.exists():
        pytest.skip(f"Fixture file {filepath} not found on this host")
    return json.loads(filepath.read_text(encoding="utf-8"))


# ── Contract Gate: SHA-256 Digest Verification ──────────────────────────────


@pytest.mark.parametrize("filename,expected_sha256", EXPECTED_DIGESTS.items())
def test_contract_gate_fixture_digests(filename: str, expected_sha256: str):
    """Verify that all input agent fixtures match the immutable contract digest."""
    filepath = FIXTURES_DIR / filename
    if not filepath.exists():
        pytest.skip(f"Fixture file {filepath} not found on this host")
    digest = hashlib.sha256(filepath.read_bytes()).hexdigest().lower()
    assert (
        digest == expected_sha256
    ), f"Digest mismatch for {filename}: expected {expected_sha256}, got {digest}"


# ── Fixture 1: rpc_7001_exec.json ──────────────────────────────────────────


def test_rpc_7001_exec_fixture_compatibility():
    """Verify structure and compatibility of rpc_7001_exec golden fixture with provider models."""
    data = _load_fixture("rpc_7001_exec.json")
    assert data["method_code"] == 7001
    assert data["method_code"] == CMD_DIAG_EXEC

    examples = data["examples"]
    assert "exec_cmd_hostname" in examples
    ex = examples["exec_cmd_hostname"]

    req_payload = ex["request"]["payload"]
    assert req_payload["method_code"] == 7001
    assert req_payload["command_line"] == "hostname"
    assert req_payload["shell"] == "cmd"
    assert req_payload["ttl_sec"] == 30

    # Note variance: fixture uses arbitrary string session_id ("sess-exec-9001"),
    # whereas provider DiagExecPayload enforces RFC-4122 UUID.
    # When converted/mapped to UUID, DiagExecPayload validates successfully:
    mapped_session_id = UUID("018f3a5b-0001-7001-8000-000000000001")
    task_item = DiagExecPayload(
        session_id=mapped_session_id,
        command_id=req_payload["id"],
        command_line=req_payload["command_line"],
        shell=req_payload["shell"],
        ttl_sec=req_payload["ttl_sec"],
        topic=req_payload["topic"],
    )
    assert task_item.session_id == mapped_session_id
    assert task_item.command_line == "hostname"

    # Streaming chunks variance:
    # Fixture chunks contain session_id (str), seq, data, eof.
    # Provider DeviceOutputEnvelope requires UUID session_id, kind (OutputKind), and stream (str).
    chunk_payload = ex["stream_output_chunk"]["payload"]
    envelope = DeviceOutputEnvelope(
        session_id=mapped_session_id,
        seq=chunk_payload["seq"],
        stream="stdout",
        kind=OutputKind.STDOUT,
        data=chunk_payload["data"],
        eof=chunk_payload["eof"],
    )
    assert envelope.seq == 1
    assert envelope.data == "TERM-KIOSK-01\r\n"
    assert envelope.eof is False

    eof_payload = ex["stream_output_eof"]["payload"]
    final_envelope = DeviceOutputEnvelope(
        session_id=mapped_session_id,
        seq=eof_payload["seq"],
        stream="stdout",
        kind=OutputKind.RESULT,
        data=eof_payload["data"],
        eof=eof_payload["eof"],
        exit_code=eof_payload["exit_code"],
    )
    assert final_envelope.eof is True
    assert final_envelope.exit_code == 0


# ── Fixture 2: rpc_7000_stream_control.json ────────────────────────────────


def test_rpc_7000_stream_control_fixture_compatibility():
    """Verify compatibility of rpc_7000_stream_control actions with provider schemas."""
    data = _load_fixture("rpc_7000_stream_control.json")
    assert data["method_code"] == 7000
    assert data["method_code"] == CMD_DIAG_STREAM_CONTROL

    examples = data["examples"]

    # 1. inventory_get
    # Note variance: fixture uses string command_id ("inv_001"), while provider
    # schemas require UUID, sn, issued_at_ms, and expires_at_ms on server commands.
    inv = examples["inventory_get"]["request"]["payload"]
    assert inv["action"] == "inventory_get"
    inv_cmd = InventoryGetCommand(
        command_id=UUID("018f3a5b-0001-7000-8000-000000000001"),
        sn=inv["sn"],
        issued_at_ms=1726000000000,
        expires_at_ms=1726000005000,
    )
    assert inv_cmd.type == "inventory_get"
    assert inv_cmd.sn == "000100773"

    # 2. stream_start
    start = examples["stream_start_desktop"]["request"]["payload"]
    assert start["action"] == "stream_start"
    start_cmd = StreamStartCommand(
        command_id=UUID("018f3a5b-0001-7000-8000-000000000002"),
        sn=start["sn"],
        lease_id=UUID("018f3a5b-0001-7000-8000-000000000088"),
        stream_instance_id=UUID("018f3a5b-0001-7000-8000-000000000099"),
        mode=start["stream_mode"],
        source_id=str(start["display_index"]),
        issued_at_ms=1726000000000,
        expires_at_ms=1726000015000,
    )
    assert start_cmd.type == "stream_start"
    assert start_cmd.mode == "desktop"

    # 3. stream_stop
    stop = examples["stream_stop"]["request"]["payload"]
    assert stop["action"] == "stream_stop"
    stop_cmd = StreamStopCommand(
        command_id=UUID("018f3a5b-0001-7000-8000-000000000003"),
        sn=stop["sn"],
        lease_id=UUID("018f3a5b-0001-7000-8000-000000000088"),
        stream_instance_id=UUID("018f3a5b-0001-7000-8000-000000000099"),
        issued_at_ms=1726000000000,
        expires_at_ms=1726000005000,
    )
    assert stop_cmd.type == "stream_stop"

    # 4. mouse_click
    clk = examples["mouse_click"]["request"]["payload"]
    assert clk["action"] == "mouse_click"
    # Note coordinate mapping: normalized float 0..1 in fixture -> int 0..65535 in provider
    x_int = int(clk["x_norm"] * 65535)
    y_int = int(clk["y_norm"] * 65535)
    clk_cmd = MouseClickCommand(
        command_id=UUID("018f3a5b-0001-7000-8000-000000000004"),
        sn=clk["sn"],
        lease_id=UUID("018f3a5b-0001-7000-8000-000000000088"),
        stream_instance_id=UUID("018f3a5b-0001-7000-8000-000000000099"),
        button=clk["button"],
        x=x_int,
        y=y_int,
        issued_at_ms=1726000000000,
        expires_at_ms=1726000005000,
    )
    assert clk_cmd.button == "left"
    assert clk_cmd.x == x_int
    assert clk_cmd.y == y_int

    # 5. key_event
    key = examples["key_event"]["request"]["payload"]
    assert key["action"] == "key_event"
    key_cmd = KeyEventCommand(
        command_id=UUID("018f3a5b-0001-7000-8000-000000000005"),
        sn=key["sn"],
        lease_id=UUID("018f3a5b-0001-7000-8000-000000000088"),
        stream_instance_id=UUID("018f3a5b-0001-7000-8000-000000000099"),
        kind="down" if key["is_down"] else "up",
        vk=key["vk"],
        issued_at_ms=1726000000000,
        expires_at_ms=1726000005000,
    )
    assert key_cmd.vk == 65

    # 6. shortcut_action
    sc = examples["shortcut_action"]["request"]["payload"]
    assert sc["action"] == "shortcut_action"
    sc_cmd = ShortcutActionCommand(
        command_id=UUID("018f3a5b-0001-7000-8000-000000000006"),
        sn=sc["sn"],
        lease_id=UUID("018f3a5b-0001-7000-8000-000000000088"),
        stream_instance_id=UUID("018f3a5b-0001-7000-8000-000000000099"),
        action=sc["shortcut"],
        issued_at_ms=1726000000000,
        expires_at_ms=1726000005000,
    )
    assert sc_cmd.action == "win_d"


# ── Fixture 3: baseline_capabilities.json ─────────────────────────────────


def test_baseline_capabilities_fixture_validation():
    """Verify baseline capabilities artifact metadata and method support."""
    data = _load_fixture("baseline_capabilities.json")
    artifact = data["artifact"]
    assert artifact["version"] == "1.7.7"
    assert artifact["deployment_status"] == "PUBLISHED"

    methods = data["methods"]
    assert "7000" in methods
    assert "7001" in methods
    assert "7002" in methods
    assert methods["7000"]["name"] == "CMD_DIAG_STREAM_CONTROL"
    assert methods["7001"]["name"] == "CMD_DIAG_EXEC"
    assert methods["7002"]["name"] == "CMD_DIAG_CANCEL"

    components = data["components"]
    assert components["l4desk"] == "1.7.6"
    assert components["ffmpeg"] == "9.0"


# ── Fixture 4: rpc_7002_cancel.json ───────────────────────────────────────


def test_rpc_7002_cancel_fixture_compatibility():
    """Verify rpc_7002_cancel mapping to provider DiagCancelTaskItem."""
    data = _load_fixture("rpc_7002_cancel.json")
    assert data["method_code"] == 7002
    assert data["method_code"] == CMD_DIAG_CANCEL

    ex = data["examples"]["cancel_running_task"]["request"]["payload"]
    assert ex["method_code"] == 7002

    cancel_msg = CancelDiagnosticMessage(
        type="cancel",
        session_id=UUID("018f3a5b-0001-7001-8000-000000000001"),
        reason="user_cancel",
    )
    assert cancel_msg.type == "cancel"

    cancel_task = DiagCancelPayload(
        session_id=cancel_msg.session_id,
        reason=cancel_msg.reason,
    )
    assert cancel_task.session_id == cancel_msg.session_id


# ── Fixture 5: mqtt_presence_lifecycle.json ───────────────────────────────


def test_mqtt_presence_lifecycle_fixture_compatibility():
    """Verify presence topic semantics for main_app and extra_service."""
    data = _load_fixture("mqtt_presence_lifecycle.json")
    roles = data["roles"]

    # main_app publishes to dev/{SN}/app
    assert roles["main_app"]["topic"] == "dev/{SN}/app"
    assert roles["main_app"]["connect_will"]["payload"] == "app_offline"
    assert roles["main_app"]["connack_publish"]["payload"] == "app_online"
    assert roles["main_app"]["connect_will"]["retain"] is True

    # extra_service publishes to dev/{SN}/svc
    assert roles["extra_service"]["topic"] == "dev/{SN}/svc"
    assert roles["extra_service"]["connect_will"]["payload"] == "svc_offline"
    assert roles["extra_service"]["connack_publish"]["payload"] == "svc_online"
    assert roles["extra_service"]["connect_will"]["retain"] is True


# ── Fixture 6: l4rtp_wire_protocol.json ───────────────────────────────────


def test_l4rtp_wire_protocol_fixture_decoding():
    """Verify binary decoding of L4RTP wire protocol preamble and frame headers."""
    data = _load_fixture("l4rtp_wire_protocol.json")
    preamble = data["preamble"]

    hex_bytes = bytes.fromhex(preamble["hex_wire_bytes"])
    magic = hex_bytes[0:4].decode("ascii")
    version = hex_bytes[4]
    reserved = hex_bytes[5]
    sn_len = struct.unpack(">H", hex_bytes[6:8])[0]
    sn = hex_bytes[8 : 8 + sn_len].decode("ascii")

    assert magic == "L4RT"
    assert version == 1
    assert reserved == 0
    assert sn_len == 9
    assert sn == "000100773"

    # Frame header decoding
    rtp_frame = data["stream_frames"]["example_rtp_frame"]
    rtp_header = bytes.fromhex(rtp_frame["header_hex"])
    channel_id, reserved_frame, payload_len = struct.unpack(">BBH", rtp_header)
    assert channel_id == 1  # 0x01 = RTP
    assert reserved_frame == 0
    assert payload_len == 1400

    rtcp_frame = data["stream_frames"]["example_rtcp_frame"]
    rtcp_header = bytes.fromhex(rtcp_frame["header_hex"])
    rtcp_chan, rtcp_res, rtcp_len = struct.unpack(">BBH", rtcp_header)
    assert rtcp_chan == 2  # 0x02 = RTCP
    assert rtcp_res == 0
    assert rtcp_len == 72

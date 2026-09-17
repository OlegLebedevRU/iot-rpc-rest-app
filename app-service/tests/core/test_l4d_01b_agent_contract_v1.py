from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from core.adapters.agent_contract_v1 import (
    CONTRACT_VERSION,
    METHOD_CANCEL_TASK,
    METHOD_EXEC_COMMAND,
    METHOD_STREAM_CONTROL,
    PUBLISHED_AGENT_RELEASE,
    SCHEMA_REVISION,
    SUPPORTED_AGENT_VERSIONS,
    AgentContractV1Adapter,
    CommercialFieldViolationError,
    ContractValidationError,
    UnknownCapabilityError,
    agent_contract_v1_adapter,
    assert_no_commercial_fields,
    verify_l4rtp_frame_header,
    verify_l4rtp_preamble,
)
from core.diagnostics.mqtt_bridge import decode_output_payload
from core.diagnostics.schemas import (
    DeviceOutputEnvelope,
    DiagCancelPayload,
    DiagExecPayload,
    OutputKind,
)
from core.diagnostics.sessions import DiagnosticSession, DiagnosticsSessionRegistry

# ── Fixtures and Contract Paths ───────────────────────────────────────────────

FIXTURES_PATH = Path(
    r"D:\repo\platerra\Public\etranprocessing\tools\docs\l4desk\fixtures\golden_vectors_v1.json"
)
CONTRACTS_ROOT = Path(r"D:\repo\platerra\Public\etranprocessing")

EXPECTED_DIGESTS = {
    "tools/docs/l4desk/contracts/agent_compatibility_contract_v1.json": "38e4ae5f13d563b3ae57a83259d63f9a63049d528d9667ae33efbd5a1e71267a",
    "tools/docs/l4desk/contracts/schemas/agent_contract_v1.schema.json": "f065dd53101c4bf90b237c85082a05eea212e1a2b3de39d2bf890708e3a42f1d",
    "tools/docs/l4desk/contracts/schemas/presence_event.schema.json": "fd061b7a1a113ec4ba518208e5693ffad98593cd8096d9a013f34a0ca7748d07",
    "tools/docs/l4desk/contracts/schemas/rpc_7000_stream_control.schema.json": "d7ed9deaeddc4a8a5f668cd59ac95aa0941aeff083e4ef6d94a1c9e75ba4ab6e",
    "tools/docs/l4desk/contracts/schemas/rpc_7001_exec.schema.json": "fb511cfb368f809fb042dbece552d7f24aeedb384f7186915f82e1dfb561ee1b",
    "tools/docs/l4desk/contracts/schemas/rpc_7002_cancel.schema.json": "a1dac309f324b1d0e2073ac8ab251ed70f6cfd191c46ae38f3c9192854079a8f",
    "tools/docs/l4desk/contracts/schemas/l4rtp_wire_protocol.schema.json": "b38aeeda96a5df81561117a0acb13606b417f136abb5250e72d41d38b630bd53",
    "tools/docs/l4desk/fixtures/golden_vectors_v1.json": "b4f3c1a465e88babf89c0850cfd8dffc29a4cd921ec51a73e2112e6cf9c3034b",
    "tools/tests/test_agent_compatibility_contract_v1.py": "7e6ce52fc9351cc8a95134bcde0304fc208e0fdbec3287f279b2a7bfd0db0d52",
}


def _load_golden_vectors() -> dict:
    if not FIXTURES_PATH.exists():
        pytest.skip(f"Golden vectors file {FIXTURES_PATH} not found on this host")
    return json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))


# ── 1. Contract Gate: Artifact SHA-256 Digest Verification ────────────────────


@pytest.mark.parametrize("rel_path,expected_sha256", EXPECTED_DIGESTS.items())
def test_contract_gate_artifact_digests(rel_path: str, expected_sha256: str):
    """Verify SHA-256 digests of all 9 artifacts from H-L4D-01A-TOOLS-v1."""
    p = CONTRACTS_ROOT / rel_path
    if not p.exists():
        pytest.skip(f"Artifact {rel_path} not found")
    actual_hash = hashlib.sha256(p.read_bytes()).hexdigest().lower()
    assert (
        actual_hash == expected_sha256
    ), f"Digest mismatch for {rel_path}: expected {expected_sha256}, got {actual_hash}"


def test_contract_metadata_alignment():
    """Verify provider adapter metadata matches Agent Contract v1."""
    assert CONTRACT_VERSION == "1.0.0"
    assert SCHEMA_REVISION == "2026-09-17-v1"
    assert "1.7.6" in SUPPORTED_AGENT_VERSIONS
    assert "1.7.7" in SUPPORTED_AGENT_VERSIONS
    assert PUBLISHED_AGENT_RELEASE == "1.7.7"


# ── 2. Presence Golden Vectors Verification (6 vectors) ───────────────────────


def test_presence_lifecycle_golden_vectors():
    """Verify all 6 presence vectors from golden_vectors_v1.json."""
    data = _load_golden_vectors()
    vectors = data.get("presence_vectors", [])
    assert len(vectors) == 6

    adapter = AgentContractV1Adapter()

    for vec in vectors:
        vec_id = vec["id"]
        topic = vec["topic"]
        payload = vec["payload"]
        qos = vec["qos"]
        retain = vec["retain"]

        client_type, body_str, is_online = adapter.validate_presence_message(
            topic=topic,
            payload=payload,
            qos=qos,
            retain=retain,
        )

        assert client_type == vec["client_type"]
        assert body_str == payload
        if "online" in payload:
            assert is_online is True
        else:
            assert is_online is False


def test_presence_qos_and_retain_invariants():
    """Verify rejection of presence messages without QoS 1 or retain=True."""
    adapter = AgentContractV1Adapter()
    with pytest.raises(ContractValidationError, match="QoS 1"):
        adapter.validate_presence_message(
            topic="dev/000100773/app",
            payload="app_online",
            qos=0,
            retain=True,
        )

    with pytest.raises(ContractValidationError, match="retain=true"):
        adapter.validate_presence_message(
            topic="dev/000100773/app",
            payload="app_online",
            qos=1,
            retain=False,
        )


# ── 3. Method 7000 (Stream Control) Golden Vectors (10 vectors) ───────────────


def test_method_7000_golden_vectors_requests_and_responses():
    """Verify all 10 Method 7000 vectors from golden_vectors_v1.json."""
    data = _load_golden_vectors()
    vectors = data.get("method_7000_vectors", [])
    assert len(vectors) == 10

    adapter = AgentContractV1Adapter()
    sn = "000100773"

    for vec in vectors:
        vec_id = vec["id"]
        req = vec["request"]
        exp_res = vec["expected_response"]

        # 1. Outbound request adaptation
        outbound = adapter.adapt_outbound_stream_control(req["payload"], sn=sn)
        assert outbound["method_code"] == METHOD_STREAM_CONTROL
        assert outbound["action"] == req["payload"]["action"]
        assert outbound["command_id"] == req["payload"]["command_id"]
        assert outbound["sn"] == sn

        # Ensure no commercial fields in adapted request
        assert_no_commercial_fields(outbound)

        # 2. Inbound response adaptation
        inbound_resp, is_dup = adapter.adapt_inbound_stream_control_response(
            exp_res["payload"], sn=sn
        )
        assert inbound_resp.status == exp_res["payload"]["status"]
        assert inbound_resp.command_id == exp_res["payload"]["command_id"]


def test_method_7000_coordinate_conversion():
    """Verify int coordinates (0..65535) are converted to normalized float 0.0..1.0."""
    adapter = AgentContractV1Adapter()
    raw_cmd = {
        "action": "mouse_click",
        "command_id": "clk_test",
        "x": 32768,
        "y": 16384,
        "button": "left",
    }
    adapted = adapter.adapt_outbound_stream_control(raw_cmd, sn="000100773")
    assert pytest.approx(adapted["x_norm"], abs=0.001) == 0.5
    assert pytest.approx(adapted["y_norm"], abs=0.001) == 0.25


# ── 4. Method 7001 (Command Execution) Golden Vectors (4 vectors) ─────────────


def test_method_7001_golden_vectors_and_streaming_chunks():
    """Verify all 4 Method 7001 vectors from golden_vectors_v1.json."""
    data = _load_golden_vectors()
    vectors = data.get("method_7001_vectors", [])
    assert len(vectors) == 4

    adapter = AgentContractV1Adapter()
    sn = "000100773"

    for vec in vectors:
        vec_id = vec["id"]
        req = vec["request"]["payload"]

        # 1. Outbound exec request adaptation
        outbound = adapter.adapt_outbound_exec(
            task_id=req["id"],
            session_id=req["session_id"],
            command_line=req["command_line"],
            shell=req["shell"],
            ttl_sec=req["ttl_sec"],
            sn=sn,
            topic=req.get("topic"),
        )
        assert outbound["id"] == req["id"]
        assert outbound["method_code"] == METHOD_EXEC_COMMAND
        assert outbound["session_id"] == req["session_id"]
        assert outbound["shell"] == req["shell"]

        # 2. Inbound streaming chunks adaptation
        for chunk_entry in vec.get("stream_chunks", []):
            chunk_payload = chunk_entry["payload"]
            envelope, is_dup = adapter.adapt_inbound_stream_chunk(chunk_payload, sn=sn)
            assert envelope.session_id == chunk_payload["session_id"]
            assert envelope.seq == chunk_payload["seq"]
            assert envelope.eof == chunk_payload["eof"]
            if chunk_payload.get("stream"):
                assert envelope.stream == chunk_payload["stream"]
            if chunk_payload["eof"]:
                assert envelope.kind == OutputKind.RESULT
                assert envelope.exit_code == chunk_payload.get("exit_code")

        # 3. Final response adaptation
        final_res = vec["final_response"]["payload"]
        resp, is_dup = adapter.adapt_inbound_exec_response(final_res, sn=sn)
        assert resp.id == final_res["id"]
        assert resp.method_code == METHOD_EXEC_COMMAND
        assert resp.status == final_res["status"]
        assert resp.exit_code == final_res["exit_code"]


# ── 5. Method 7002 (Task Cancellation) Golden Vectors (2 vectors) ─────────────


def test_method_7002_golden_vectors():
    """Verify all 2 Method 7002 vectors from golden_vectors_v1.json."""
    data = _load_golden_vectors()
    vectors = data.get("method_7002_vectors", [])
    assert len(vectors) == 2

    adapter = AgentContractV1Adapter()
    sn = "000100773"

    for vec in vectors:
        vec_id = vec["id"]
        req = vec["request"]["payload"]
        exp_res = vec["expected_response"]["payload"]

        outbound = adapter.adapt_outbound_cancel(
            task_id=req["id"],
            target_task_id=req["target_task_id"],
            target_session_id=req.get("target_session_id"),
        )
        assert outbound["id"] == req["id"]
        assert outbound["method_code"] == METHOD_CANCEL_TASK
        assert outbound["target_task_id"] == req["target_task_id"]

        resp, is_dup = adapter.adapt_inbound_cancel_response(exp_res, sn=sn)
        assert resp.id == exp_res["id"]
        assert resp.method_code == METHOD_CANCEL_TASK
        assert resp.status == exp_res["status"]


# ── 6. L4RTP Wire Protocol Vectors (3 vectors) ────────────────────────────────


def test_l4rtp_wire_protocol_vectors():
    """Verify all 3 L4RTP wire protocol vectors from golden_vectors_v1.json."""
    data = _load_golden_vectors()
    vectors = data.get("l4rtp_wire_vectors", [])
    assert len(vectors) == 3

    # Vector 1: Preamble
    vec_preamble = next(v for v in vectors if v["id"] == "vec-rtp-preamble")
    wire_bytes = bytes.fromhex(vec_preamble["wire_hex"])
    parsed_preamble = verify_l4rtp_preamble(wire_bytes)
    exp = vec_preamble["expected_parsed"]
    assert parsed_preamble["magic"] == exp["magic"]
    assert parsed_preamble["version"] == exp["version"]
    assert parsed_preamble["sn"] == exp["sn"]

    # Vector 2: Video frame header
    vec_video = next(v for v in vectors if v["id"] == "vec-rtp-video-frame")
    header_bytes = bytes.fromhex(vec_video["header_hex"])
    parsed_video = verify_l4rtp_frame_header(header_bytes)
    assert parsed_video["channel"] == 1
    assert parsed_video["channel_name"] == "RTP"
    assert parsed_video["payload_length_bytes"] == vec_video["expected_length"]

    # Vector 3: RTCP frame header
    vec_rtcp = next(v for v in vectors if v["id"] == "vec-rtp-rtcp-frame")
    rtcp_bytes = bytes.fromhex(vec_rtcp["header_hex"])
    parsed_rtcp = verify_l4rtp_frame_header(rtcp_bytes)
    assert parsed_rtcp["channel"] == 2
    assert parsed_rtcp["channel_name"] == "RTCP"
    assert parsed_rtcp["payload_length_bytes"] == vec_rtcp["expected_length"]


# ── 7. Commercial Field Isolation Tests ───────────────────────────────────────


def test_commercial_fields_rejection_in_outbound_requests():
    """Verify that any commercial or billing attribute is rejected with CommercialFieldViolationError."""
    adapter = AgentContractV1Adapter()

    # Leaking price or billing to 7000 request
    with pytest.raises(CommercialFieldViolationError, match="price"):
        adapter.adapt_outbound_stream_control(
            {
                "action": "stream_start",
                "command_id": "c1",
                "price": 100,
            },
            sn="000100773",
        )

    with pytest.raises(CommercialFieldViolationError, match="billing"):
        adapter.adapt_outbound_stream_control(
            {
                "action": "inventory_get",
                "command_id": "c2",
                "billing_period": "2026-09",
            },
            sn="000100773",
        )

    # Leaking org_id or tenant_id
    with pytest.raises(CommercialFieldViolationError, match="tenant_id"):
        assert_no_commercial_fields({"tenant_id": 42, "payload": {}})

    with pytest.raises(CommercialFieldViolationError, match="org_id"):
        assert_no_commercial_fields({"org_id": 1, "action": "stream_stop"})


# ── 8. Duplicate / Retry Handling Tests ───────────────────────────────────────


def test_chunk_deduplication():
    """Verify that duplicate streaming chunks are detected and flagged."""
    adapter = AgentContractV1Adapter()
    sn = "000100773"
    chunk = {
        "session_id": "sess-exec-9001",
        "seq": 1,
        "data": "output line 1\n",
        "eof": False,
    }

    env1, is_dup1 = adapter.adapt_inbound_stream_chunk(chunk, sn=sn)
    assert is_dup1 is False
    assert env1.seq == 1

    # Second arrival of seq 1
    env2, is_dup2 = adapter.adapt_inbound_stream_chunk(chunk, sn=sn)
    assert is_dup2 is True

    # Seq 2 arrival
    chunk_seq2 = {
        "session_id": "sess-exec-9001",
        "seq": 2,
        "data": "output line 2\n",
        "eof": False,
    }
    env3, is_dup3 = adapter.adapt_inbound_stream_chunk(chunk_seq2, sn=sn)
    assert is_dup3 is False


@pytest.mark.asyncio
async def test_session_registry_drops_duplicate_chunks():
    """Verify that DiagnosticSessionRegistry ignores duplicate chunks."""
    reg = DiagnosticsSessionRegistry()
    sn = "000100773"
    session_id = "sess-dup-test"
    session = DiagnosticSession(
        sn=sn,
        session_id=session_id,
        kind="exec",
        ttl_sec=60,
    )
    await reg.register(session)

    env = DeviceOutputEnvelope(
        session_id=session_id,
        seq=1,
        stream="stdout",
        kind=OutputKind.STDOUT,
        data="data chunk\n",
    )

    # First delivery: enqueued
    delivered1 = await reg.route_output(sn, env)
    assert delivered1 is True
    assert session.queue.qsize() == 2  # started status + output

    # Duplicate delivery: acknowledged, but not enqueued again
    delivered2 = await reg.route_output(sn, env)
    assert delivered2 is True
    assert session.queue.qsize() == 2


# ── 9. Unknown Capability Handling Tests ───────────────────────────────────────


def test_unknown_capability_rejection():
    """Verify clean rejection of unknown methods, actions, or shells."""
    adapter = AgentContractV1Adapter()

    # Unknown action in 7000
    with pytest.raises(UnknownCapabilityError, match="Unsupported action"):
        adapter.adapt_outbound_stream_control(
            {"action": "reboot_machine", "command_id": "inv_001"},
            sn="000100773",
        )

    # Unknown shell in 7001
    with pytest.raises(UnknownCapabilityError, match="Unsupported shell"):
        adapter.adapt_outbound_exec(
            task_id="t1",
            session_id="s1",
            command_line="ls",
            shell="bash",
            sn="000100773",
        )


# ── 10. Timeout and Error Status Handling Tests ───────────────────────────────


def test_agent_error_status_mapping():
    """Verify handling of Agent Contract v1 error responses."""
    adapter = AgentContractV1Adapter()
    sn = "000100773"

    # 7000 desktop_locked
    resp_locked, _ = adapter.adapt_inbound_stream_control_response(
        {
            "status": "error",
            "command_id": "cmd_lock",
            "error": "desktop_locked",
            "desktop_locked": True,
            "session_available": False,
        },
        sn=sn,
    )
    assert resp_locked.status == "error"
    assert resp_locked.error == "desktop_locked"
    assert resp_locked.desktop_locked is True

    # 7000 busy
    resp_busy, _ = adapter.adapt_inbound_stream_control_response(
        {
            "status": "busy",
            "command_id": "cmd_busy",
            "error": "already_running",
        },
        sn=sn,
    )
    assert resp_busy.status == "busy"
    assert resp_busy.error == "already_running"

    # 7001 timed_out
    resp_timeout, _ = adapter.adapt_inbound_exec_response(
        {
            "id": "task-timeout-01",
            "session_id": "sess-to",
            "method_code": 7001,
            "status": "timed_out",
            "exit_code": -1,
            "execution_time_ms": 2005,
        },
        sn=sn,
    )
    assert resp_timeout.status == "timed_out"
    assert resp_timeout.exit_code == -1

    # 7002 not_found
    resp_notfound, _ = adapter.adapt_inbound_cancel_response(
        {
            "id": "task-cncl-99",
            "method_code": 7002,
            "target_task_id": "task-missing",
            "status": "not_found",
            "message": "Task task-missing not found",
        },
        sn=sn,
    )
    assert resp_notfound.status == "not_found"


# ── 11. Regression Tests (String IDs, Missing kind/stream on EOF) ──────────────


def test_regression_string_session_id_in_chunks_and_payloads():
    """Regression test: string session_id (e.g. 'sess-exec-9001') was previously rejected by UUID constraint."""
    # Chunk with arbitrary string session_id
    raw_chunk = {
        "session_id": "sess-exec-9001",
        "seq": 1,
        "data": "hostname output\n",
        "stream": "stdout",
        "eof": False,
    }
    envelope = decode_output_payload(raw_chunk)
    assert envelope.session_id == "sess-exec-9001"
    assert envelope.kind == OutputKind.STDOUT


def test_regression_missing_kind_and_stream_on_eof():
    """Regression test: EOF chunk with no 'kind' and no 'stream' was previously rejected by extra='forbid'."""
    eof_chunk = {
        "session_id": "sess-exec-9001",
        "seq": 2,
        "data": "",
        "eof": True,
        "exit_code": 0,
    }
    envelope = decode_output_payload(eof_chunk)
    assert envelope.session_id == "sess-exec-9001"
    assert envelope.kind == OutputKind.RESULT
    assert envelope.stream == "stdout"
    assert envelope.eof is True
    assert envelope.exit_code == 0

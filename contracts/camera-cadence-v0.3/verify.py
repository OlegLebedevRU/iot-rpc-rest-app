"""Independent nominal/proof decision oracle, not an SDP or VCL parser."""

import hashlib
import json
import re
from decimal import Decimal
from pathlib import Path

MAX = (1 << 63) - 1


def declared_nominal(values):
    """Input is already-selected validated RTSP metadata, never measured rate."""
    if not values or any(
        not isinstance(v, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", v)
        for v in values
    ):
        return None
    parsed = [Decimal(v) for v in values]
    if any(not 1 <= v <= 120 or v != v.to_integral_value() for v in parsed):
        return None
    return int(parsed[0]) if all(v == parsed[0] for v in parsed) else None


def observe(case):
    nominal = declared_nominal(case["declared_nominal"])
    if nominal is None:
        return {"state": "unavailable", "reason": "declared_nominal_unknown"}
    prior, last_idr, ready = None, None, False
    extended, observed_kfi = 0, None
    facts = case["source_facts"]
    for i, au in enumerate(case["access_units"]):
        if not ready and au["local_elapsed_ms"] >= 30000:
            return {"state": "unavailable", "reason": "acquisition_expired"}
        if (
            any(au.get(k, v) != v for k, v in facts.items())
            or au.get("declared_nominal", nominal) != nominal
        ):
            return {"state": "failed", "reason": "immutable_source_changed"}
        if (
            not au.get("complete", True)
            or not au.get("valid", True)
            or au.get("b_frames", False)
            or au.get("sequence_loss", False)
        ):
            return {"state": "failed", "reason": "bitstream"}
        t = au["timestamp"]
        if type(t) is not int or not 0 <= t < 1 << 32:
            return {"state": "failed", "reason": "timestamp"}
        if prior is not None:
            delta = (t - prior) & 0xFFFFFFFF
            if not 0 < delta < 1 << 31 or extended > MAX - delta:
                return {"state": "failed", "reason": "timestamp"}
            extended += delta
        prior = t
        if au.get("idr", False):
            if not au.get("repeated_ps", False):
                return {"state": "failed", "reason": "parameter_sets"}
            if last_idr is not None and not ready:
                span = extended - last_idr
                interval_ms = (span + 89) // 90
                if 250 <= interval_ms <= 5000:
                    ready, observed_kfi = True, interval_ms
            last_idr = extended
    return {
        "state": "ready" if ready else "pending",
        "nominal_fps": nominal,
        "keyframe_interval_ms": observed_kfi,
    }


def main():
    root = Path(__file__).resolve().parent
    manifest = json.loads((root / "manifest.json").read_text())
    for name, expected in manifest["files"].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected, name
    vectors = json.loads((root / "vectors.json").read_text())
    results = []
    for case in vectors["cases"]:
        actual = observe(case)
        assert actual == case["expected"], (case["name"], actual, case["expected"])
        results.append({"name": case["name"], **actual})
    print(
        json.dumps(
            {
                "evidence": "offline policy decisions over synthetic validated facts",
                "actual_rate_is_admission_input": False,
                "history_ring_bytes": 0,
                "results": results,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

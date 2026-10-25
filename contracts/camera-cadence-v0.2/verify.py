"""Offline timestamp-policy experiment only; markers never prove VCL/AU validity."""

import bisect
from collections import deque
import hashlib
import json
from pathlib import Path

MAX = (1 << 63) - 1


def within_rate(f, count, span):
    if not 1 <= f <= 120 or not 0 < count <= 1024 or not 0 < span <= MAX:
        return False
    if max(90000 * count * 100, f * span * 102) > MAX:
        return False
    return abs(90000 * count - f * span) * 100 <= 2 * f * span


def proof_eligible(
    elapsed_ms,
    span_ticks,
    complete_gops,
    survivors,
    at_boundary=True,
    full_au=True,
    repeated_ps=True,
    no_b=True,
):
    return (
        type(elapsed_ms) is int
        and 0 <= elapsed_ms < 10000
        and type(span_ticks) is int
        and 360000 <= span_ticks < 900000
        and complete_gops >= 2
        and len(survivors) == 1
        and all(value is True for value in (at_boundary, full_au, repeated_ps, no_b))
    )


def all_ring_alignments():
    # Contract oracle for the exact retained predecessor, not a firmware parser.
    for initial in range(1024):
        ring = [None] * 1024
        head, count = initial, 0
        for t in range(0, 450000, 375):
            while count >= 2 and ring[(head + 1) % 1024] <= t - 360000:
                head = (head + 1) % 1024
                count -= 1
            assert count < 1024
            ring[(head + count) % 1024] = t
            count += 1
            if t >= 360000:
                assert ring[head] <= t - 360000 < ring[(head + 1) % 1024]
    return 1024


def candidates(timestamps, gop_boundaries=(), facts=None, local_elapsed_ms=None):
    if not timestamps or any(
        type(t) is not int or not 0 <= t < 1 << 32 for t in timestamps
    ):
        return []
    extended = [0]
    for prior, current in zip(timestamps, timestamps[1:]):
        delta = (current - prior) & 0xFFFFFFFF
        if not 0 < delta < (1 << 31) or extended[-1] > MAX - delta:
            return []
        extended.append(extended[-1] + delta)
    if extended[-1] < 360000:
        return []
    survivors = set(range(1, 121))
    boundaries = set(gop_boundaries)
    prior_boundary = None
    completed = 0
    acquired_reference = 0
    ready = False
    reference = None
    for i, current in enumerate(extended):
        if not ready and (
            current >= 900000
            or local_elapsed_ms is not None
            and local_elapsed_ms[i] >= 10000
        ):
            return []
        if i:
            delta = current - extended[i - 1]
            survivors = {f for f in survivors if 45000 <= f * delta <= 180000}
        if current >= 360000:
            j = bisect.bisect_right(extended, current - 360000, 0, i) - 1
            survivors = {
                f for f in survivors if within_rate(f, i - j, current - extended[j])
            }
        if not survivors:
            return []
        if i in boundaries:
            if prior_boundary is not None:
                span = current - extended[prior_boundary]
                if not 0 < span <= 450000 or ready and 100 * span > 105 * reference:
                    return []
                completed += 1
                if not ready:
                    acquired_reference = max(acquired_reference, span)
            prior_boundary = i
        eligible_boundary = (
            not boundaries
            or i in boundaries
            and completed >= 2
            and 22500 <= acquired_reference <= 450000
        )
        if (
            not ready
            and current >= 360000
            and len(survivors) == 1
            and eligible_boundary
        ):
            ready = True
            reference = acquired_reference
            if facts is not None:
                facts.update(ready_au_index=i, gop_reference_ticks=reference)
    return sorted(survivors) if ready or len(survivors) > 1 else []


def series(delta, count=241, offset=0):
    return [(offset + round(i * delta)) & 0xFFFFFFFF for i in range(count)]


def main():
    root = Path(__file__).resolve().parent
    manifest = json.loads((root / "manifest.json").read_text())
    for name, expected in manifest["files"].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected, name
    assert proof_eligible(9999, 899999, 2, [20])
    assert not proof_eligible(10000, 899999, 2, [20])
    assert not proof_eligible(9999, 900000, 2, [20])
    assert not proof_eligible(9999, 359999, 2, [20])
    assert not proof_eligible(9999, 360000, 1, [20])
    assert not proof_eligible(9999, 360000, 2, [29, 30])
    for field in ("at_boundary", "full_au", "repeated_ps", "no_b"):
        assert not proof_eligible(5000, 450000, 2, [20], **{field: False})
    assert within_rate(20, 102, 450000)
    assert not within_rate(20, 102, 449999)
    assert within_rate(20, 98, 450000)
    assert not within_rate(20, 98, 450001)
    assert not within_rate(120, 1024, MAX)
    assert 100 * 94500 == 105 * 90000 and 100 * 94501 > 105 * 90000
    assert 20 * 2250 == 45000 and 20 * 9000 == 180000
    assert not 45000 <= 20 * 2249 <= 180000
    assert not 45000 <= 20 * 9001 <= 180000
    ring = deque()
    peak = 0
    for tick in range(0, 3600000, 375):
        while len(ring) >= 2 and ring[1] <= tick - 360000:
            ring.popleft()
        ring.append(tick)
        peak = max(peak, len(ring))
        assert len(ring) <= 1024
        if tick >= 360000:
            assert ring[0] <= tick - 360000 < ring[1]
    cases = {
        "exact20": (series(4500), [20]),
        "bounded20_3_nominal20": (series(90000 / 20.3), [20]),
        "sustained20_7_changes_nominal_candidate": (series(90000 / 20.7), [21]),
        "native25_no_desktop_geometry_cap": (series(3600), [25]),
        "wrap20": (series(4500, offset=0xFFF00000), [20]),
        "short_prefix": (series(4500, count=60), []),
    }
    duplicate = series(4500)
    duplicate[100] = duplicate[99]
    cases["duplicate_rejected"] = (duplicate, [])
    reverse = series(4500)
    reverse[100] = reverse[99] - 1
    cases["backward_rejected"] = (reverse, [])
    half_wrap = series(4500)
    half_wrap[100] = (half_wrap[99] + (1 << 31)) & 0xFFFFFFFF
    cases["ambiguous_half_wrap_rejected"] = (half_wrap, [])
    gap = series(4500)
    gap[120:] = [v + 90000 for v in gap[120:]]
    cases["one_second_stall_rejected"] = (gap, [])
    hidden = series(90000 / 21, count=169)
    hidden += [hidden[-1] + round(i * 90000 / 19) for i in range(1, 153)]
    assert 90000 * (len(hidden) - 1) == 20 * (hidden[-1] - hidden[0])
    cases["whole_mean20_hides_eight_seconds21_then19_rejected"] = (hidden, [])
    results = []
    results.append(
        {
            "name": "thresholds_and_memory",
            "rate_upper_and_lower_equality_pass": True,
            "one_tick_outside_reject": True,
            "gop_upper_equality_pass_one_tick_over_reject": True,
            "au_delta_endpoints_pass_outside_reject": True,
            "checked64_overflow_reject": True,
            "ring_capacity": 1024,
            "peak_points_over_40seconds_at375ticks": peak,
            "all_ring_start_alignments_tested": all_ring_alignments(),
            "acquisition_deadline_equalities_reject": True,
            "missing_au_ps_no_b_and_nonboundary_reject": True,
        }
    )
    for name, (timestamps, expected) in cases.items():
        actual = candidates(timestamps)
        assert actual == expected, (name, actual, expected)
        results.append({"name": name, "candidate_fps": actual})
    ambiguous = candidates(series(90000 / 29.5))
    assert ambiguous == [29, 30]
    results.append(
        {"name": "ambiguous29_5_rejected", "candidates": ambiguous, "admission": False}
    )
    high = series(900, count=501)
    high_candidates = candidates(high)
    assert len(high_candidates) > 1
    results.append(
        {
            "name": "high_fps_ambiguous_without_declaration",
            "candidates": high_candidates,
            "admission": False,
        }
    )
    delayed = series(90000 / 29.5, count=121)
    delayed += [delayed[-1] + round(i * 90000 / 29) for i in range(1, 121)]
    delayed_facts = {}
    assert candidates(
        delayed,
        gop_boundaries=[0, 30, 60, 90, 120, 155, 185, 215, 240],
        facts=delayed_facts,
    ) == [29]
    assert delayed_facts["ready_au_index"] == 155
    assert delayed_facts["gop_reference_ticks"] > 100000
    assert candidates(series(90000 / 29.5, count=401)) == []
    deadline_trace = series(4500, count=201)
    assert candidates(deadline_trace, gop_boundaries=[0, 100, 200]) == []
    assert candidates(deadline_trace[:200], gop_boundaries=[0, 100, 199]) == [20]
    short = series(4500, count=81)
    assert candidates(short, local_elapsed_ms=[i * 9999 // 80 for i in range(81)]) == [
        20
    ]
    assert (
        candidates(short, local_elapsed_ms=[i * 10000 // 80 for i in range(81)]) == []
    )
    results.append(
        {
            "name": "delayed_unique_candidate_updates_acquisition_gop_until_actual_ready",
            "candidates": [29],
            **delayed_facts,
        }
    )
    results.append(
        {
            "name": "pending_ambiguity_and_rtp_local_deadline_equalities_reject",
            "acquisition_restarts": False,
            "passed": True,
        }
    )
    fixed = series(4500)
    assert candidates(fixed, gop_boundaries=[0, 20, 40, 60, 80, 100]) == [20]
    assert candidates(fixed, gop_boundaries=[0, 20, 40, 60, 80, 82, 100]) == [20]
    assert candidates(fixed, gop_boundaries=[0, 20, 40, 60, 80, 102]) == []
    results.append(
        {
            "name": "extra_full_validated_short_idr_timestamp_hypothesis",
            "candidates": [20],
            "full_au_proof_required": True,
        }
    )
    results.append({"name": "gop_growth_after_ready_rejected", "candidates": []})
    longer = series(4500, count=361)
    assert candidates(longer, gop_boundaries=[0, 20, 120, 222]) == []
    results.append(
        {
            "name": "gop_above_5seconds_even_within105percent_reject",
            "reference_ticks": 450000,
            "later_ticks": 459000,
            "candidates": [],
        }
    )
    revoke = series(4500, count=101)
    assert candidates(revoke) == [20]
    revoke += [revoke[-1] + 3600 * i for i in range(1, 151)]
    assert candidates(revoke) == []
    results.append(
        {
            "name": "post_start_rate_change_revokes_without_reset",
            "initial_candidates": [20],
            "later_candidates": [],
        }
    )
    trace = Path(__file__).resolve().parent / "fixtures/diagnostic-markers.json"
    source = json.loads(trace.read_text())
    stamps = source["marker_timestamps"]
    boundaries = [
        i for i, value in enumerate(source["marker_irap_header_seen"]) if value
    ]
    results.append(
        {
            "name": "real_marker_trace_diagnostic_only",
            "fps_window_only_candidates": candidates(stamps),
            "candidate_fps_including_header_gop_hypothesis": candidates(
                stamps, gop_boundaries=boundaries
            ),
            "marker_count": len(stamps),
            "header_irap_indices": boundaries,
            "full_au_proof": False,
            "physical_port_proof": False,
            "admission": False,
        }
    )
    print(
        json.dumps(
            {
                "status": "policy-review-only",
                "frozen_schemas_modified": False,
                "runtime_changed": False,
                "results": results,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

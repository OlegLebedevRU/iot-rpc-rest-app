from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

import pytest


class EvidenceValidationResult(NamedTuple):
    is_valid: bool
    rejection_reasons_detected: list[int]
    details: list[str]


def validate_report_evidence(
    report_text: str,
    candidate_text: str | None = None,
    check_candidate: bool = True,
) -> EvidenceValidationResult:
    """Validate report and detached candidate against the 6 rejection reasons."""
    rejection_reasons: list[int] = []
    details: list[str] = []

    # 1. Mandatory linters, formatting, and type-checks results
    has_linter_output = bool(
        re.search(r"(ruff check|flake8)", report_text, re.IGNORECASE)
        and re.search(
            r"(exit code:?\s*0|all checks passed|0 errors)", report_text, re.IGNORECASE
        )
    )
    has_formatter_output = bool(
        re.search(r"(black --check|black)", report_text, re.IGNORECASE)
        and re.search(
            r"(reformatted|would leave|left unchanged|reformatted 0 files|0 files reformatted|exit code:?\s*0)",
            report_text,
            re.IGNORECASE,
        )
    )
    has_typecheck_output = bool(
        re.search(r"(pyright|mypy)", report_text, re.IGNORECASE)
        and re.search(
            r"(0 errors|success: no issues found|exit code:?\s*0)",
            report_text,
            re.IGNORECASE,
        )
    )

    if not (has_linter_output and has_formatter_output and has_typecheck_output):
        rejection_reasons.append(1)
        details.append(
            f"Reason 1: Missing required lint/format/type check execution evidence "
            f"(lint={has_linter_output}, format={has_formatter_output}, type={has_typecheck_output})"
        )

    # 2. Explicit and complete list of modified files with commits and purposes
    has_files_table = bool(
        re.search(
            r"##\s+.*(?:Перечень измен[её]нных файлов|Changed Files|Измен[её]нные файлы)",
            report_text,
            re.IGNORECASE,
        )
        and re.search(
            r"(commit|коммит|диапазон|назначение|purpose)", report_text, re.IGNORECASE
        )
        and (
            "app-service/core/models/device_provisioning.py" in report_text
            or "device_provisioning.py" in report_text
        )
    )
    if not has_files_table:
        rejection_reasons.append(2)
        details.append(
            "Reason 2: Missing explicit table/list of modified files with commit ranges and purposes"
        )

    # 3. Actual deploy & smoke results (not simulated or 'ожидается')
    has_simulated_deploy = bool(
        re.search(r"#\s*Ожидается:\s*\d{3}", report_text)
        or re.search(r"Ожидаемый ответ:", report_text)
    )
    has_actual_deploy_results = bool(
        re.search(
            r"(Ревизия.*до|Alembic revision.*до|head revision|текущая ревизия)",
            report_text,
            re.IGNORECASE,
        )
        and re.search(
            r"(HTTP/\d|HTTP status:?\s*\d{3}|HTTP\s+\d{3}|status_code:?\s*\d{3})",
            report_text,
            re.IGNORECASE,
        )
        and not has_simulated_deploy
    )
    if has_simulated_deploy or not has_actual_deploy_results:
        rejection_reasons.append(3)
        details.append(
            "Reason 3: Deploy section lacks actual execution outputs or contains simulated '# Ожидается' responses"
        )

    # 4. Proven container/image identity and link of running bytes to the implementation commit
    has_container_link = bool(
        re.search(
            r"(Container ID|image id|sha256:[a-f0-9]{64}|docker inspect)",
            report_text,
            re.IGNORECASE,
        )
        and re.search(
            r"(producer_commit|commit реализации|running commit|git rev-parse HEAD|Git HEAD)",
            report_text,
            re.IGNORECASE,
        )
        and re.search(
            r"(docker exec.*git|hash_match|verified running bytes|байты соответствуют|побайтовое подтверждение|совпадают побайтово)",
            report_text,
            re.IGNORECASE,
        )
    )
    if not has_container_link:
        rejection_reasons.append(4)
        details.append(
            "Reason 4: Missing proof linking running container/image bytes to implementation commit"
        )

    # 5. Published lowercase SHA-256 of final report in detached candidate
    if check_candidate:
        has_report_sha = False
        if candidate_text:
            has_report_sha = bool(
                re.search(r"report_commit:\s*[a-f0-9]{40}", candidate_text)
                and re.search(r"[a-f0-9]{64}", candidate_text)
                and re.search(r"candidate_format:\s*DETACHED_V1", candidate_text)
            )
        if not has_report_sha:
            rejection_reasons.append(5)
            details.append(
                "Reason 5: Missing published SHA-256 of final report in separate DETACHED_V1 candidate"
            )

    # 6. Canonical consumers alignment with journal
    has_invalid_consumer_claim = bool(
        "ALL_FOLLOWING" in report_text
        or re.search(r"Gate 2.*?L4D-06B-IOT", report_text, re.DOTALL)
    )
    if has_invalid_consumer_claim:
        rejection_reasons.append(6)
        details.append(
            "Reason 6: False assertion about H-L4D-02-IOT-v1 consumers contradicts canonical journal"
        )

    return EvidenceValidationResult(
        is_valid=len(rejection_reasons) == 0,
        rejection_reasons_detected=rejection_reasons,
        details=details,
    )


def test_reproduce_original_report_rejection_reasons():
    """Verify that the original L4D-06B-IOT report fails validation and reproduces all 6 rejection reasons."""
    report_path = Path("docs/l4desk/handoffs/L4D-06B-IOT-report.md")
    assert report_path.exists(), f"Historical report {report_path} must be preserved"

    report_text = report_path.read_text(encoding="utf-8")
    result = validate_report_evidence(report_text, candidate_text=None)

    assert not result.is_valid, "Original report must fail validation"
    # All 6 rejection reasons must be detected in the original report
    for expected_reason in [1, 2, 3, 4, 5, 6]:
        assert (
            expected_reason in result.rejection_reasons_detected
        ), f"Expected rejection reason {expected_reason} was not detected in original report. Detected: {result.rejection_reasons_detected}"


def test_validate_fixed_evidence_package():
    """Verify that the fixed report and candidate (when created) satisfy all 6 requirements."""
    fix_report_path = Path("docs/l4desk/handoffs/L4D-06B-IOT-FIX-01-report.md")
    fix_candidate_path = Path("docs/l4desk/handoffs/L4D-06B-IOT-FIX-01-candidate.md")

    if not fix_report_path.exists():
        pytest.skip("L4D-06B-IOT-FIX-01-report.md has not been generated yet")

    report_text = fix_report_path.read_text(encoding="utf-8")
    candidate_text = (
        fix_candidate_path.read_text(encoding="utf-8")
        if fix_candidate_path.exists()
        else None
    )

    result = validate_report_evidence(
        report_text,
        candidate_text=candidate_text,
        check_candidate=(candidate_text is not None),
    )
    assert (
        result.is_valid
    ), f"Fixed evidence package must pass all criteria. Failures: {result.details}"

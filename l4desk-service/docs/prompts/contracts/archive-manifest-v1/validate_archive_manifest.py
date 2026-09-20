#!/usr/bin/env python3
"""
Archive Manifest Contract v1 — Validator and Acceptance Suite.
Tests Draft 2020-12 schemas and golden positive/negative fixtures.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError


def is_older_than_three_full_months(source_month_str: str, reference_date: datetime) -> bool:
    """
    Validates the 3-month hot retention rule:
    Archive target month must be older than 3 full calendar months.
    E.g., if reference_date is September 2026 (month 9),
    the 3 full recent months are Aug (8), Jul (7), Jun (6).
    Eligible months must be May 2026 (5) or earlier.
    """
    parts = source_month_str.split("-")
    s_year, s_month = int(parts[0]), int(parts[1])
    
    # Calculate month difference:
    diff_months = (reference_date.year - s_year) * 12 + (reference_date.month - s_month)
    return diff_months > 3


def main() -> int:
    contract_dir = Path(__file__).resolve().parent
    schema_path = contract_dir / "archive-manifest.schema.json"
    schemas_bundle_path = contract_dir / "schemas.json"
    examples_path = contract_dir / "examples.json"

    print(f"[*] Validating Archive Manifest Contract in {contract_dir}")

    # 1. Load schema
    with open(schema_path, "r", encoding="utf-8") as f:
        manifest_schema = json.load(f)

    with open(schemas_bundle_path, "r", encoding="utf-8") as f:
        schemas_bundle = json.load(f)

    # Validate the schemas themselves
    Draft202012Validator.check_schema(manifest_schema)
    Draft202012Validator.check_schema(schemas_bundle)
    print("  [+] JSON Schemas are valid Draft 2020-12")

    validator = Draft202012Validator(manifest_schema, format_checker=FormatChecker())
    envelope_validator = Draft202012Validator(schemas_bundle["$defs"]["RecordEnvelope"], format_checker=FormatChecker())

    # 2. Load examples
    with open(examples_path, "r", encoding="utf-8") as f:
        examples_data = json.load(f)

    cases = examples_data.get("cases", [])
    print(f"[*] Executing {len(cases)} acceptance vector cases...")

    passed = 0
    failed = 0

    ref_date = datetime(2026, 9, 21, 0, 3, 0, tzinfo=timezone.utc)

    for case in cases:
        case_id = case["id"]
        expected_valid = case["valid"]
        schema_type = case.get("schema", "ArchiveManifest")
        body = case["body"]

        active_validator = envelope_validator if schema_type == "RecordEnvelope" else validator

        errors = list(active_validator.iter_errors(body))
        schema_is_valid = len(errors) == 0

        # Additional domain checks if schema passed
        domain_valid = True
        domain_errors = []

        if schema_is_valid and schema_type == "ArchiveManifest":
            # Check 3-month hot retention rule
            month_str = body.get("source_month", "")
            if not is_older_than_three_full_months(month_str, ref_date):
                domain_valid = False
                domain_errors.append(f"Source month {month_str} violates 3 full months hot retention window relative to {ref_date.isoformat()}")

            # Check cursor guard invariant
            state = body.get("state")
            cursor_bounds = body.get("cursor_bounds") or {}
            through_cursor = cursor_bounds.get("through_cursor")
            consumers_cursor = cursor_bounds.get("consumers_passed_cursor")

            if state == "purged" and through_cursor is not None:
                if consumers_cursor is None or consumers_cursor < through_cursor:
                    domain_valid = False
                    domain_errors.append(f"Purge attempted when consumer cursor ({consumers_cursor}) < through_cursor ({through_cursor})")

            # Check reread checksum matching
            verification = body.get("verification") or {}
            if state in ("verified", "purged"):
                files = body.get("files", [])
                if files:
                    expected_sha = files[0].get("sha256")
                    reread_sha = verification.get("reread_checksum_sha256")
                    if expected_sha and reread_sha and expected_sha != reread_sha:
                        domain_valid = False
                        domain_errors.append(f"Verification reread SHA-256 mismatch: {expected_sha} vs {reread_sha}")

        overall_valid = schema_is_valid and domain_valid

        if overall_valid == expected_valid:
            print(f"  [PASS] {case_id} (expected_valid={expected_valid}, got={overall_valid})")
            passed += 1
        else:
            print(f"  [FAIL] {case_id} (expected_valid={expected_valid}, got={overall_valid})")
            if errors:
                for err in errors:
                    print(f"         Schema error: {err.message} at path {list(err.path)}")
            if domain_errors:
                for err in domain_errors:
                    print(f"         Domain error: {err}")
            failed += 1

    print(f"\n[+] Acceptance Suite Summary: {passed} passed, {failed} failed")
    if failed > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

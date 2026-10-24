"""Offline enrollment proposal rejects commits below its accepted offer."""

import runpy
from pathlib import Path


def test_camera_enrollment_proposal():
    root = Path(__file__).resolve().parents[4]
    oracle = runpy.run_path(
        str(root / "contracts/camera-enrollment-proposal/verify.py")
    )
    oracle["main"]()

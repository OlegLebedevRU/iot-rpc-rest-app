"""The proposed camera handshake stays executable without enabling a writer."""

import runpy
from pathlib import Path


def test_camera_monotonic_proposal_vectors():
    root = Path(__file__).resolve().parents[4]
    oracle = runpy.run_path(str(root / "contracts/camera-ctl-monotonic-v1/verify.py"))
    oracle["verify"]()

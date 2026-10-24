"""Verify raw package pins and both verifiers from an immutable Git export."""

import argparse
import hashlib
import io
import json
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[2]
PATHS = (
    "contracts/camera-enrollment-v0.2",
    "contracts/camera-ctl-monotonic-v1",
    "contracts/siplite-camera-v1",
    "contracts/siplite-camera-v1.1",
    "contracts/siplite-camera-v1.1.lock.json",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", default="HEAD")
    args = parser.parse_args()
    commit = (
        subprocess.check_output(
            ["git", "rev-parse", "--verify", args.revision + "^{commit}"],
            cwd=REPOSITORY,
        )
        .decode()
        .strip()
    )
    archive = subprocess.check_output(
        ["git", "archive", commit, *PATHS], cwd=REPOSITORY
    )
    scratch = REPOSITORY / "docs/local-files"
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="manifest-git-", dir=scratch) as directory:
        exported = Path(directory).resolve()
        assert exported.is_relative_to(scratch.resolve())
        with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
            bundle.extractall(exported, filter="data")
        contracts = exported / "contracts"
        package = contracts / "camera-enrollment-v0.2"
        manifest = json.loads((package / "manifest.json").read_bytes())
        pins = {
            package / "schema.json": manifest["schema_sha256"],
            contracts
            / "camera-ctl-monotonic-v1/camera-ctl.schema.json": manifest[
                "admission_schema_sha256"
            ],
            contracts
            / "siplite-camera-v1.1/hevc.schema.json": manifest["media_schema_sha256"],
        }
        pins.update(
            {
                package / "fixtures" / name: sha
                for name, sha in manifest["fixtures"].items()
            }
        )
        lock = json.loads((contracts / "siplite-camera-v1.1.lock.json").read_bytes())
        pins.update(
            {
                contracts / "siplite-camera-v1.1" / name: sha
                for name, sha in lock["files"].items()
            }
        )
        assert lock["schema_sha256"] == manifest["media_schema_sha256"]
        assert (
            lock["canonical_vectors_sha256"] == lock["files"]["canonical-vectors.json"]
        )
        for path, expected in pins.items():
            assert (
                hashlib.sha256(path.read_bytes()).hexdigest() == expected
            ), path.relative_to(exported)
        # --strict-bytes is supported by the fixed package, not the original PR143.
        subprocess.run(
            [sys.executable, str(package / "verify.py"), "--strict-bytes"], check=True
        )
        subprocess.run(
            [sys.executable, str(contracts / "siplite-camera-v1.1/verify.py")],
            check=True,
        )
    print(
        json.dumps(
            {
                "commit": commit,
                "raw_git_pins_verified": len(pins),
                "package_verifiers": 2,
            }
        )
    )


if __name__ == "__main__":
    main()

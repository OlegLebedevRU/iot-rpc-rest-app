"""Cross-check pinned firmware C integer-JCS and real MbedTLS SHA256, offline."""

import argparse
import hashlib
import json
import os
import runpy
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FIRMWARE_PIN = "b165b4da88da66da0411643f74b080a272e40653"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--firmware-repo", required=True, type=Path)
    parser.add_argument("--mbedtls-dir", required=True, type=Path)
    parser.add_argument("--cc", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    os.environ["CC"] = str(args.cc)
    os.environ["L4_HOST_MBEDTLS_DIR"] = str(args.mbedtls_dir)
    own = ROOT.parents[1] / "docs/local-files"
    own.mkdir(parents=True, exist_ok=True)
    sources = {}
    with tempfile.TemporaryDirectory(prefix="canonical-c-", dir=own) as temp:
        work = Path(temp).resolve()
        assert work.is_relative_to(own.resolve())
        for relative in (
            "main/l4_camera_canonical.c",
            "include/l4_camera_canonical.h",
            "tools/test_camera_canonical.py",
        ):
            raw = subprocess.check_output(
                [
                    "git",
                    "-C",
                    str(args.firmware_repo),
                    "show",
                    FIRMWARE_PIN + ":" + relative,
                ]
            )
            destination = work / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(raw)
            sources[relative] = hashlib.sha256(raw).hexdigest()
        host = runpy.run_path(str(work / "tools/test_camera_canonical.py"))
        lib = host["build"]()
        vectors = json.loads(
            (ROOT.parent / "siplite-camera-v1.1/canonical-vectors.json").read_text()
        )
        cases = {name: vectors[name] for name in ("descriptor", "binding")}
        cases.update(
            {
                name: json.loads((ROOT / f"fixtures/{name}.json").read_text())
                for name in ("offer", "proof", "commit")
            }
        )
        digests = {}
        for name, value in cases.items():
            expected = json.dumps(
                value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode("utf-8")
            raw = json.dumps(
                dict(reversed(list(value.items()))), ensure_ascii=True
            ).encode()
            result, canonical, sha = host["invoke"](lib, raw)
            assert result == 0 and canonical == expected
            assert sha == hashlib.sha256(expected).hexdigest()
            if name in ("descriptor", "binding"):
                assert sha == vectors[name + "_sha256"]
            digests[name] = sha
        proof = json.dumps(cases["proof"], separators=(",", ":")).encode()
        assert host["invoke"](lib, proof + b" " * (4096 - len(proof)))[0] == 0
        assert host["invoke"](lib, proof + b" " * (4097 - len(proof)))[0] != 0
        # The DLL is mapped by ctypes; release it before Windows temp cleanup.
        if os.name == "nt":
            import _ctypes

            _ctypes.FreeLibrary(lib._handle)
        report = {
            "firmware_commit": FIRMWARE_PIN,
            "sources_sha256": sources,
            "actual_sdk_mbedtls_sha256": True,
            "canonical_bytes_equal": True,
            "digests": digests,
            "full_message4096_4097_boundary": True,
            "device_or_video_acceptance": False,
        }
        if args.output:
            args.output.write_text(
                json.dumps(report, indent=2) + "\n", encoding="utf-8"
            )
        print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()

"""Build and publish app1 from a clean Git revision on the dedicated builder."""

import argparse
import hashlib
import json
import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path


def run(*args, capture=False):
    result = subprocess.run(
        args, check=True, text=True, stdout=subprocess.PIPE if capture else None
    )
    return result.stdout.strip() if capture else ""


def source_archive_sha256():
    archive = subprocess.Popen(["git", "archive", "HEAD"], stdout=subprocess.PIPE)
    digest = hashlib.sha256()
    assert archive.stdout is not None
    for chunk in iter(lambda: archive.stdout.read(1024 * 1024), b""):
        digest.update(chunk)
    if archive.wait() != 0:
        raise RuntimeError("git archive failed")
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--builder", default="etran-beta")
    args = parser.parse_args()

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]*", args.registry):
        raise ValueError("Invalid registry path")
    if run("git", "status", "--porcelain", capture=True):
        raise RuntimeError("Working tree is not clean")
    revision = run("git", "rev-parse", "HEAD", capture=True)
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Expected full Git SHA")
    if revision != run("git", "rev-parse", "origin/master", capture=True):
        raise RuntimeError("Release only the fetched origin/master revision")

    args.artifact_dir.mkdir(parents=True, exist_ok=True)
    record = args.artifact_dir / f"{revision}.json"
    image_repo = f"{args.registry.rstrip('/')}/app1"
    if record.exists():
        artifact = json.loads(record.read_text())
        if artifact.get("revision") != revision or not re.fullmatch(
            r"sha256:[0-9a-f]{64}", artifact.get("digest", "")
        ):
            raise ValueError("Invalid existing artifact")
        run(
            "docker",
            "buildx",
            "imagetools",
            "inspect",
            f"{image_repo}@{artifact['digest']}",
        )
        print(json.dumps(artifact, sort_keys=True))
        return

    run("uv", "sync", "--locked")
    run("uv", "run", "--locked", "pytest", "-q", "app-service/tests")
    run("docker", "buildx", "inspect", args.builder, "--bootstrap")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    tag = f"{revision}-{stamp}"
    metadata = args.artifact_dir / f"{tag}-metadata.json"
    run(
        "docker",
        "buildx",
        "build",
        "--builder",
        args.builder,
        "--platform",
        "linux/amd64",
        "--file",
        "docker-files/app-service/Dockerfile",
        "--tag",
        f"{image_repo}:{tag}",
        "--label",
        f"org.opencontainers.image.revision={revision}",
        "--build-arg",
        f"SOURCE_REVISION={revision}",
        "--build-arg",
        f"SOURCE_ARCHIVE_SHA256={source_archive_sha256()}",
        "--metadata-file",
        str(metadata),
        "--provenance=mode=min",
        "--push",
        ".",
    )
    digest = json.loads(metadata.read_text())["containerimage.digest"]
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError("Invalid registry digest")
    run("docker", "buildx", "imagetools", "inspect", f"{image_repo}@{digest}")
    artifact = {
        "component": "app1",
        "revision": revision,
        "tag": tag,
        "digest": digest,
        "built_at": stamp,
    }
    temporary = record.with_suffix(".tmp")
    with temporary.open("w") as output:
        json.dump(artifact, output, sort_keys=True)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(record)
    print(json.dumps(artifact, sort_keys=True))


if __name__ == "__main__":
    main()

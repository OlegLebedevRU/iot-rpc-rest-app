"""Scoped camera CI on the existing dedicated builder; no hosted Actions required."""

import subprocess

SCOPED = [
    "app-service/core/camera",
    "app-service/tests/core/services/test_camera_negotiated.py",
    "app-service/tests/core/remote_input/test_video_v2.py",
    "app-service/core/config.py",
    "app-service/core/crud/dev_tasks_repo.py",
    "app-service/core/crud/device_repo.py",
    "app-service/core/remote_input",
    "app-service/core/rpc_redaction.py",
    "app-service/core/schemas/device_tasks.py",
    "app-service/core/services/device_events_collect.py",
    "app-service/core/services/device_tasks.py",
    "app-service/api/api_v1/device_tasks.py",
    "app-service/api/internal_v1/device_tasks.py",
    "app-service/api/internal_v1/remote_input.py",
    "app-service/create_api_app.py",
]
COMMANDS = [
    ["uv", "sync", "--locked"],
    ["uv", "run", "--locked", "python", "contracts/siplite-camera-v1/verify.py"],
    [
        "uv",
        "run",
        "--locked",
        "pytest",
        "-q",
        "app-service/tests/core/services/test_camera_negotiated.py",
        "app-service/tests/core/services/test_ip_camera_contract.py",
        "app-service/tests/core/services/test_rpc_result_lifecycle.py",
        "app-service/tests/core/remote_input",
    ],
    ["uv", "tool", "run", "--from", "ruff==0.15.5", "ruff", "check", *SCOPED],
    ["uv", "run", "--locked", "black", "--check", *SCOPED],
]


def main():
    for command in COMMANDS:
        print("Running: " + " ".join(command), flush=True)
        subprocess.run(command, check=True)
    print("Scoped camera CI passed", flush=True)


if __name__ == "__main__":
    main()

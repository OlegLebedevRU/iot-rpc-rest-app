"""Build server-authorized bindings from fresh gauge84 and concrete descriptors."""

from core.camera.contract import REVISION, validate_definition
from core.camera.runtime_wire import digest


def configuration(camera: dict, descriptor: dict, mac: str) -> dict:
    validate_definition("hevc.schema.json", "camera_descriptor", descriptor)
    discovery = camera.get("discovery", {})
    if (
        camera.get("camera_contract_revision") != REVISION
        or descriptor["source_id"] != camera["camera_id"]
        or descriptor["tracks"][0] != camera.get("actual_track")
        or discovery.get("state") != "ready"
        or discovery.get("physical_port") != 2
        or not any(
            candidate["mac"] == mac
            and candidate["port_verified"] is True
            and candidate["auth"] == "verified"
            for candidate in discovery.get("candidates", [])
        )
    ):
        raise ValueError("camera_physical_binding_unverified")
    return {
        "descriptor": descriptor,
        "binding": {
            "source_id": descriptor["source_id"],
            "physical_camera_mac": mac,
            "path_generation": f"port2/{discovery['generation']}/{descriptor['geometry_generation']}",
            "codec": descriptor["tracks"][0]["codec"],
            "descriptor_sha256": digest(descriptor),
        },
    }

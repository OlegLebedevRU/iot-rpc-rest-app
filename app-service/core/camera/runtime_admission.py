"""Build server-authorized bindings from fresh gauge84 and concrete descriptors."""

from core.camera.contract import REVISION, validate_definition
from core.camera.native_contract import (
    SELECTED,
    SELECTED3,
    SELECTED4,
    modern_selection,
    observation_validator,
    validate11,
    validate3,
)
from core.camera.runtime_wire import digest


def configuration(
    camera: dict,
    descriptor: dict,
    mac: str,
    *,
    observation: dict | None = None,
    selection: dict | None = None,
) -> dict:
    native = selection is not None
    if native:
        if selection not in (SELECTED, SELECTED3, SELECTED4):
            raise ValueError("camera11_incomplete_revision_bundle")
        modern = modern_selection(selection)
        (validate3 if modern else validate11)(
            "descriptor" if modern else "camera_descriptor", descriptor
        )
        if modern and descriptor["source_type"] != "camera":
            raise ValueError("camera_source_type_required")
        observation_validator(selection)("camera_observation", observation)
        if modern and descriptor["profile_id"] not in {
            q["profile_id"] for q in observation["capabilities"]["quality_options"]
        }:
            raise ValueError("camera_quality_policy_unsupported")
        if (
            descriptor["source_id"] != observation["source_id"]
            or descriptor["geometry_generation"] != observation["geometry_generation"]
            or descriptor["tracks"][0] != observation["actual_track"]
        ):
            raise ValueError("camera11_observation_descriptor_mismatch")
    else:
        validate_definition("hevc.schema.json", "camera_descriptor", descriptor)
    discovery = camera.get("discovery", {})
    if (
        camera.get("camera_contract_revision") != REVISION
        or descriptor["source_id"] != camera["camera_id"]
        or (not native and descriptor["tracks"][0] != camera.get("actual_track"))
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
    result = {
        "descriptor": descriptor,
        "binding": {
            "source_id": descriptor["source_id"],
            "physical_camera_mac": mac,
            "path_generation": f"port2/{discovery['generation']}/{descriptor['geometry_generation']}",
            "codec": descriptor["tracks"][0]["codec"],
            "descriptor_sha256": digest(descriptor),
        },
    }
    if native:
        result.update(selection=selection, observation=observation)
    return result

"""Native START rollout policy, separate from physical camera mutation authority."""

from core.config import settings


def start_enabled(sn: str | None) -> bool:
    """Only authoritative, already tenant/lease-checked SNs may use test admission."""
    return settings.camera.writers_enabled or bool(
        sn and sn in settings.camera.test_start_sn_allowlist
    )

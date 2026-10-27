"""Scoped physical stream-quality activation, separate from START-only admission."""

from core.config import settings


def quality_enabled(sn: str) -> bool:
    return settings.camera.writers_enabled or sn in settings.camera.quality_sn_allowlist

from __future__ import annotations


class ArchiveError(Exception):
    """Base exception for all archive operations."""

    code: str = "ARCHIVE_OPERATION_FAILED"

    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        if code:
            self.code = code


class HotRetentionViolationError(ArchiveError):
    code = "HOT_RETENTION_VIOLATION"


class ActiveRecordsDetectedError(ArchiveError):
    code = "ACTIVE_RECORDS_DETECTED"


class CursorLagDetectedError(ArchiveError):
    code = "CURSOR_LAG_DETECTED"


class ChecksumMismatchError(ArchiveError):
    code = "CHECKSUM_MISMATCH"


class CountMismatchError(ArchiveError):
    code = "COUNT_MISMATCH"


class RestoreSampleFailedError(ArchiveError):
    code = "RESTORE_SAMPLE_FAILED"


class DiskSpaceExhaustedError(ArchiveError):
    code = "DISK_SPACE_EXHAUSTED"


class VolumeUnavailableError(ArchiveError):
    code = "VOLUME_UNAVAILABLE"


class AtomicRenameFailedError(ArchiveError):
    code = "ATOMIC_RENAME_FAILED"


class PurgeOperationFailedError(ArchiveError):
    code = "PURGE_OPERATION_FAILED"

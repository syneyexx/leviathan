"""Local backup / restore — SQLite snapshot + manifest. Not cloud sync."""

from .service import (
    BACKUP_KIND_FULL_WITH_CORPUS,
    BACKUP_KIND_METADATA_ONLY,
    RESTORE_JOURNAL_NAME,
    RESTORE_NEW_SET_ACTIVE,
    RESTORE_OLD_SET_ACTIVE,
    RESTORE_RECOVERY_REQUIRED,
    BackupError,
    BackupManifest,
    BackupService,
)

__all__ = [
    "BACKUP_KIND_FULL_WITH_CORPUS",
    "BACKUP_KIND_METADATA_ONLY",
    "RESTORE_JOURNAL_NAME",
    "RESTORE_NEW_SET_ACTIVE",
    "RESTORE_OLD_SET_ACTIVE",
    "RESTORE_RECOVERY_REQUIRED",
    "BackupError",
    "BackupManifest",
    "BackupService",
]

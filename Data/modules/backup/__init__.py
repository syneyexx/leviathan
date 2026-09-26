"""Local backup / restore — SQLite snapshot + manifest. Not cloud sync."""

from .service import (
    BACKUP_KIND_FULL_WITH_CORPUS,
    BACKUP_KIND_METADATA_ONLY,
    BackupError,
    BackupManifest,
    BackupService,
)

__all__ = [
    "BACKUP_KIND_FULL_WITH_CORPUS",
    "BACKUP_KIND_METADATA_ONLY",
    "BackupError",
    "BackupManifest",
    "BackupService",
]

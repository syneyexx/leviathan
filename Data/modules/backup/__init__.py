"""Local backup / restore — SQLite snapshot + manifest. Not cloud sync."""

from .service import BackupManifest, BackupService, BackupError

__all__ = ["BackupError", "BackupManifest", "BackupService"]

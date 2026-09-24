"""Secret / credential safety for source ingestion."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

from Data.modules.common.secrets import looks_like_secret, redact_secrets

# High-confidence secret-bearing filenames (safe-by-default quarantine).
SECRET_FILENAME_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\.env$", re.I),
    re.compile(r"^\.env\..+$", re.I),
    re.compile(r"^id_rsa$", re.I),
    re.compile(r"^id_ed25519$", re.I),
    re.compile(r"^id_ecdsa$", re.I),
    re.compile(r"^id_dsa$", re.I),
    re.compile(r".+\.pem$", re.I),
    re.compile(r".+\.key$", re.I),
    re.compile(r"^credentials\.json$", re.I),
    re.compile(r"^service-account.*\.json$", re.I),
    re.compile(r"^.*service.?account.*\.json$", re.I),
    re.compile(r"^secrets?\.(ya?ml|json|toml|env)$", re.I),
    re.compile(r"^\.aws/credentials$", re.I),
    re.compile(r"^gcloud.*\.json$", re.I),
)

_PEM_PRIVATE = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"
)


def filename_looks_secret(relative_path: str) -> bool:
    name = PurePosixPath(relative_path.replace("\\", "/")).name
    posix = relative_path.replace("\\", "/")
    for pat in SECRET_FILENAME_PATTERNS:
        if pat.match(name) or pat.match(posix):
            return True
    return False


def content_looks_like_private_key(sample: bytes | str) -> bool:
    if isinstance(sample, bytes):
        try:
            text = sample[:8192].decode("utf-8", errors="ignore")
        except Exception:  # noqa: BLE001
            return False
    else:
        text = sample[:8192]
    return bool(_PEM_PRIVATE.search(text))


def should_quarantine(
    *,
    relative_path: str,
    sample: bytes | None = None,
    policy: str = "quarantine",
) -> tuple[bool, str | None]:
    """Return (quarantine?, reason). Never returns secret contents."""
    if policy not in {"quarantine", "skip", "redact"}:
        policy = "quarantine"
    if filename_looks_secret(relative_path):
        reason = "secrets_policy:filename"
        return True, reason
    if sample and content_looks_like_private_key(sample):
        return True, "secrets_policy:private_key_pem"
    # Content-level: only private-key / high-confidence patterns for hard quarantine.
    # Avoid over-redacting normal source that mentions the word "token".
    if sample:
        try:
            text = sample[:4096].decode("utf-8", errors="ignore")
        except Exception:  # noqa: BLE001
            text = ""
        if text and looks_like_secret(text) and (
            "BEGIN" in text and "PRIVATE KEY" in text
            or text.lstrip().startswith("-----BEGIN")
        ):
            return True, "secrets_policy:secret_content"
    return False, None


def safe_error_message(message: str) -> str:
    return redact_secrets(message or "")


def sample_file_prefix(path: Path, *, max_bytes: int = 8192) -> bytes:
    try:
        with open(path, "rb") as handle:
            return handle.read(max_bytes)
    except OSError:
        return b""

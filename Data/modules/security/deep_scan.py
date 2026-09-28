"""Deep security scan — repository / dependency / integrity (EXTERNAL only).

Never echo secret values. Missing scanners => UNAVAILABLE / UNMEASURED, never PASS.
Excludes Data/HADES/ and editor/ completely.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Absolute exclusion — never traverse.
_EXCLUDED_DIR_NAMES = frozenset(
    {
        "HADES",
        "editor",
        ".git",
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        "dist",
        "build",
    }
)
_EXCLUDED_PATH_PARTS = ("Data/HADES", "Data\\HADES", "/HADES/", "\\HADES\\")

_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("generic_api_key", re.compile(r"(?i)(api[_-]?key|secret|token)\s*[:=]\s*['\"]?([A-Za-z0-9_\-]{20,})")),
    ("private_key_header", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
)

_MAX_FILES = 50_000
_MAX_BYTES = 512 * 1024 * 1024
_MAX_FILE_BYTES = 2 * 1024 * 1024
_MAX_FINDINGS = 500


@dataclass
class SecurityFinding:
    rule: str
    path: str
    line: int | None
    severity: str
    fingerprint: str
    measurement: str = "FAIL"
    detail: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "path": self.path,
            "line": self.line,
            "severity": self.severity,
            "measurement": self.measurement,
            "detail": self.detail,
            # NEVER include secret value
            "secretRedacted": True,
        }


@dataclass
class DeepAuditReport:
    scan_type: str
    started_at: float
    finished_at: float
    files_scanned: int
    bytes_scanned: int
    findings: list[SecurityFinding] = field(default_factory=list)
    omitted: list[str] = field(default_factory=list)
    measurement: str = "PASS"
    scanner_status: str = "AVAILABLE"

    def public_dict(self) -> dict[str, Any]:
        return {
            "scanType": self.scan_type,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
            "durationSeconds": max(0.0, self.finished_at - self.started_at),
            "filesScanned": self.files_scanned,
            "bytesScanned": self.bytes_scanned,
            "findings": [f.public_dict() for f in self.findings],
            "findingsBySeverity": _by_severity(self.findings),
            "omitted": list(self.omitted),
            "measurement": self.measurement,
            "scannerStatus": self.scanner_status,
            "truth": {
                "missingScannerIsNotPass": True,
                "secretValuesNeverEchoed": True,
                "hadesEditorExcluded": True,
                "staticAuditIsNotDeepScan": True,
            },
        }


def _by_severity(findings: list[SecurityFinding]) -> dict[str, int]:
    out: dict[str, int] = {}
    for f in findings:
        out[f.severity] = out.get(f.severity, 0) + 1
    return out


def _redacted_fingerprint(rule: str, path: str, line: int | None, sample: str) -> str:
    raw = f"{rule}|{path}|{line}|{hashlib.sha256(sample.encode('utf-8', errors='replace')).hexdigest()[:16]}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _is_excluded(path: Path, root: Path) -> bool:
    try:
        rel = path.resolve().relative_to(root.resolve())
    except ValueError:
        return True
    parts = rel.parts
    if any(p in _EXCLUDED_DIR_NAMES for p in parts):
        return True
    text = str(path)
    if any(token in text for token in _EXCLUDED_PATH_PARTS):
        return True
    # Explicit: never under Data/HADES or editor at repo root
    if len(parts) >= 2 and parts[0] == "Data" and parts[1] == "HADES":
        return True
    if parts and parts[0] == "editor":
        return True
    return False


def run_repo_scan(
    root: Path,
    *,
    max_files: int = _MAX_FILES,
    max_bytes: int = _MAX_BYTES,
    cancel_check: Any | None = None,
) -> DeepAuditReport:
    started = time.time()
    root = Path(root).resolve()
    findings: list[SecurityFinding] = []
    omitted: list[str] = []
    files = 0
    bytes_scanned = 0

    for dirpath, dirnames, filenames in os.walk(root):
        if callable(cancel_check) and cancel_check():
            omitted.append("cancelled")
            break
        # Prune excluded directories in-place
        dirnames[:] = [
            d
            for d in dirnames
            if d not in _EXCLUDED_DIR_NAMES
            and not _is_excluded(Path(dirpath) / d, root)
        ]
        for name in filenames:
            if files >= max_files or bytes_scanned >= max_bytes or len(findings) >= _MAX_FINDINGS:
                omitted.append("bounds_reached")
                break
            path = Path(dirpath) / name
            if _is_excluded(path, root):
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if size > _MAX_FILE_BYTES:
                omitted.append(f"oversized:{path.relative_to(root)}")
                continue
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            files += 1
            bytes_scanned += size
            for rule, pattern in _SECRET_PATTERNS:
                for match in pattern.finditer(text):
                    line = text.count("\n", 0, match.start()) + 1
                    sample = match.group(0)[:64]
                    findings.append(
                        SecurityFinding(
                            rule=rule,
                            path=str(path.relative_to(root)),
                            line=line,
                            severity="high",
                            fingerprint=_redacted_fingerprint(rule, str(path), line, sample),
                            detail="potential secret pattern (value redacted)",
                        )
                    )
                    if len(findings) >= _MAX_FINDINGS:
                        break
            if len(findings) >= _MAX_FINDINGS:
                break
        if files >= max_files or bytes_scanned >= max_bytes or "bounds_reached" in omitted:
            break

    measurement = "FAIL" if findings else "PASS"
    if "cancelled" in omitted:
        measurement = "UNMEASURED"
    return DeepAuditReport(
        scan_type="repo.scan",
        started_at=started,
        finished_at=time.time(),
        files_scanned=files,
        bytes_scanned=bytes_scanned,
        findings=findings,
        omitted=omitted,
        measurement=measurement,
    )


def run_dependency_audit(root: Path) -> DeepAuditReport:
    """Read-only dependency manifest audit — never pip/npm install or audit fix."""
    started = time.time()
    root = Path(root).resolve()
    findings: list[SecurityFinding] = []
    omitted: list[str] = []
    manifests = [
        root / "requirements.txt",
        root / "requirements-dev.txt",
        root / "package.json",
        root / "package-lock.json",
        root / "Data" / "frontend" / "package.json",
        root / "Data" / "launcher" / "package.json",
    ]
    scanned = 0
    bytes_scanned = 0
    for path in manifests:
        if not path.is_file():
            continue
        if _is_excluded(path, root):
            continue
        scanned += 1
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        bytes_scanned += len(raw)
        # Honest: without an allowlisted scanner binary we record UNMEASURED,
        # not PASS. We still confirm manifests are readable.
        omitted.append(f"scanner_unavailable_for:{path.relative_to(root)}")

    measurement = "UNMEASURED" if scanned else "NOT_APPLICABLE"
    return DeepAuditReport(
        scan_type="dependencies.audit",
        started_at=started,
        finished_at=time.time(),
        files_scanned=scanned,
        bytes_scanned=bytes_scanned,
        findings=findings,
        omitted=omitted,
        measurement=measurement,
        scanner_status="UNAVAILABLE",
    )


def run_deep_audit(root: Path, *, scope: str = "all") -> dict[str, Any]:
    scope_l = str(scope or "all").strip().lower()
    sections: dict[str, Any] = {}
    if scope_l in {"all", "repo", "repo.scan"}:
        sections["repo"] = run_repo_scan(root).public_dict()
    if scope_l in {"all", "dependencies", "deps"}:
        sections["dependencies"] = run_dependency_audit(root).public_dict()
    measurements = [s.get("measurement") for s in sections.values()]
    if "FAIL" in measurements:
        overall = "FAIL"
    elif all(m in {"PASS", "NOT_APPLICABLE"} for m in measurements) and measurements:
        overall = "PASS"
    else:
        overall = "UNMEASURED"
    return {
        "scope": scope_l,
        "sections": sections,
        "measurement": overall,
        "truth": {
            "staticInlineAuditorIsNotDeepScan": True,
            "hadesEditorExcluded": True,
            "secretsRedacted": True,
            "noAutoFix": True,
        },
    }


def write_report_artifact(report: dict[str, Any], dest: Path) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, indent=2), encoding="utf-8")
    tmp.replace(dest)
    return dest

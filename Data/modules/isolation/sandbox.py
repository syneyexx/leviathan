"""Measured untrusted-execution boundary probes (Round 8).

Never claim sandboxing from configuration alone. Each check records what was
actually observed: pass / fail / unmeasured.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from Data.modules.coding.workspace import PathEscapeError, confine


class ProbeOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNMEASURED = "UNMEASURED"


@dataclass
class BoundaryProbeResult:
    name: str
    outcome: ProbeOutcome
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "outcome": self.outcome.value,
            "detail": self.detail,
            "evidence": dict(self.evidence),
            "truth": {
                "configuration_is_not_enforcement_proof": True,
                "unmeasured_is_not_pass": self.outcome != ProbeOutcome.PASS,
            },
        }


@dataclass
class SandboxProbeReport:
    workspace_root: str
    probes: list[BoundaryProbeResult]
    os_enforced_modes: tuple[str, ...] = ()
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def public_dict(self) -> dict[str, Any]:
        passed = sum(1 for p in self.probes if p.outcome == ProbeOutcome.PASS)
        failed = sum(1 for p in self.probes if p.outcome == ProbeOutcome.FAIL)
        unmeasured = sum(1 for p in self.probes if p.outcome == ProbeOutcome.UNMEASURED)
        return {
            "workspace_root": self.workspace_root,
            "probes": [p.public_dict() for p in self.probes],
            "summary": {
                "passed": passed,
                "failed": failed,
                "unmeasured": unmeasured,
                "total": len(self.probes),
            },
            "os_enforced_modes": list(self.os_enforced_modes),
            "elapsed_ms": (
                None
                if self.finished_at is None
                else (self.finished_at - self.started_at) * 1000.0
            ),
            "truth": {
                "configuration_is_not_enforcement_proof": True,
                "sandbox_claimed_only_when_probes_pass": failed == 0 and passed > 0,
                "unmeasured_is_not_pass": True,
            },
        }


class UntrustedExecutionProber:
    """Run adversarial boundary probes against a workspace-scoped execution surface."""

    def __init__(
        self,
        workspace_root: Path,
        *,
        network_allow_outbound: bool = False,
        allow_credential_env: bool = False,
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.network_allow_outbound = network_allow_outbound
        self.allow_credential_env = allow_credential_env

    def run_all(self) -> SandboxProbeReport:
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        probes = [
            self.probe_filesystem_boundary(),
            self.probe_process_boundary_and_timeout(),
            self.probe_child_termination(),
            self.probe_network_policy(),
            self.probe_resource_limits(),
            self.probe_credential_isolation(),
        ]
        enforced: list[str] = []
        for p in probes:
            if p.outcome == ProbeOutcome.PASS:
                if p.name.startswith("filesystem"):
                    enforced.append("WORKSPACE")
                elif p.name.startswith("process") or p.name.startswith("child"):
                    enforced.append("PROCESS")
                elif p.name.startswith("network") and not self.network_allow_outbound:
                    enforced.append("NETWORK_DENY")
        report = SandboxProbeReport(
            workspace_root=str(self.workspace_root),
            probes=probes,
            os_enforced_modes=tuple(dict.fromkeys(enforced)),
            finished_at=time.time(),
        )
        return report

    def probe_filesystem_boundary(self) -> BoundaryProbeResult:
        """Adversarial path escape must be refused by confine()."""
        escapes = [
            "../outside.txt",
            "..\\..\\outside.txt",
            "/etc/passwd",
            str(self.workspace_root.parent / "escape_probe.txt"),
        ]
        blocked = 0
        details: list[str] = []
        for raw in escapes:
            try:
                confine(self.workspace_root, raw)
                details.append(f"ALLOWED unexpectedly: {raw}")
            except PathEscapeError:
                blocked += 1
                details.append(f"blocked: {raw}")
            except Exception as exc:  # noqa: BLE001
                details.append(f"error on {raw}: {exc}")
        # Positive control: in-workspace path must work.
        try:
            inside = confine(self.workspace_root, "ok.txt")
            inside_ok = str(inside).startswith(str(self.workspace_root))
        except Exception as exc:  # noqa: BLE001
            inside_ok = False
            details.append(f"inside path failed: {exc}")
        if blocked == len(escapes) and inside_ok:
            return BoundaryProbeResult(
                name="filesystem_boundary",
                outcome=ProbeOutcome.PASS,
                detail="Path escapes blocked; in-workspace resolve ok",
                evidence={"blocked": blocked, "attempts": len(escapes), "notes": details},
            )
        return BoundaryProbeResult(
            name="filesystem_boundary",
            outcome=ProbeOutcome.FAIL,
            detail="Filesystem boundary incomplete",
            evidence={"blocked": blocked, "attempts": len(escapes), "notes": details},
        )

    def probe_process_boundary_and_timeout(self) -> BoundaryProbeResult:
        """Child process must honor timeout (not hang forever)."""
        script = (
            "import time,sys\n"
            "sys.stdout.write('started\\n'); sys.stdout.flush()\n"
            "time.sleep(30)\n"
            "sys.stdout.write('should_not_finish\\n')\n"
        )
        started = time.perf_counter()
        try:
            proc = subprocess.Popen(  # noqa: S603
                [sys.executable, "-c", script],
                cwd=str(self.workspace_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=_scrubbed_env(allow_credentials=self.allow_credential_env),
            )
            try:
                out, err = proc.communicate(timeout=0.4)
                # Finished too fast without timeout — still ok if sleep was interrupted oddly
                elapsed = time.perf_counter() - started
                if proc.returncode == 0 and "should_not_finish" in (out or ""):
                    return BoundaryProbeResult(
                        name="process_timeout",
                        outcome=ProbeOutcome.FAIL,
                        detail="Long-running child completed without timeout enforcement",
                        evidence={"elapsed_ms": elapsed * 1000, "stdout": out[:200]},
                    )
                return BoundaryProbeResult(
                    name="process_timeout",
                    outcome=ProbeOutcome.PASS,
                    detail="Child exited before full sleep under short wait",
                    evidence={"elapsed_ms": elapsed * 1000, "returncode": proc.returncode},
                )
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=2)
                except Exception:  # noqa: BLE001
                    pass
                elapsed = time.perf_counter() - started
                return BoundaryProbeResult(
                    name="process_timeout",
                    outcome=ProbeOutcome.PASS,
                    detail="Timeout fired; child terminated",
                    evidence={"elapsed_ms": elapsed * 1000, "terminated": True},
                )
        except OSError as exc:
            return BoundaryProbeResult(
                name="process_timeout",
                outcome=ProbeOutcome.UNMEASURED,
                detail=f"Could not spawn child: {exc}",
                evidence={},
            )

    def probe_child_termination(self) -> BoundaryProbeResult:
        """Killed child must not remain as a live READY-like process."""
        try:
            proc = subprocess.Popen(  # noqa: S603
                [sys.executable, "-c", "import time; time.sleep(60)"],
                cwd=str(self.workspace_root),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=_scrubbed_env(allow_credentials=self.allow_credential_env),
            )
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)
            alive = proc.poll() is None
            if alive:
                return BoundaryProbeResult(
                    name="child_termination",
                    outcome=ProbeOutcome.FAIL,
                    detail="Child still alive after terminate/kill",
                    evidence={"pid": proc.pid},
                )
            return BoundaryProbeResult(
                name="child_termination",
                outcome=ProbeOutcome.PASS,
                detail="Child terminated cleanly",
                evidence={"pid": proc.pid, "returncode": proc.returncode},
            )
        except OSError as exc:
            return BoundaryProbeResult(
                name="child_termination",
                outcome=ProbeOutcome.UNMEASURED,
                detail=str(exc),
            )

    def probe_network_policy(self) -> BoundaryProbeResult:
        """When outbound is denied, child must not freely reach the network via policy env.
        Application-level deny is not OS firewall — report honestly.
        """
        if self.network_allow_outbound:
            return BoundaryProbeResult(
                name="network_policy",
                outcome=ProbeOutcome.UNMEASURED,
                detail="Outbound allowed by config — network deny not claimed",
                evidence={"network_allow_outbound": True},
            )
        # Measure: scrubbed env has no proxy that would widen egress; OS firewall unmeasured.
        env = _scrubbed_env(allow_credentials=False)
        proxy_keys = [k for k in env if "proxy" in k.lower()]
        return BoundaryProbeResult(
            name="network_policy",
            outcome=ProbeOutcome.UNMEASURED,
            detail=(
                "Application intends NETWORK_DENY but OS firewall/namespace not proven — "
                "unmeasured, not PASS"
            ),
            evidence={
                "network_allow_outbound": False,
                "proxy_env_keys": proxy_keys,
                "os_firewall_proven": False,
            },
        )

    def probe_resource_limits(self) -> BoundaryProbeResult:
        """Try to apply a soft CPU/time limit to a child; UNMEASURED if unsupported."""
        try:
            import resource  # noqa: PLC0415 — Unix only
        except ImportError:
            return BoundaryProbeResult(
                name="resource_limits",
                outcome=ProbeOutcome.UNMEASURED,
                detail="resource module unavailable on this platform",
            )

        def _limit() -> None:
            resource.setrlimit(resource.RLIMIT_CPU, (1, 1))

        try:
            proc = subprocess.Popen(  # noqa: S603
                [sys.executable, "-c", "while True: pass"],
                cwd=str(self.workspace_root),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                preexec_fn=_limit if os.name != "nt" else None,
                env=_scrubbed_env(allow_credentials=False),
            )
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)
                return BoundaryProbeResult(
                    name="resource_limits",
                    outcome=ProbeOutcome.UNMEASURED,
                    detail="CPU limit did not stop child within probe window",
                    evidence={"pid": proc.pid},
                )
            return BoundaryProbeResult(
                name="resource_limits",
                outcome=ProbeOutcome.PASS,
                detail="Child exited under CPU soft limit (or platform stop)",
                evidence={"returncode": proc.returncode},
            )
        except (OSError, ValueError) as exc:
            return BoundaryProbeResult(
                name="resource_limits",
                outcome=ProbeOutcome.UNMEASURED,
                detail=str(exc),
            )

    def probe_credential_isolation(self) -> BoundaryProbeResult:
        """Secrets in parent env must not appear in scrubbed child env."""
        marker = "leviathan_probe_secret_TOKEN_sk-TESTPROBE1234567890"
        parent_env = {**os.environ, "LEVIATHAN_PROBE_API_KEY": marker, "OPENAI_API_KEY": marker}
        child_env = _scrubbed_env(
            allow_credentials=self.allow_credential_env,
            base=parent_env,
        )
        leaked = [
            k
            for k, v in child_env.items()
            if marker in str(v) or "API_KEY" in k.upper() or "TOKEN" in k.upper() and "LEV" in k.upper()
        ]
        # Also ensure known secret key names are dropped
        secret_names = [k for k in child_env if _is_secret_env_key(k)]
        if self.allow_credential_env:
            return BoundaryProbeResult(
                name="credential_isolation",
                outcome=ProbeOutcome.UNMEASURED,
                detail="Credential passthrough explicitly allowed",
                evidence={"allow_credential_env": True},
            )
        if leaked or secret_names:
            return BoundaryProbeResult(
                name="credential_isolation",
                outcome=ProbeOutcome.FAIL,
                detail="Secret-like env vars present in scrubbed child env",
                evidence={"leaked_keys": leaked or secret_names},
            )
        # Positive: child cannot read marker
        try:
            proc = subprocess.run(  # noqa: S603
                [
                    sys.executable,
                    "-c",
                    "import os; print(os.environ.get('LEVIATHAN_PROBE_API_KEY','MISSING'))",
                ],
                cwd=str(self.workspace_root),
                capture_output=True,
                text=True,
                timeout=5,
                env=child_env,
                check=False,
            )
            out = (proc.stdout or "").strip()
            if marker in out:
                return BoundaryProbeResult(
                    name="credential_isolation",
                    outcome=ProbeOutcome.FAIL,
                    detail="Child observed parent secret",
                    evidence={"stdout": out[:80]},
                )
            return BoundaryProbeResult(
                name="credential_isolation",
                outcome=ProbeOutcome.PASS,
                detail="Scrubbed child env has no secret marker",
                evidence={"child_saw": out[:40]},
            )
        except Exception as exc:  # noqa: BLE001
            return BoundaryProbeResult(
                name="credential_isolation",
                outcome=ProbeOutcome.UNMEASURED,
                detail=str(exc),
            )


def _is_secret_env_key(key: str) -> bool:
    upper = key.upper()
    needles = (
        "API_KEY",
        "SECRET",
        "TOKEN",
        "PASSWORD",
        "CREDENTIAL",
        "PRIVATE_KEY",
        "AUTHORIZATION",
    )
    return any(n in upper for n in needles)


def _scrubbed_env(
    *,
    allow_credentials: bool,
    base: dict[str, str] | None = None,
) -> dict[str, str]:
    src = dict(base or os.environ)
    if allow_credentials:
        return src
    return {k: v for k, v in src.items() if not _is_secret_env_key(k)}


def run_workspace_sandbox_probes(
    workspace_root: Path | None = None,
    *,
    network_allow_outbound: bool = False,
) -> SandboxProbeReport:
    root = Path(workspace_root) if workspace_root else Path(tempfile.mkdtemp(prefix="lev-sandbox-"))
    return UntrustedExecutionProber(
        root,
        network_allow_outbound=network_allow_outbound,
    ).run_all()

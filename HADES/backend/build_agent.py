"""Isolated build/patch workflow with deterministic file ops and verification."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from database import new_id, utc_now
from path_boundary import join_within_root, path_within_root, run_dir, validate_run_id

ALLOWED_TEST_COMMANDS = {
    "pytest": [sys.executable, "-m", "pytest"],
    "unittest": [sys.executable, "-m", "unittest"],
    "npm_test": ["npm", "test", "--"],
    # Explicit safe runners — never shell=True; never model-authored argv.
    "go_test": ["go", "test", "./..."],
    "cargo_test": ["cargo", "test", "--", "--nocapture"],
    "ctest": ["ctest", "--output-on-failure"],
}

SKIP_BUILD_PARTS = {".git", "__pycache__", "node_modules", ".venv", ".tox"}


def resolve_repair_attempt_ceiling(max_attempts: int, configured: Any) -> int:
    """Single authoritative test+repair iteration ceiling.

    Caller ``max_attempts`` is the requested upper bound. A finite control-plane
    setting may tighten it, never silently expand past the caller bound.
    ``max_attempts <= 0`` means one verification pass and no repairs.
    """
    caller = int(max_attempts)
    if configured is None:
        return 1 if caller <= 0 else max(1, caller)
    cfg = int(configured)
    if caller <= 0:
        return 1
    return max(1, min(caller, cfg))


def _setting(name: str, fallback: Any) -> Any:
    try:
        from control.service import resolve_setting

        return resolve_setting(name, default=fallback)
    except Exception:
        return fallback


def _is_skippable_rel(rel: str) -> bool:
    parts = Path(rel).parts
    if any(part in SKIP_BUILD_PARTS for part in parts):
        return True
    return Path(rel).suffix.lower() in {".pyc", ".pyo", ".pyd"}


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relpath(root: Path, raw: str) -> Path:
    return join_within_root(root, raw)


@dataclass
class FileEdit:
    path: str
    action: str  # create | replace | patch_lines | unified_diff | rename
    content: str | None = None
    old_content: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    from_path: str | None = None
    base_hash: str | None = None


@dataclass
class BuildRunResult:
    run_id: str
    status: str
    baseline_commit: str | None
    baseline_hashes: dict[str, str]
    work_root: str
    planned_edits: list[dict[str, Any]]
    applied_edits: list[dict[str, Any]]
    diff_text: str
    commands: list[dict[str, Any]] = field(default_factory=list)
    test_results: list[dict[str, Any]] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    patch_text: str = ""
    report: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    loop_timeline: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "baseline_commit": self.baseline_commit,
            "baseline_hashes": self.baseline_hashes,
            "work_root": self.work_root,
            "planned_edits": self.planned_edits,
            "applied_edits": self.applied_edits,
            "diff_text": self.diff_text,
            "commands": self.commands,
            "test_results": self.test_results,
            "conflicts": self.conflicts,
            "patch_text": self.patch_text,
            "report": self.report,
            "error": self.error,
            "loop_timeline": self.loop_timeline,
        }


def plan_multi_file_edits(edits: list[FileEdit], *, goal: str = "") -> dict[str, Any]:
    """Composer multi-file plan preview: reviewable file list before any apply."""
    files: list[dict[str, Any]] = []
    risks: list[str] = []
    for edit in edits:
        path = (edit.path or "").replace("\\", "/").strip()
        if not path:
            raise ValueError("Edit zonder pad is niet toegestaan.")
        if path.startswith("/") or path.startswith("..") or "/../" in f"/{path}/":
            raise ValueError(f"Onveilig pad in plan: {edit.path}")
        entry = {
            "path": path,
            "action": edit.action,
            "has_content": edit.content is not None,
            "start_line": edit.start_line,
            "end_line": edit.end_line,
            "bytes": len((edit.content or "").encode("utf-8")),
        }
        files.append(entry)
        if edit.action == "replace" and edit.old_content is None:
            risks.append(f"{path}: replace zonder old_content — conflictcheck bij apply blijft hash-gebaseerd.")
        if edit.action == "rename":
            risks.append(f"{path}: rename in worktree — bronbestand wordt niet stil uit de user workspace verwijderd bij apply.")
        if edit.action == "create":
            risks.append(f"{path}: nieuw bestand — faalt als het al bestaat in de worktree.")
    unique_paths = sorted({item["path"] for item in files})
    return {
        "goal": (goal or "").strip() or None,
        "status": "planned",
        "file_count": len(unique_paths),
        "edit_count": len(files),
        "files": files,
        "unique_paths": unique_paths,
        "risks": risks,
        "approval_required": True,
        "note": "Plan alleen — bronrepo blijft intact tot expliciete build-run + apply.",
    }


class BuildAgentService:
    """Prepare patches in an isolated copy/worktree; never mutate source until explicit apply."""

    def __init__(self, workspace_root: Path, artifact_service: Any | None = None) -> None:
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.artifact_service = artifact_service
        self.runs_root = self.workspace_root / "build_runs"
        self.runs_root.mkdir(parents=True, exist_ok=True)

    def _git(self, repo: Path, *args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=str(repo),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            check=check,
        )

    def detect_baseline(self, repo: Path) -> tuple[str | None, dict[str, str]]:
        commit = None
        if (repo / ".git").exists() or self._git(repo, "rev-parse", "--is-inside-work-tree").returncode == 0:
            head = self._git(repo, "rev-parse", "HEAD")
            if head.returncode == 0:
                commit = head.stdout.strip()
        hashes: dict[str, str] = {}
        repo_root = Path(repo).resolve()
        for path in sorted(repo.rglob("*")):
            if not path.is_file():
                continue
            if not path_within_root(path, repo_root):
                continue
            rel = path.relative_to(repo).as_posix()
            if _is_skippable_rel(rel):
                continue
            hashes[rel] = _sha256_file(path)
        return commit, hashes

    def prepare_workspace(self, source_repo: Path, *, scope_globs: list[str] | None = None) -> tuple[Path, str | None, dict[str, str]]:
        source = Path(source_repo).expanduser().resolve()
        if not source.is_dir():
            raise FileNotFoundError(f"Bronrepo niet gevonden: {source}")
        run_id = new_id("build")
        work = self.runs_root / run_id / "work"
        work.parent.mkdir(parents=True, exist_ok=True)
        baseline_commit, hashes = self.detect_baseline(source)

        # Prefer git worktree when clean isolation is available; fall back to copy.
        used_worktree = False
        if baseline_commit:
            status = self._git(source, "status", "--porcelain")
            # Protect uncommitted user work: still create detached worktree from HEAD without touching dirty files.
            proc = self._git(source, "worktree", "add", "--detach", str(work), "HEAD")
            used_worktree = proc.returncode == 0
        if not used_worktree:
            pattern_ignore = shutil.ignore_patterns(
                ".git", "__pycache__", "node_modules", ".venv", "*.pyc", "*.pyo"
            )

            def _ignore(directory: str, names: list[str]) -> set[str]:
                ignored = set(pattern_ignore(directory, names))
                dir_path = Path(directory)
                for name in names:
                    if name in ignored:
                        continue
                    candidate = dir_path / name
                    # Do not materialize symlink targets that escape the source root.
                    if candidate.is_symlink() and not path_within_root(candidate, source):
                        ignored.add(name)
                return ignored

            shutil.copytree(source, work, ignore=_ignore)
        meta = {
            "run_id": run_id,
            "source": str(source),
            "work_root": str(work),
            "baseline_commit": baseline_commit,
            "baseline_hashes": hashes,
            "scope_globs": scope_globs or ["**/*"],
            "created_at": utc_now(),
            "isolation": "git_worktree" if used_worktree else "copy",
        }
        (work.parent / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return work, baseline_commit, hashes

    def apply_edits_in_workspace(self, work_root: Path, edits: list[FileEdit]) -> tuple[list[dict[str, Any]], str]:
        applied: list[dict[str, Any]] = []
        for edit in edits:
            target = _safe_relpath(work_root, edit.path)
            action = edit.action
            if action == "create":
                if target.exists():
                    raise FileExistsError(f"Bestand bestaat al: {edit.path}")
                if edit.content is None:
                    raise ValueError("create vereist content")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(edit.content, encoding="utf-8")
            elif action == "replace":
                if edit.content is None:
                    raise ValueError("replace vereist content")
                if edit.old_content is not None and target.exists():
                    current = target.read_text(encoding="utf-8")
                    if current != edit.old_content:
                        raise RuntimeError(f"Baseline-hash conflict voor {edit.path}")
                if edit.base_hash and target.exists():
                    from coding_edits import sha256_text

                    current = target.read_text(encoding="utf-8")
                    if sha256_text(current) != edit.base_hash:
                        raise RuntimeError(f"Stale baseline hash voor {edit.path}")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(edit.content, encoding="utf-8")
            elif action == "patch_lines":
                if edit.content is None or edit.start_line is None or edit.end_line is None:
                    raise ValueError("patch_lines vereist content, start_line en end_line")
                from coding_edits import patch_lines as _patch_lines

                original = target.read_text(encoding="utf-8") if target.exists() else ""
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(_patch_lines(original, edit.start_line, edit.end_line, edit.content), encoding="utf-8")
            elif action == "unified_diff":
                if not edit.content:
                    raise ValueError("unified_diff vereist content")
                from coding_edits import apply_unified_diff_to_text

                original = target.read_text(encoding="utf-8") if target.exists() else ""
                if edit.old_content is not None and original != edit.old_content:
                    raise RuntimeError(f"Baseline-hash conflict voor {edit.path}")
                if edit.base_hash:
                    from coding_edits import sha256_text

                    if sha256_text(original) != edit.base_hash:
                        raise RuntimeError(f"Stale baseline hash voor {edit.path}")
                patched = apply_unified_diff_to_text(original, edit.content)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(patched, encoding="utf-8")
            elif action == "rename":
                src_rel = edit.from_path or edit.old_content
                if not src_rel:
                    raise ValueError("rename vereist from_path")
                src = _safe_relpath(work_root, str(src_rel))
                if not src.is_file():
                    raise FileNotFoundError(f"rename bron ontbreekt: {src_rel}")
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    raise FileExistsError(f"rename doel bestaat al: {edit.path}")
                shutil.copy2(src, target)
                src.unlink()
            else:
                raise ValueError(f"Onbekende edit-actie: {action}")
            applied.append({
                "path": edit.path,
                "action": action,
                "hash": _sha256_file(target),
                "status": "applied",
            })
        diff = self._unified_diff(work_root)
        return applied, diff

    def _unified_diff(self, work_root: Path) -> str:
        meta_path = work_root.parent / "meta.json"
        if not meta_path.exists():
            return ""
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        source = Path(meta["source"])
        from coding_edits import make_worktree_unified_diff

        return make_worktree_unified_diff(
            work_root,
            baseline_hashes=dict(meta.get("baseline_hashes") or {}),
            source_root=source,
        )

    def run_tests(self, work_root: Path, suite: str = "unittest", extra_args: list[str] | None = None) -> dict[str, Any]:
        if suite not in ALLOWED_TEST_COMMANDS:
            raise ValueError(f"Testsuite niet toegestaan: {suite}")
        command = list(ALLOWED_TEST_COMMANDS[suite])
        work = Path(work_root).resolve()
        if extra_args:
            # Only allow simple relative targets inside the worktree, never shell strings.
            for arg in extra_args:
                if arg.startswith("-"):
                    command.append(arg)
                    continue
                looks_like_path = "/" in arg or "\\" in arg or arg.endswith((".py", ".ts", ".js", ".tsx", ".jsx"))
                if looks_like_path:
                    join_within_root(work, arg)
                    command.append(arg)
                else:
                    raise ValueError(f"Ongeldig testargument: {arg}")
        # Drop stale bytecode so repair waves are actually reloaded.
        for cache_dir in work.rglob("__pycache__"):
            if cache_dir.is_dir():
                shutil.rmtree(cache_dir, ignore_errors=True)
        started = utc_now()
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        proc = subprocess.run(
            command,
            cwd=str(work),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            timeout=int(_setting("build.test_timeout_seconds", 180) or 180),
            env=env,
        )
        return {
            "suite": suite,
            "command": command,
            "exit_code": proc.returncode,
            "stdout": proc.stdout[-20_000:],
            "stderr": proc.stderr[-20_000:],
            "status": "passed" if proc.returncode == 0 else "failed",
            "started_at": started,
            "finished_at": utc_now(),
            "executed": True,
        }

    def _run_root(self, run_id: str) -> Path:
        return run_dir(self.runs_root, run_id)

    def _changed_files(self, run_id: str) -> list[dict[str, Any]]:
        run_root = self._run_root(run_id)
        meta = json.loads((run_root / "meta.json").read_text(encoding="utf-8"))
        work = Path(meta["work_root"]).resolve()
        baseline: dict[str, str] = meta.get("baseline_hashes") or {}
        changed: list[dict[str, Any]] = []
        seen: set[str] = set()
        for path in work.rglob("*"):
            if not path.is_file():
                continue
            if not path_within_root(path, work):
                continue
            rel = path.relative_to(work).as_posix()
            if _is_skippable_rel(rel):
                continue
            digest = _sha256_file(path)
            old = baseline.get(rel)
            if old is None:
                changed.append({"path": rel, "change": "added", "hash": digest})
                seen.add(rel)
            elif old != digest:
                changed.append({"path": rel, "change": "modified", "hash": digest, "baseline_hash": old})
                seen.add(rel)
        for rel, old in baseline.items():
            if rel in seen:
                continue
            work_file = work / rel
            if not work_file.exists():
                # Deletions are not auto-applied; surface for review only.
                changed.append({"path": rel, "change": "deleted_in_worktree", "baseline_hash": old, "applyable": False})
        return changed

    def preview_apply(self, run_id: str) -> dict[str, Any]:
        validate_run_id(run_id)
        meta_path = self._run_root(run_id) / "meta.json"
        if not meta_path.exists():
            raise FileNotFoundError(f"Build-run niet gevonden: {run_id}")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        conflicts = self.check_apply_conflicts(run_id)
        files = [item for item in self._changed_files(run_id) if item.get("change") in {"added", "modified"}]
        return {
            "run_id": run_id,
            "source": meta.get("source"),
            "work_root": meta.get("work_root"),
            "files": files,
            "file_count": len(files),
            "conflicts": conflicts,
            "can_apply": not conflicts and bool(files),
            "approval_required": True,
            "note": "Alleen gewijzigde/nieuwe bestanden worden gekopieerd; verwijderingen worden niet stil toegepast.",
        }

    def run_repair_loop(
        self,
        source_repo: Path,
        edits: list[FileEdit],
        *,
        test_suite: str = "unittest",
        test_args: list[str] | None = None,
        max_attempts: int = 2,
        repair_waves: list[list[FileEdit]] | None = None,
        goal: str = "",
        repair_generator: Any | None = None,
        attempt_ceiling: int | None = None,
    ) -> BuildRunResult:
        work, baseline_commit, hashes = self.prepare_workspace(source_repo)
        run_id = work.parent.name
        plan = plan_multi_file_edits(edits, goal=goal) if edits else {
            "goal": (goal or "").strip() or None,
            "status": "planned",
            "file_count": 0,
            "edit_count": 0,
            "files": [],
            "unique_paths": [],
            "risks": [],
            "approval_required": True,
            "note": "Geen edits — alleen testloop in geïsoleerde worktree.",
        }
        planned = [{"path": e.path, "action": e.action, "status": "planned"} for e in edits]
        result = BuildRunResult(
            run_id=run_id,
            status="running",
            baseline_commit=baseline_commit,
            baseline_hashes=hashes,
            work_root=str(work),
            planned_edits=planned,
            applied_edits=[],
            diff_text="",
        )
        repair_signatures: list[str] = []
        result.loop_timeline.append({
            "attempt": 0,
            "phase": "plan",
            "status": "ok",
            "summary": f"{plan['edit_count']} edit(s) over {plan['file_count']} bestand(en)",
            "detail": plan,
        })
        try:
            if edits:
                applied, diff = self.apply_edits_in_workspace(work, edits)
                result.applied_edits = applied
                result.diff_text = diff
                result.patch_text = diff
                result.loop_timeline.append({
                    "attempt": 1,
                    "phase": "apply_edits",
                    "status": "ok",
                    "summary": f"{len(applied)} edit(s) toegepast in worktree",
                    "files": [item.get("path") for item in applied],
                })
            else:
                result.loop_timeline.append({
                    "attempt": 1,
                    "phase": "apply_edits",
                    "status": "skipped",
                    "summary": "Geen initiële edits",
                })

            attempts = 0
            waves = repair_waves or []
            configured_attempts = _setting("build.max_repair_attempts", max_attempts)
            resolved_ceiling = resolve_repair_attempt_ceiling(max_attempts, configured_attempts)
            if attempt_ceiling is not None:
                resolved_ceiling = max(1, min(resolved_ceiling, int(attempt_ceiling)))
            while attempts < resolved_ceiling:
                attempts += 1
                test = self.run_tests(work, suite=test_suite, extra_args=test_args)
                result.commands.append({
                    "command": test["command"],
                    "exit_code": test["exit_code"],
                    "status": "executed",
                    "outcome": test["status"],
                    "attempt": attempts,
                })
                result.test_results.append(test)
                result.loop_timeline.append({
                    "attempt": attempts,
                    "phase": "test",
                    "status": test["status"],
                    "summary": f"{test_suite} → {test['status']} (exit {test['exit_code']})",
                    "exit_code": test["exit_code"],
                })
                if test["status"] == "passed":
                    result.status = "verified"
                    break

                logs = f"{test.get('stdout') or ''}\n{test.get('stderr') or ''}"
                diagnosis: dict[str, Any] | None = None
                try:
                    from debug_agent import diagnose_failure

                    diagnosis = diagnose_failure(logs=logs, failing_test="")
                except Exception as diag_exc:
                    diagnosis = {"status": "unavailable", "error": str(diag_exc)}
                try:
                    from coding_failures import normalize_test_result

                    structured = normalize_test_result(
                        test,
                        related_changes=[e.get("path") for e in result.applied_edits if e.get("path")],
                    ).to_dict()
                    test["structured_failure"] = structured
                    if diagnosis is not None:
                        diagnosis["structured_failure"] = structured
                except Exception:
                    pass
                result.loop_timeline.append({
                    "attempt": attempts,
                    "phase": "diagnose",
                    "status": str((diagnosis or {}).get("status") or "unknown"),
                    "summary": (
                        f"{len((diagnosis or {}).get('findings') or [])} finding(s); "
                        f"{len((diagnosis or {}).get('suggestions') or [])} suggestie(s)"
                    ),
                    "diagnosis": diagnosis,
                })

                if attempts >= resolved_ceiling:
                    result.status = "tests_failed"
                    result.error = "Tests faalden; herstelpogingen begrensd. Falingtests worden niet verwijderd."
                    break

                # Next attempt: apply an explicit repair wave when provided (test→fail→fix→retest).
                wave_index = attempts - 1
                repair_edits: list[FileEdit] = []
                repair_meta: dict[str, Any] | None = None
                if wave_index < len(waves) and waves[wave_index]:
                    repair_edits = waves[wave_index]
                elif callable(repair_generator):
                    try:
                        generated = repair_generator(work, diagnosis, test, attempts)
                        if isinstance(generated, tuple) and len(generated) == 2:
                            repair_edits, repair_meta = generated
                        else:
                            repair_edits = list(generated or [])
                    except Exception as gen_exc:
                        repair_meta = {"error": str(gen_exc)}
                        repair_edits = []
                if repair_edits:
                    # Detect identical repeat patches without new information.
                    sig = json.dumps(
                        [{"path": e.path, "action": e.action, "content": e.content} for e in repair_edits],
                        sort_keys=True,
                    )
                    prior_sigs = repair_signatures
                    if sig in prior_sigs:
                        result.loop_timeline.append({
                            "attempt": attempts + 1,
                            "phase": "repair",
                            "status": "blocked",
                            "summary": "Herhaalde patch zonder nieuwe informatie — stop eerlijk.",
                            "repair_meta": repair_meta,
                        })
                        result.status = "tests_failed"
                        result.error = (
                            "Repair herhaalde dezelfde patch zonder nieuwe diagnostiek. "
                            "Kwaliteitscontroles worden niet verzwakt om groen te worden."
                        )
                        break
                    prior_sigs.append(sig)
                    repaired, diff = self.apply_edits_in_workspace(work, repair_edits)
                    result.applied_edits.extend(repaired)
                    result.diff_text = diff
                    result.patch_text = diff
                    result.loop_timeline.append({
                        "attempt": attempts + 1,
                        "phase": "repair",
                        "status": "applied",
                        "summary": (
                            f"Repair wave {wave_index + 1}: {len(repaired)} edit(s)"
                            if wave_index < len(waves) and waves[wave_index]
                            else f"Agent repair: {len(repaired)} edit(s)"
                        ),
                        "files": [item.get("path") for item in repaired],
                        "repair_meta": repair_meta,
                    })
                else:
                    result.loop_timeline.append({
                        "attempt": attempts + 1,
                        "phase": "repair",
                        "status": "blocked",
                        "summary": (
                            "Geen repair wave voor deze poging — lever repair_waves, "
                            "schakel auto-repair in, of pas edits handmatig aan. "
                            "Zelfde failing suite opnieuw draaien zonder fix is geen herstel."
                        ),
                        "repair_meta": repair_meta,
                    })
                    result.status = "tests_failed"
                    result.error = (
                        "Tests faalden en er was geen repair voor de volgende poging. "
                        "Gebruik diagnose-suggesties, auto-repair, of expliciete repair_waves."
                    )
                    break

            if result.status == "running":
                last = result.test_results[-1] if result.test_results else {}
                if str(last.get("status") or "") == "passed":
                    result.status = "verified"
                else:
                    result.status = "tests_failed"
                    result.error = result.error or (
                        "Tests faalden; herstelpogingen begrensd. Falingtests worden niet verwijderd."
                    )

            result.report = {
                "attempts": attempts,
                "attempt_ceiling": resolved_ceiling,
                "verified": result.status == "verified",
                "source_intact": True,
                "apply_requires_approval": True,
                "composer_plan": plan,
                "loop_phases": [item.get("phase") for item in result.loop_timeline],
                "what_broke": self._extract_what_broke(result.test_results),
            }
            self._persist_result(result)
            self._export_artifacts(result)
            return result
        except Exception as exc:
            result.status = "failed"
            result.error = str(exc)
            result.loop_timeline.append({
                "attempt": 0,
                "phase": "error",
                "status": "failed",
                "summary": str(exc),
            })
            result.report = {
                "verified": False,
                "source_intact": True,
                "apply_requires_approval": True,
                "composer_plan": plan,
                "what_broke": [],
            }
            try:
                self._persist_result(result)
            except OSError as persist_exc:
                result.error = f"{result.error or 'build_failed'}; result_persistence_failed:{persist_exc}"
            return result

    @staticmethod
    def _extract_what_broke(test_results: list[dict[str, Any]]) -> list[str]:
        broken: list[str] = []
        for test in test_results:
            if test.get("status") == "passed":
                continue
            blob = f"{test.get('stdout') or ''}\n{test.get('stderr') or ''}"
            found_for_test = False
            for line in blob.splitlines():
                stripped = line.strip()
                if stripped.startswith("FAIL:") or stripped.startswith("ERROR:") or " FAILED" in stripped:
                    broken.append(stripped[:240])
                    found_for_test = True
            if not found_for_test:
                broken.append(f"{test.get('suite')} exit {test.get('exit_code')}")
        seen: set[str] = set()
        out: list[str] = []
        for item in broken:
            if item in seen:
                continue
            seen.add(item)
            out.append(item)
        return out[:40]

    def _persist_result(self, result: BuildRunResult) -> None:
        path = self.runs_root / result.run_id / "result.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def get_run(self, run_id: str) -> dict[str, Any]:
        run_root = self._run_root(run_id)
        path = run_root / "result.json"
        meta_path = run_root / "meta.json"
        if not meta_path.exists():
            raise FileNotFoundError(f"Build-run niet gevonden: {run_id}")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        payload: dict[str, Any] = {"run_id": run_id, "meta": meta}
        if path.exists():
            payload["result"] = json.loads(path.read_text(encoding="utf-8"))
        payload["preview"] = self.preview_apply(run_id)
        return payload

    def check_apply_conflicts(self, run_id: str) -> list[dict[str, Any]]:
        run_root = self._run_root(run_id)
        meta = json.loads((run_root / "meta.json").read_text(encoding="utf-8"))
        source = Path(meta["source"])
        conflicts = []
        for item in self._changed_files(run_id):
            if item.get("change") not in {"added", "modified"}:
                continue
            rel = str(item["path"])
            expected = (meta.get("baseline_hashes") or {}).get(rel)
            path = source / rel
            if expected is None:
                # New file in worktree: conflict if source already has a different file.
                if path.exists():
                    conflicts.append({
                        "path": rel,
                        "reason": "Nieuw bestand in patch bestaat al in bronrepo.",
                        "actual": _sha256_file(path),
                    })
                continue
            if not path.exists():
                conflicts.append({"path": rel, "reason": "Bronbestand ontbreekt nu."})
                continue
            actual = _sha256_file(path)
            if actual != expected:
                conflicts.append({
                    "path": rel,
                    "reason": "Bestand is ondertussen gewijzigd sinds baseline.",
                    "expected": expected,
                    "actual": actual,
                })
        return conflicts

    def apply_to_source(self, run_id: str, *, approved: bool) -> dict[str, Any]:
        if not approved:
            raise PermissionError("Toepassen op gebruikersworkspace vereist expliciete goedkeuring.")
        run_root = self._run_root(run_id)
        meta = json.loads((run_root / "meta.json").read_text(encoding="utf-8"))
        conflicts = self.check_apply_conflicts(run_id)
        if conflicts:
            return {"status": "conflict", "conflicts": conflicts, "applied": False}
        source = Path(meta["source"])
        work = Path(meta["work_root"])
        backup_root = run_root / "pre_apply_backup"
        backup_root.mkdir(parents=True, exist_ok=True)
        applied_files: list[str] = []
        added_files: list[dict[str, Any]] = []
        modified_files: list[dict[str, Any]] = []
        skipped: list[str] = []
        applied_steps: list[dict[str, Any]] = []

        def _rollback() -> None:
            for step in reversed(applied_steps):
                dest = Path(step["dest"])
                backup = Path(step["backup"]) if step.get("backup") else None
                if step.get("existed_before") and backup is not None and backup.is_file():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(backup, dest)
                elif not step.get("existed_before") and dest.is_file():
                    if _sha256_file(dest) == step.get("hash"):
                        dest.unlink(missing_ok=True)

        try:
            for item in self._changed_files(run_id):
                if item.get("change") not in {"added", "modified"}:
                    skipped.append(str(item.get("path")))
                    continue
                rel = Path(str(item["path"]))
                path = work / rel
                if not path.is_file() or not path_within_root(path, work):
                    continue
                dest = source / rel
                existed_before = dest.exists()
                backup: Path | None = None
                if existed_before:
                    backup = backup_root / rel
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(dest, backup)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, dest)
                digest = str(item.get("hash") or _sha256_file(path))
                step = {
                    "path": rel.as_posix(),
                    "dest": str(dest),
                    "backup": str(backup) if backup is not None else None,
                    "existed_before": existed_before,
                    "hash": digest,
                    "change": item.get("change"),
                }
                applied_steps.append(step)
                applied_files.append(rel.as_posix())
                if existed_before:
                    modified_files.append({"path": rel.as_posix(), "hash": digest})
                else:
                    added_files.append({"path": rel.as_posix(), "hash": digest})
        except Exception as exc:
            _rollback()
            failure = {
                "status": "failed",
                "applied": False,
                "files": [],
                "added_files": [],
                "modified_files": [],
                "skipped_non_applyable": skipped,
                "backup_root": str(backup_root),
                "conflicts": [],
                "file_count": 0,
                "error": f"{type(exc).__name__}: {exc}",
                "rolled_back": True,
                "message": "Apply afgebroken; eerdere mutaties in deze transactie zijn teruggedraaid.",
            }
            try:
                (run_root / "apply.json").write_text(
                    json.dumps(failure, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except OSError:
                pass
            return failure

        if not applied_files:
            outcome = {
                "status": "noop",
                "applied": False,
                "files": [],
                "added_files": [],
                "modified_files": [],
                "skipped_non_applyable": skipped,
                "backup_root": str(backup_root),
                "conflicts": [],
                "file_count": 0,
                "error": "no_files_applied",
                "message": "Geen bestanden toegepast (lege of niet-applybare diff).",
            }
        else:
            outcome = {
                "status": "applied",
                "applied": True,
                "files": applied_files,
                "added_files": added_files,
                "modified_files": modified_files,
                "skipped_non_applyable": skipped,
                "backup_root": str(backup_root),
                "conflicts": [],
                "file_count": len(applied_files),
            }
        try:
            (run_root / "apply.json").write_text(
                json.dumps(outcome, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass
        return outcome

    def restore_backup(self, run_id: str) -> dict[str, Any]:
        run_root = self._run_root(run_id)
        meta = json.loads((run_root / "meta.json").read_text(encoding="utf-8"))
        source = Path(meta["source"])
        work = Path(meta["work_root"])
        backup_root = run_root / "pre_apply_backup"
        apply_meta: dict[str, Any] = {}
        apply_path = run_root / "apply.json"
        if apply_path.is_file():
            try:
                apply_meta = json.loads(apply_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                apply_meta = {}
        if not backup_root.exists() and not apply_meta.get("added_files"):
            raise FileNotFoundError("Geen pre-apply backup gevonden.")
        restored = []
        removed = []
        if backup_root.exists():
            for path in backup_root.rglob("*"):
                if not path.is_file():
                    continue
                rel = path.relative_to(backup_root)
                dest = source / rel
                work_file = work / rel
                if dest.exists() and work_file.exists():
                    if _sha256_file(dest) != _sha256_file(work_file):
                        continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, dest)
                restored.append(rel.as_posix())
        for item in apply_meta.get("added_files") or []:
            rel = str(item.get("path") or "")
            if not rel:
                continue
            dest = source / rel
            work_file = work / rel
            applied_hash = str(item.get("hash") or "")
            if not dest.is_file():
                continue
            current_hash = _sha256_file(dest)
            if applied_hash and current_hash != applied_hash:
                continue
            if work_file.is_file() and current_hash != _sha256_file(work_file):
                continue
            dest.unlink(missing_ok=True)
            removed.append(rel)
        if not restored and not removed:
            return {
                "status": "noop",
                "restored": False,
                "files": [],
                "removed_added_files": [],
                "file_count": 0,
                "error": "no_files_restored",
                "message": "Geen bestanden hersteld (lege backup of alle bestanden overgeslagen).",
            }
        return {
            "status": "restored",
            "restored": True,
            "files": restored,
            "removed_added_files": removed,
            "file_count": len(restored) + len(removed),
        }

    def _export_artifacts(self, result: BuildRunResult) -> None:
        if not self.artifact_service:
            return
        try:
            self.artifact_service.create_text_result(
                name=f"build-{result.run_id}.patch.diff",
                text=result.patch_text or result.diff_text or "",
                kind="generated",
                mime_type="text/plain",
                metadata={"build_run_id": result.run_id, "type": "patch"},
            )
            self.artifact_service.create_text_result(
                name=f"build-{result.run_id}.report.json",
                text=json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
                kind="generated",
                mime_type="application/json",
                metadata={"build_run_id": result.run_id, "type": "verification_report"},
            )
        except Exception:
            # Artifact export must not hide the build result itself.
            pass

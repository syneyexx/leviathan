"""Backend Coding preflight evaluation (shared with UI messaging)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from coding_failure_reasons import human_reason_nl
from coding_model_resolve import resolve_coding_model
from coding_task_intent import classify_coding_task_intent


def evaluate_coding_preflight(
    *,
    source_repo: str | None,
    goal: str | None = None,
    has_manual_edits: bool = False,
    backend_reachable: bool = True,
    lm_reachable: bool | None = None,
    active_model_id: str | None = None,
    profile_model_id: str | None = None,
    inventory: list[Any] | None = None,
    use_omniroute: bool = False,
    omniroute_usable: bool | None = None,
    autonomy_profile: str | None = None,
    test_suite: str | None = None,
    subprocess_approval_required: bool = True,
    subprocess_approved: bool = False,
) -> dict[str, Any]:
    """Return preflight readiness for a natural-language Coding mutation task."""
    blockers: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    repo = (source_repo or "").strip()
    if not repo:
        blockers.append({"code": "source_repo_missing", "message": "Vul een source_repo pad in."})
    else:
        try:
            path = Path(repo).expanduser()
            if path.exists() and not path.is_dir():
                blockers.append({"code": "source_repo_not_dir", "message": "Source repo is geen map."})
            elif path.exists() and not any(path.iterdir()):
                warnings.append({"code": "source_repo_empty", "message": "Source repo lijkt leeg."})
            # When path does not exist on this host, keep as warning — backend may run elsewhere.
            elif not path.exists():
                warnings.append(
                    {
                        "code": "source_repo_unverified",
                        "message": "Source pad kon lokaal niet worden geverifieerd.",
                    }
                )
        except OSError as exc:
            warnings.append({"code": "source_repo_error", "message": str(exc)[:200]})

    if not backend_reachable:
        blockers.append({"code": "backend_unreachable", "message": "Backend is niet bereikbaar."})

    intent = classify_coding_task_intent(goal or "", autonomy_profile=autonomy_profile)
    autonomy = (autonomy_profile or "reviewable_result").strip().lower()

    if autonomy == "analyze_only" and intent.requires_mutation and not has_manual_edits:
        blockers.append(
            {
                "code": "analyze_only",
                "message": human_reason_nl("analyze_only"),
            }
        )

    model = resolve_coding_model(
        explicit_model_id=active_model_id,
        active_model_id=active_model_id,
        profile_model_id=profile_model_id,
        inventory=inventory,
        use_omniroute=use_omniroute,
        omniroute_usable=omniroute_usable,
    )

    needs_model = (not has_manual_edits) and bool((goal or "").strip()) and intent.requires_mutation
    if needs_model and autonomy != "analyze_only":
        if lm_reachable is False and not use_omniroute:
            blockers.append(
                {
                    "code": "model_unavailable",
                    "message": human_reason_nl("model_unavailable"),
                }
            )
        elif not model.usable and not use_omniroute:
            blockers.append(
                {
                    "code": "model_unavailable",
                    "message": human_reason_nl("model_unavailable"),
                }
            )
        if use_omniroute and omniroute_usable is False:
            blockers.append(
                {
                    "code": "omniroute_unavailable",
                    "message": "OmniRoute is aangevraagd maar niet bruikbaar.",
                }
            )

    if needs_model and subprocess_approval_required and not subprocess_approved:
        warnings.append(
            {
                "code": "subprocess_approval",
                "message": "Subprocess-goedkeuring is vereist voor tests.",
            }
        )

    ready = len(blockers) == 0
    return {
        "schema": "coding_preflight_v1",
        "ready": ready,
        "can_start_natural_language": ready and (bool((goal or "").strip()) or has_manual_edits),
        "blockers": blockers,
        "warnings": warnings,
        "intent": intent.to_dict(),
        "model": model.to_dict(),
        "autonomy_profile": autonomy,
        "test_suite": test_suite or "auto",
        "analyze_only_blocks_mutation": autonomy == "analyze_only" and intent.requires_mutation,
        "manual_edits_ok_without_model": bool(has_manual_edits),
        "human_summary_nl": (
            blockers[0]["message"]
            if blockers
            else ("Klaar om te starten." if ready else "Preflight niet gereed.")
        ),
    }

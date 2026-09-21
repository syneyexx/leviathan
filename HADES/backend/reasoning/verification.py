from __future__ import annotations

import json
import re
from typing import Any

from .contracts import AcceptanceCriterionMatch, ToolObservation, VerificationResult
from .json_util import loads_json_object

_SUCCESS = {"completed", "succeeded", "success", "ok"}
_FAILURE = {"failed", "error", "blocked", "rejected", "cancelled", "timeout"}

# Soft display/parse bound — overflow criteria are marked unmet, never silently dropped as passed.
_CHECKLIST_SOFT_LIMIT = 48

_TRUE_STRINGS = frozenset({"true", "yes", "y", "1"})
_FALSE_STRINGS = frozenset({"false", "no", "n", "0"})


def _extract_json(text: str) -> Any | None:
    return loads_json_object(text)


def parse_strict_bool(value: Any) -> bool | None:
    """Parse verification booleans strictly.

    Accepts real bools and the explicit strings true/false (case-insensitive).
    Rejects arbitrary truthy values such as non-empty strings (including "false"
    when coerced via bool()).
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value == 1:
            return True
        if value == 0:
            return False
        return None
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _TRUE_STRINGS:
            return True
        if normalized in _FALSE_STRINGS:
            return False
        return None
    return None


def criterion_id_for(index: int, criterion: str = "") -> str:
    """Stable criterion id for matching (order-based, independent of wording drift)."""
    _ = criterion  # wording is not part of the id — ids stay stable across paraphrases
    return f"c{index + 1}"


def _norm_criterion(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _tool_status(item: ToolObservation | dict[str, Any]) -> str:
    if isinstance(item, ToolObservation):
        return str(item.status or "")
    return str(item.get("status") or "")


def _tool_call_id(item: ToolObservation | dict[str, Any]) -> str | None:
    if isinstance(item, ToolObservation):
        value = item.call_id
    else:
        value = item.get("call_id") or item.get("id")
    return str(value) if value else None


def _tool_optional(item: ToolObservation | dict[str, Any]) -> bool:
    if isinstance(item, ToolObservation):
        return False
    return bool(item.get("optional"))


def _step_is_draft_only(step: dict[str, Any]) -> bool:
    """True when a step is the candidate/draft answer under review, not source evidence."""
    if step.get("is_draft") or step.get("evidence_role") in {"draft", "candidate_answer", "under_review"}:
        return True
    title = str(step.get("title") or "").strip().lower()
    return title in {"chatantwoord", "draft", "candidate answer", "conceptantwoord", "onder beoordeling"}


def _iter_evidence_steps(
    step_outputs: list[dict[str, Any]] | None,
    *,
    include_draft_steps: bool = False,
):
    """Yield (1-based evidence index, step) skipping draft-only rows by default."""
    index = 0
    for step in step_outputs or []:
        if _step_is_draft_only(step) and not include_draft_steps:
            continue
        index += 1
        yield index, step


def build_allowed_evidence_refs(
    *,
    step_outputs: list[dict[str, Any]] | None = None,
    tool_observations: list[ToolObservation] | list[dict[str, Any]] | None = None,
    include_draft_steps: bool = False,
) -> set[str]:
    allowed: set[str] = set()
    for index, step in _iter_evidence_steps(step_outputs, include_draft_steps=include_draft_steps):
        allowed.add(f"step:{index}")
        step_id = step.get("step_id") or step.get("id")
        if step_id:
            allowed.add(f"step:{step_id}")
        title = str(step.get("title") or "").strip()
        if title:
            allowed.add(f"step:{title}")
        provenance = str(step.get("provenance") or "").strip()
        if provenance:
            allowed.add(provenance)
        for ref in step.get("evidence_refs") or []:
            if ref:
                allowed.add(str(ref))
    for item in tool_observations or []:
        call_id = _tool_call_id(item)
        status = _tool_status(item)
        if call_id and status in _SUCCESS:
            allowed.add(f"tool:{call_id}")
        if isinstance(item, ToolObservation):
            plugin_id, tool_name = item.plugin_id, item.tool_name
        else:
            plugin_id = str(item.get("plugin_id") or "")
            tool_name = str(item.get("tool_name") or "")
        if plugin_id and tool_name and status in _SUCCESS:
            allowed.add(f"tool:{plugin_id}/{tool_name}")
    return allowed


def _looks_like_draft_ref(ref: str) -> bool:
    lower = str(ref or "").strip().lower()
    if not lower:
        return False
    needles = (
        "chatantwoord",
        "conceptantwoord",
        "candidate_answer",
        "candidate answer",
        "draft_under_review",
        "onder beoordeling",
    )
    return any(needle in lower for needle in needles)


def validate_evidence_refs(
    refs: list[str],
    *,
    step_outputs: list[dict[str, Any]] | None = None,
    tool_observations: list[ToolObservation] | list[dict[str, Any]] | None = None,
    include_draft_steps: bool = False,
) -> tuple[bool, str]:
    """Every evidence_ref must resolve to a real step or successful tool observation."""
    factual_refs = [ref for ref in refs if not _looks_like_draft_ref(ref)]
    if not factual_refs:
        return True, ""
    allowed = build_allowed_evidence_refs(
        step_outputs=step_outputs,
        tool_observations=tool_observations,
        include_draft_steps=include_draft_steps,
    )
    unknown = [ref for ref in factual_refs if ref not in allowed]
    if unknown:
        return False, f"Onbekende of ongeldige evidence_refs: {', '.join(unknown[:6])}"
    return True, ""


def required_tool_failures(
    tool_observations: list[ToolObservation] | list[dict[str, Any]] | None,
) -> list[str]:
    failures: list[str] = []
    for item in tool_observations or []:
        if _tool_optional(item):
            continue
        status = _tool_status(item)
        if status in _FAILURE:
            if isinstance(item, ToolObservation):
                label = f"{item.plugin_id}/{item.tool_name}"
                detail = item.error or status
            else:
                label = f"{item.get('plugin_id')}/{item.get('tool_name')}"
                detail = item.get("error") or status
            failures.append(f"{label}: {detail}")
    return failures


def build_verification_prompt(
    *,
    task_title: str,
    task_prompt: str,
    acceptance_criteria: list[str],
    step_outputs: list[dict[str, str]],
    tool_observations: list[ToolObservation] | list[dict[str, Any]],
    draft_answer: str | None = None,
) -> str:
    evidence_parts: list[str] = []
    draft_parts: list[str] = []
    for item in step_outputs:
        if _step_is_draft_only(item):
            draft_parts.append(
                f"=== CONCEPT (geen step-ref, geen feitelijk bewijs) — {item.get('title')} ({item.get('agent_id')}) ===\n"
                f"{str(item.get('output', ''))[:18_000]}"
            )
    for index, item in _iter_evidence_steps(list(step_outputs), include_draft_steps=False):
        evidence_parts.append(
            f"=== step:{index} {item.get('title')} ({item.get('agent_id')}) ===\n"
            f"{str(item.get('output', ''))[:18_000]}"
        )
    if draft_answer and not draft_parts:
        draft_parts.append(f"=== DRAFT UNDER REVIEW ===\n{draft_answer[:18_000]}")
    evidence = "\n\n".join(evidence_parts) or "(geen bron/tool-observaties)"
    draft_view = "\n\n".join(draft_parts) or "(geen conceptantwoord)"

    tools_view: list[dict[str, Any]] = []
    for item in tool_observations:
        if isinstance(item, ToolObservation):
            tools_view.append(
                {
                    "call_id": item.call_id,
                    "plugin_id": item.plugin_id,
                    "tool_name": item.tool_name,
                    "status": item.status,
                    "exit_code": item.exit_code,
                    "error": item.error,
                    "succeeded": item.succeeded,
                }
            )
        else:
            tools_view.append(
                {
                    "call_id": item.get("call_id") or item.get("id"),
                    "plugin_id": item.get("plugin_id"),
                    "tool_name": item.get("tool_name"),
                    "status": item.get("status"),
                    "exit_code": item.get("exit_code"),
                    "error": item.get("error"),
                }
            )
    allowed = sorted(
        build_allowed_evidence_refs(
            step_outputs=list(step_outputs),
            tool_observations=tool_observations,
            include_draft_steps=False,
        )
    )
    criteria = acceptance_criteria or ["De oorspronkelijke opdracht is volledig uitgevoerd."]
    criteria_lines = []
    for index, criterion in enumerate(criteria):
        cid = criterion_id_for(index, criterion)
        criteria_lines.append(f"- id={cid}: {criterion}")

    return (
        "Je bent de onafhankelijke HADES Verification/Critic. "
        "Bepaal of de oorspronkelijke taak werkelijk is voltooid volgens de acceptance criteria. "
        "Een geslaagde maar irrelevante toolcall is geen bewijs van taakvoltooiing. "
        "Het CONCEPTANTWOORD mag beoordeeld worden op relevantie, structuur, consistentie en formulering, "
        "maar bewijst NIET zijn eigen feitelijke claims. Verwijs niet naar het concept als feitelijk bewijs. "
        "Gebruik uitsluitend bestaande evidence_refs uit de toegestane lijst (bronnen/toolresultaten). "
        "Het conceptantwoord heeft GEEN step-nummer; citeer nooit step:N voor het concept. "
        "Ontbrekend bewijs => passed=false. Lever geen herschreven final_answer met nieuwe claims; "
        "geef repair_instructions voor gerichte reparatie. "
        "Antwoord ALLEEN met JSON: "
        '{"passed":true|false,"issues":["..."],"evidence_refs":["step:1|tool:..."],'
        '"final":"","incomplete":false,'
        '"repair_instructions":["..."],'
        '"criteria_checklist":[{"id":"c1","criterion":"...","met":true|false,"note":"..."}]}.\n\n'
        f"TAAK:\n{task_title}\n{task_prompt}\n\nACCEPTANCE CRITERIA (match op id):\n"
        + "\n".join(criteria_lines)
        + "\n\nBeoordeel ELKE acceptance criterion in criteria_checklist met hetzelfde id en met=true/false (echte booleans)."
        + f"\n\nCONCEPTANTWOORD (onder beoordeling, GEEN feitelijk bewijs):\n{draft_view}"
        + f"\n\nBRONMATERIAAL / WERKRESULTATEN:\n{evidence}\n\nTOOLSTATUS:\n{json.dumps(tools_view, ensure_ascii=False)}"
        + f"\n\nTOEGESTANE EVIDENCE_REFS (geen draft):\n{json.dumps(allowed, ensure_ascii=False)}"
    )


def _parse_criteria_checklist(raw: Any) -> tuple[list[AcceptanceCriterionMatch], list[str]]:
    """Parse checklist rows with strict bools. Returns (rows, parse_issues)."""
    if not isinstance(raw, list):
        return [], ["criteria_checklist ontbreekt of is geen lijst"]
    rows: list[AcceptanceCriterionMatch] = []
    issues: list[str] = []
    seen_ids: set[str] = set()
    for item in raw:
        if len(rows) >= _CHECKLIST_SOFT_LIMIT:
            issues.append(f"checklist_truncated_at_{_CHECKLIST_SOFT_LIMIT}")
            break
        if isinstance(item, dict):
            criterion = str(item.get("criterion") or item.get("text") or "").strip()
            cid = str(item.get("id") or item.get("criterion_id") or "").strip()
            if not criterion and not cid:
                continue
            note = str(item.get("note") or item.get("reason") or "").strip()[:400]
            met_raw = item.get("met", item.get("passed", None))
            met = parse_strict_bool(met_raw)
            if met is None:
                issues.append(f"invalid_bool_for:{cid or criterion[:40]}")
                met = False
                if not note:
                    note = f"Ongeldige met-waarde ({met_raw!r}); behandeld als niet behaald"
            if cid and cid in seen_ids:
                issues.append(f"duplicate_criterion_id:{cid}")
                note = (note + "; dubbele id genegeerd voor matching").strip("; ")
            if cid:
                seen_ids.add(cid)
            rows.append(
                AcceptanceCriterionMatch(
                    criterion=criterion[:500] or cid,
                    met=met,
                    note=note,
                    criterion_id=cid,
                )
            )
        elif isinstance(item, str) and item.strip():
            rows.append(
                AcceptanceCriterionMatch(criterion=item.strip()[:500], met=False, note="Geen met-veld", criterion_id="")
            )
    return rows, issues


def bounded_schema_repair(parsed: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    """Attempt a bounded repair of near-valid critic JSON. Returns (repaired|None, notes)."""
    notes: list[str] = []
    if not isinstance(parsed, dict):
        return None, ["not_an_object"]
    out = dict(parsed)

    passed = parse_strict_bool(out.get("passed"))
    if passed is None and "passed" in out:
        notes.append("passed_not_strict_bool")
        return None, notes
    if passed is None:
        # Missing passed — cannot invent success.
        notes.append("passed_missing")
        out["passed"] = False
        out["incomplete"] = True
        passed = False
    else:
        out["passed"] = passed

    incomplete = parse_strict_bool(out.get("incomplete"))
    if incomplete is None:
        out["incomplete"] = False if "incomplete" not in out else True
        if "incomplete" in parsed and parse_strict_bool(parsed.get("incomplete")) is None:
            notes.append("incomplete_defaulted_true_after_invalid")
            out["incomplete"] = True
    else:
        out["incomplete"] = incomplete

    issues = out.get("issues", [])
    if not isinstance(issues, list):
        out["issues"] = [str(issues)]
        notes.append("issues_coerced_to_list")
    evidence_refs = out.get("evidence_refs", [])
    if not isinstance(evidence_refs, list):
        out["evidence_refs"] = []
        notes.append("evidence_refs_cleared_invalid")
    checklist = out.get("criteria_checklist") or out.get("acceptance_checklist") or out.get("checklist")
    if checklist is not None and not isinstance(checklist, list):
        out["criteria_checklist"] = []
        notes.append("checklist_cleared_invalid")
    elif isinstance(checklist, list):
        out["criteria_checklist"] = checklist
    repairs = out.get("repair_instructions", [])
    if repairs is not None and not isinstance(repairs, list):
        out["repair_instructions"] = [str(repairs)]
        notes.append("repair_instructions_coerced")
    if notes:
        notes.insert(0, "schema_repaired")
    return out, notes


def build_acceptance_checklist(
    criteria: list[str] | None,
    *,
    result: VerificationResult | None = None,
) -> list[AcceptanceCriterionMatch]:
    """Build a visible checklist matched by stable criterion ids / exact text.

    Rules:
    - No positional fallback that can map the wrong critic row onto an expected criterion.
    - A bare passed=True without per-criterion rows does NOT mark criteria as met.
    - Soft limits never silently drop required criteria as satisfied.
    """
    expected_raw = [str(item).strip() for item in (criteria or []) if str(item).strip()]
    truncated_note = ""
    if len(expected_raw) > _CHECKLIST_SOFT_LIMIT:
        truncated_note = f"Soft limit {_CHECKLIST_SOFT_LIMIT}: overige criteria blijven expliciet unmet"
    expected = expected_raw  # never drop requirements from the matching set

    if not expected:
        expected = ["De oorspronkelijke opdracht is volledig uitgevoerd."]

    if result is None:
        return [
            AcceptanceCriterionMatch(
                criterion=item,
                met=False,
                note="Nog niet geverifieerd",
                criterion_id=criterion_id_for(index, item),
            )
            for index, item in enumerate(expected)
        ]

    by_id: dict[str, AcceptanceCriterionMatch] = {}
    by_norm: dict[str, AcceptanceCriterionMatch] = {}
    unknown_ids: list[str] = []
    expected_ids = {criterion_id_for(i, c) for i, c in enumerate(expected)}
    expected_norms = {_norm_criterion(c) for c in expected}

    for row in result.criteria_checklist:
        cid = (row.criterion_id or "").strip()
        if cid:
            if cid in by_id:
                continue  # duplicate id: first wins
            if cid not in expected_ids:
                unknown_ids.append(cid)
            by_id[cid] = row
        norm = _norm_criterion(row.criterion)
        if norm and norm not in by_norm:
            by_norm[norm] = row
            if norm not in expected_norms and not cid:
                unknown_ids.append(f"text:{row.criterion[:40]}")

    matched: list[AcceptanceCriterionMatch] = []
    for index, criterion in enumerate(expected):
        cid = criterion_id_for(index, criterion)
        row = by_id.get(cid) or by_norm.get(_norm_criterion(criterion))
        if row is not None:
            matched.append(
                AcceptanceCriterionMatch(
                    criterion=criterion,
                    met=bool(row.met),
                    note=row.note,
                    criterion_id=cid,
                )
            )
        elif not result.criteria_checklist:
            # Missing checklist entirely — even if passed=True, criteria are unmet.
            note = "Geen criteria_checklist; algemeen passed vervangt geen individuele controle"
            if result.passed:
                note = "passed=true zonder checklist; criterium niet individueel aangetoond"
            matched.append(
                AcceptanceCriterionMatch(criterion=criterion, met=False, note=note, criterion_id=cid)
            )
        else:
            matched.append(
                AcceptanceCriterionMatch(
                    criterion=criterion,
                    met=False,
                    note="Geen match op criterion id/tekst (geen positionele fallback)",
                    criterion_id=cid,
                )
            )

    if unknown_ids and result is not None:
        # Surface unknown ids on the first unmatched note if needed; callers can inspect issues.
        result.issues = list(result.issues) + [f"onbekende_criterion_ids:{','.join(unknown_ids[:6])}"]
        result.issues = result.issues[:16]

    if truncated_note:
        for row in matched[_CHECKLIST_SOFT_LIMIT:]:
            if row.met:
                row.met = False
                row.note = (row.note + "; " if row.note else "") + truncated_note

    return matched


def checklist_blocks_completion(checklist: list[AcceptanceCriterionMatch] | list[dict[str, Any]] | None) -> bool:
    for item in checklist or []:
        if isinstance(item, AcceptanceCriterionMatch):
            if not item.met:
                return True
        elif isinstance(item, dict):
            met = parse_strict_bool(item.get("met"))
            if met is not True:
                return True
    return False


def parse_verification_result(raw: str) -> VerificationResult | None:
    """Parse critic output. Invalid schema after bounded repair => unverified/incomplete."""
    parsed = _extract_json(raw)
    repair_notes: list[str] = []
    if not isinstance(parsed, dict):
        return VerificationResult(
            passed=False,
            issues=["Ongeldige JSON van verification/critic"],
            final_answer="",
            method="structured_critic",
            incomplete=True,
            parse_status="invalid_json",
            schema_valid=False,
            criteria_coverage_complete=False,
            evidence_sufficient=False,
        )

    repaired, repair_notes = bounded_schema_repair(parsed)
    if repaired is None:
        return VerificationResult(
            passed=False,
            issues=["Ongeldig schema van verification/critic"] + repair_notes,
            final_answer="",
            method="structured_critic",
            incomplete=True,
            parse_status="invalid_schema",
            schema_valid=False,
            criteria_coverage_complete=False,
            evidence_sufficient=False,
            repair_notes=repair_notes,
        )

    passed = bool(repaired["passed"])
    issues = [str(item) for item in (repaired.get("issues") or [])[:12]]
    evidence_refs = [str(item) for item in (repaired.get("evidence_refs") or [])[:20]]
    checklist, checklist_issues = _parse_criteria_checklist(
        repaired.get("criteria_checklist") or repaired.get("acceptance_checklist") or repaired.get("checklist")
    )
    issues.extend(checklist_issues[:6])
    repair_instructions = [str(item) for item in (repaired.get("repair_instructions") or [])[:12]]
    proposed = str(repaired.get("final") or repaired.get("proposed_final_answer") or "").strip()
    incomplete = bool(repaired.get("incomplete", False))
    parse_status = "repaired" if repair_notes else "valid_schema"

    return VerificationResult(
        passed=passed,
        issues=issues,
        final_answer="",  # Do not auto-adopt critic rewrite as verified final.
        evidence_refs=evidence_refs,
        method="structured_critic",
        incomplete=incomplete,
        criteria_checklist=checklist,
        parse_status=parse_status,
        schema_valid=True,
        criteria_coverage_complete=False,  # filled by verification_allows_success
        evidence_sufficient=False,
        repair_notes=repair_notes,
        repair_instructions=repair_instructions,
        proposed_final_answer=proposed,
    )


def verification_allows_success(
    result: VerificationResult | None,
    *,
    tool_observations: list[ToolObservation] | list[dict[str, Any]] | None = None,
    step_outputs: list[dict[str, Any]] | None = None,
    require_final: bool = True,
    require_evidence_when_tools: bool = True,
    acceptance_criteria: list[str] | None = None,
    allow_draft_as_evidence: bool = False,
) -> tuple[bool, str]:
    if result is None:
        return False, "Verification/Critic gaf geen valide completion-beslissing."
    if result.parse_status in {"invalid_json", "invalid_schema"}:
        return False, "Verification output ongeldig; status blijft unverified/incomplete."
    if result.incomplete:
        return False, "Verification markeerde het resultaat als incompleet."
    if not result.passed:
        return False, "; ".join(result.issues[:8]) or "Critic vond onvoldoende bewijs."

    # Prefer draft content already produced; proposed_final_answer is advisory only unless
    # callers explicitly adopt it after targeted re-check.
    usable_final = (result.final_answer or result.proposed_final_answer or "").strip()
    if require_final and not usable_final:
        # Chat path often keeps the original draft; allow success when draft exists in steps.
        draft_present = any(_step_is_draft_only(step) and str(step.get("output") or "").strip() for step in (step_outputs or []))
        if not draft_present:
            return False, "Verification slaagde maar leverde geen bruikbaar eindresultaat."

    checklist = build_acceptance_checklist(acceptance_criteria, result=result)
    result.criteria_checklist = checklist
    # Coverage = every expected criterion has an explicit row (matched or explicitly unmet).
    # Missing checklist still yields rows, but those are incomplete coverage.
    missing_individual = any(
        "zonder checklist" in (row.note or "")
        or row.note.startswith("Geen criteria_checklist")
        or "geen positionele fallback" in (row.note or "").lower()
        for row in checklist
    )
    expected_count = len([c for c in (acceptance_criteria or checklist) if str(getattr(c, "criterion", c) or "").strip()])
    result.criteria_coverage_complete = bool(checklist) and len(checklist) >= max(1, expected_count) and not missing_individual

    if checklist_blocks_completion(checklist):
        unmet = [row.criterion for row in checklist if not row.met][:6]
        result.parse_status = "incomplete_coverage" if not any(row.met for row in checklist) else "unverified"
        return False, "Acceptatiecriteria niet gehaald: " + "; ".join(unmet)

    failures = required_tool_failures(tool_observations)
    if failures:
        return False, "Vereiste toolactie(s) mislukt zonder aantoonbaar herstel: " + "; ".join(failures[:6])

    factual_refs = [ref for ref in result.evidence_refs if not _looks_like_draft_ref(ref)]
    if result.evidence_refs and not factual_refs and not allow_draft_as_evidence:
        result.evidence_sufficient = False
        return False, "Evidence_refs verwijzen alleen naar het conceptantwoord, niet naar bronnen of tools."
    if factual_refs:
        ok, reason = validate_evidence_refs(
            factual_refs,
            step_outputs=step_outputs,
            tool_observations=tool_observations,
            include_draft_steps=allow_draft_as_evidence,
        )
        if not ok:
            result.evidence_sufficient = False
            return False, reason
        result.evidence_sufficient = True
    else:
        result.evidence_sufficient = False

    if require_evidence_when_tools and tool_observations is not None and not factual_refs:
        successes = 0
        for item in tool_observations:
            if _tool_status(item) in _SUCCESS:
                successes += 1
        if successes > 0:
            return False, "Toolsucces zonder gekoppeld taakbewijs is onvoldoende voor completion."
        non_draft_steps = [s for s in (step_outputs or []) if not _step_is_draft_only(s)]
        if non_draft_steps:
            return False, "Voltooide werkstappen vereisen gekoppelde evidence_refs."

    result.parse_status = "verified"
    # Keep proposed text available but do not treat it as already-verified final unless set.
    if not result.final_answer and result.proposed_final_answer:
        # Callers that require_final may copy after their own checks; leave final empty by default.
        pass
    return True, ""


def apply_critic_outcome(
    *,
    draft_answer: str,
    result: VerificationResult | None,
    allowed: bool,
    reason: str,
) -> tuple[str, str, list[str]]:
    """Apply critic outcome without unchecked adoption of rewritten claims.

    Returns (content, status_note, repair_instructions).
    Contract: critic assesses + gives repair instructions; a rewritten final is
    advisory (proposed_final_answer) and is only used when it does not introduce
    unchecked replacement of the draft as factual verification.
    """
    if not allowed or result is None:
        repairs = list(result.repair_instructions) if result else []
        suffix = f"\n\n---\nVerificatie kon voltooiing niet bevestigen: {reason}"
        if repairs:
            suffix += "\nGerichte reparatie: " + "; ".join(repairs[:4])
        return draft_answer + suffix, f"verification:failed:{reason}", repairs

    # Prefer keeping the draft; only adopt proposed text when it is a constrained repair
    # and evidence still holds — callers should re-verify material rewrites.
    proposed = (result.proposed_final_answer or "").strip()
    if proposed and proposed != draft_answer.strip():
        # Do not silently replace; return draft with repair note unless proposed is empty-final path.
        if result.repair_instructions:
            return (
                draft_answer,
                "verification:passed_with_repair_instructions",
                list(result.repair_instructions),
            )
        # Short structural polish without new claim markers may be adopted by caller after re-check.
        return draft_answer, "verification:passed_proposed_rewrite_pending_recheck", list(result.repair_instructions)
    return draft_answer, "verification:passed", []

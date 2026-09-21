"""Debug agent: failing logs/tests → minimal verified fix proposal.

Does not silently apply patches. Returns a reviewable diagnosis + suggested edits.
"""

from __future__ import annotations

import re
from typing import Any


TS_ERROR_RE = re.compile(
    r"(?P<path>[\w./\\-]+\.(?:ts|tsx|js|jsx|py))\((?P<line>\d+),(?P<col>\d+)\):\s*error\s+(?P<code>TS\d+):\s*(?P<msg>.+)",
    re.I,
)
PYTEST_RE = re.compile(
    r"(?P<path>[\w./\\-]+\.py):(?P<line>\d+):\s*(?P<msg>.+)",
)
UNITTEST_FAIL_RE = re.compile(r"^(?P<kind>FAIL|ERROR):\s+(?P<test>.+)$", re.M)
ASSERT_RE = re.compile(r"AssertionError:?\s*(?P<msg>.+)")
ASSERT_EQUAL_RE = re.compile(
    r"AssertionError:\s*(?P<got>.+?)\s*!=\s*(?P<expected>.+)",
)
NAME_ERROR_RE = re.compile(r"NameError:\s*name\s+'(?P<name>[^']+)'\s+is not defined")
ATTR_ERROR_RE = re.compile(r"AttributeError:\s*(?P<msg>.+)")


def diagnose_failure(*, logs: str, failing_test: str = "", context_files: list[dict[str, str]] | None = None) -> dict[str, Any]:
    text = (logs or "").strip()
    if not text and not failing_test:
        raise ValueError("Geef logs en/of een falende test op.")

    structured = None
    try:
        from coding_failures import normalize_failure

        structured = normalize_failure(logs=text)
    except Exception:
        structured = None

    findings: list[dict[str, Any]] = []
    for match in TS_ERROR_RE.finditer(text):
        findings.append(
            {
                "kind": "typescript",
                "path": match.group("path").replace("\\", "/"),
                "line": int(match.group("line")),
                "column": int(match.group("col")),
                "code": match.group("code"),
                "message": match.group("msg").strip(),
            }
        )
    if not findings:
        for match in PYTEST_RE.finditer(text):
            findings.append(
                {
                    "kind": "pytest",
                    "path": match.group("path").replace("\\", "/"),
                    "line": int(match.group("line")),
                    "message": match.group("msg").strip()[:400],
                }
            )

    failing_tests = [m.group("test").strip() for m in UNITTEST_FAIL_RE.finditer(text)]
    if failing_test and failing_test not in failing_tests:
        failing_tests.insert(0, failing_test)

    assert_msgs = [m.group("msg").strip() for m in ASSERT_RE.finditer(text)]
    assert_pairs = [
        {"got": m.group("got").strip(), "expected": m.group("expected").strip()}
        for m in ASSERT_EQUAL_RE.finditer(text)
    ]

    suggestions: list[dict[str, Any]] = []
    for item in findings[:8]:
        msg = item.get("message", "")
        action = "inspect"
        hint = "Lees de fout op de gemelde regel en pas het minimale type/waarde-probleem aan."
        if "is not assignable" in msg or "Type '" in msg:
            action = "narrow_or_default"
            hint = "Voeg een default/guard toe of vernauw het type op de gemelde locatie."
        elif "does not exist" in msg or "has no attribute" in msg or "NameError" in msg:
            action = "define_or_import"
            hint = "Definieer of importeer het ontbrekende symbool; claim geen bestaande API."
        elif "ModuleNotFoundError" in msg or "Cannot find module" in msg:
            action = "dependency"
            hint = "Controleer of de dependency lokaal geïnstalleerd is; geen stille remote install."
        suggestions.append(
            {
                "path": item.get("path"),
                "line": item.get("line"),
                "action": action,
                "hint": hint,
                "evidence": msg,
            }
        )

    for name_err in NAME_ERROR_RE.finditer(text):
        suggestions.append(
            {
                "path": None,
                "line": None,
                "action": "define_or_import",
                "hint": f"Importeer of definieer '{name_err.group('name')}' vóór gebruik.",
                "evidence": name_err.group(0),
            }
        )
    for attr_err in ATTR_ERROR_RE.finditer(text):
        suggestions.append(
            {
                "path": None,
                "line": None,
                "action": "define_or_import",
                "hint": "Controleer attribuutnaam/API — geen stille monkeypatch van ontbrekende members.",
                "evidence": attr_err.group("msg").strip()[:300],
            }
        )

    context_by_name: dict[str, dict[str, str]] = {}
    for blob in context_files or []:
        path = str(blob.get("path") or "").replace("\\", "/")
        if path:
            context_by_name[path.split("/")[-1]] = {"path": path, "content": str(blob.get("content") or "")}

    file_hints: list[str] = []
    proposed_edits: list[dict[str, Any]] = []
    for item in findings[:8]:
        path = str(item.get("path") or "").replace("\\", "/")
        base = path.split("/")[-1]
        if path and any(path.endswith(str(f.get("path") or "").split("/")[-1]) for f in findings):
            file_hints.append(path)
        ctx = context_by_name.get(base)
        if not ctx or not ctx.get("content"):
            continue
        line_no = int(item.get("line") or 0)
        lines = ctx["content"].splitlines()
        if line_no < 1 or line_no > len(lines):
            continue
        # Never invent a full patch body — propose a patch_lines stub targeting the failing line.
        proposed_edits.append(
            {
                "path": ctx["path"],
                "action": "patch_lines",
                "start_line": line_no,
                "end_line": line_no,
                "content": lines[line_no - 1],
                "status": "review_required",
                "note": "Stub op falende regel — pas content handmatig aan vóór build-run.",
                "evidence": item.get("message"),
            }
        )
        file_hints.append(ctx["path"])

    # Deduplicate file hints
    file_hints = list(dict.fromkeys(file_hints))

    status = "diagnosed" if findings or assert_msgs or failing_tests else "insufficient_evidence"
    payload = {
        "status": status,
        "failing_test": failing_test or (failing_tests[0] if failing_tests else None),
        "failing_tests": failing_tests[:20],
        "findings": findings,
        "assertions": assert_msgs[:10],
        "assertion_pairs": assert_pairs[:10],
        "suggestions": suggestions[:20],
        "related_context_files": file_hints,
        "proposed_edits": proposed_edits,  # Review stubs only; never auto-applied.
        "verification_required": True,
        "what_broke": (failing_tests[:10] or [f["message"] for f in findings[:5] if f.get("message")] or assert_msgs[:5]),
        "note": (
            "Diagnose is heuristisch. Geen automatische apply. "
            "Gebruik Build Agent met expliciete edits + tests (repair_waves) om een fix te verifiëren."
            if status == "diagnosed"
            else "Onvoldoende parseerbare fouten in de logs — lever volledigere testoutput."
        ),
    }
    if structured is not None:
        payload["structured_failure"] = structured.to_dict()
        if structured.file and not payload.get("failing_test"):
            payload["related_context_files"] = list(dict.fromkeys([*file_hints, structured.file]))
        if structured.message and status == "insufficient_evidence":
            payload["status"] = "diagnosed"
            payload["what_broke"] = [structured.message]
    return payload

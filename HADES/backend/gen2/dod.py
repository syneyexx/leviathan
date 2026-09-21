"""Definition of Done enforcement helper (K11).

Refuses to mark Gen2 checklist items as ``full`` / ``shipped`` without evidence.
"""

from __future__ import annotations

from typing import Any


REQUIRED_EVIDENCE_FIELDS = (
    "tests",
    "verification_status",
    "notes",
)

FORBIDDEN_FULL_WITHOUT_EVIDENCE = frozenset({"full", "shipped", "complete", "done_full"})


def validate_status_claim(claim: dict[str, Any] | None) -> dict[str, Any]:
    """Validate a status/DoD claim payload.

    Returns ok=False when status is full/shipped but evidence fields are missing
    or verification_status is a fake PASS without tests.
    """
    data = dict(claim or {})
    status = str(data.get("status") or data.get("dod_status") or "").strip().lower()
    missing = [f for f in REQUIRED_EVIDENCE_FIELDS if not data.get(f)]
    verification = str(data.get("verification_status") or "").strip()
    tests = data.get("tests")
    errors: list[str] = []

    if status in FORBIDDEN_FULL_WITHOUT_EVIDENCE:
        if missing:
            errors.append(f"full_status_requires_evidence:{','.join(missing)}")
        if verification.upper() in {"PASS", "PASSED", "VERIFIED"} and not tests:
            errors.append("pass_without_tests_forbidden")
        if verification.upper() in {"UNVERIFIED_ON_HOST", "UNVERIFIED", "PARTIAL"}:
            errors.append("full_status_forbidden_while_unverified")
        if data.get("fake_success") is True:
            errors.append("fake_success_flag_set")

    return {
        "ok": len(errors) == 0,
        "allowed_status": status if len(errors) == 0 else "refused",
        "requested_status": status,
        "errors": errors,
        "required_evidence_fields": list(REQUIRED_EVIDENCE_FIELDS),
        "note": "DoD: never mark full/shipped without tests + verification_status + notes.",
    }


def refuse_full_without_evidence(claim: dict[str, Any] | None) -> dict[str, Any]:
    """Public helper used by docs/CI discipline checks."""
    result = validate_status_claim(claim)
    if not result["ok"]:
        return {
            **result,
            "status": "refused",
            "enforced": True,
        }
    return {
        **result,
        "status": result["requested_status"],
        "enforced": True,
    }

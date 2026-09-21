"""Context Compiler 2.0 — ranked pack with approx tokenizer, dedupe, diversity.

Token counts are local estimates by default (~4 chars/token), not provider billing.
Optional ``tokenizer_mode``: approx_chars_4 | whitespace_words | tiktoken_cl100k
(with honest fallback when tiktoken is unavailable).
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from gen2.store import Gen2Store, new_id, utc_now


def _sha(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


CANONICAL_DROP_REASONS = frozenset(
    {"token_budget", "duplicate", "low_relevance", "stale", "superseded", "insufficient_evidence"}
)


def canonicalize_drop_reason(reason: str | None) -> str:
    """Map internal drop labels onto the operator-facing taxonomy."""
    raw = str(reason or "").strip().lower()
    if raw in CANONICAL_DROP_REASONS:
        return raw
    if "duplicate" in raw:
        return "duplicate"
    if "stale" in raw or "max_age" in raw or "temporal" in raw:
        return "stale"
    if "supersede" in raw:
        return "superseded"
    if "relevance" in raw or "usefulness" in raw or "source_diversity" in raw:
        return "low_relevance"
    if "insufficient" in raw or (("mandatory" in raw) and ("fail" in raw or "error" in raw)):
        return "insufficient_evidence"
    if "token" in raw or "budget" in raw or "evict" in raw or "summarized" in raw:
        return "token_budget"
    return raw or "token_budget"


def estimate_tokens_with_mode(text: str, *, tokenizer_mode: str = "approx_chars_4") -> tuple[int, str]:
    """Return (token_count, effective_tokenizer_label)."""
    mode = (tokenizer_mode or "approx_chars_4").strip().lower()
    content = text or ""
    if mode in {"whitespace_words", "words", "whitespace"}:
        words = [w for w in re.split(r"\s+", content) if w]
        return (max(1, len(words)) if content.strip() else 1), "whitespace_words"
    if mode in {"tiktoken_cl100k", "tiktoken", "cl100k_base"}:
        try:
            import tiktoken  # type: ignore

            enc = tiktoken.get_encoding("cl100k_base")
            return max(1, len(enc.encode(content))), "tiktoken_cl100k"
        except Exception:
            approx = max(1, (len(content) + 3) // 4) if content else 1
            return approx, "tiktoken_unavailable_fallback_approx"
    return (max(1, (len(content) + 3) // 4) if content else 1), "approx_chars_4"


def estimate_tokens(text: str, tokenizer_mode: str = "approx_chars_4") -> int:
    """Approximate tokenizer: default ~4 chars/token for Latin text (local, no model dependency)."""
    count, _label = estimate_tokens_with_mode(text, tokenizer_mode=tokenizer_mode)
    return count


def entity_key(text: str) -> str:
    tokens = re.findall(r"[A-Za-zÀ-ÿ0-9]{4,}", text or "")
    if not tokens:
        return "misc"
    return "|".join(sorted({t.lower() for t in tokens[:6]}))


def _parse_time(value: Any) -> datetime | None:
    if value is None or value is False:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    text = str(value).strip()
    if not text:
        return None
    try:
        # Support trailing Z
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except Exception:
        return None


def _is_pinned(raw: dict[str, Any]) -> bool:
    pin = raw.get("pin") or raw.get("pinned") or raw.get("mandatory")
    if pin in {True, 1, "1", "true", "True", "yes", "mandatory", "pin", "pinned"}:
        return True
    if str(raw.get("priority") or "").lower() in {"mandatory", "pin", "pinned"}:
        return True
    if str(raw.get("kind") or "").lower() == "mandatory":
        return True
    return False


def _extractive_snippet(content: str, *, max_chars: int = 220) -> str:
    """Cheap extractive compression: prefer sentence boundaries over naive [:N] cuts."""
    text = re.sub(r"\s+", " ", (content or "").strip())
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    # Split on sentence-ish boundaries; keep highest-signal early + mid sentences.
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", text) if p.strip()]
    if len(parts) <= 1:
        cut = text[: max(40, max_chars - 1)].rstrip()
        return cut + "…"
    scored: list[tuple[float, int, str]] = []
    for index, part in enumerate(parts):
        # Prefer informative length and earlier position lightly.
        score = min(len(part), 180) / 180.0 + max(0.0, 0.25 - index * 0.03)
        tokens = re.findall(r"[A-Za-zÀ-ÿ0-9]{4,}", part.lower())
        score += min(0.35, 0.04 * len(set(tokens)))
        scored.append((score, index, part))
    scored.sort(key=lambda item: (-item[0], item[1]))
    chosen: list[tuple[int, str]] = []
    used = 0
    for _score, index, part in scored:
        piece = part if len(part) <= max_chars else (part[: max_chars - 1].rstrip() + "…")
        if used + len(piece) + 1 > max_chars and chosen:
            break
        chosen.append((index, piece))
        used += len(piece) + 1
        if used >= max_chars or len(chosen) >= 3:
            break
    chosen.sort(key=lambda item: item[0])
    return " ".join(piece for _, piece in chosen)


def _hierarchical_summary_node(
    children: list[dict[str, Any]],
    *,
    budget_tokens: int,
    tokenizer_mode: str,
    summarize_fn: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """Hierarchical summary of budget-dropped items.

    When ``summarize_fn`` succeeds, labels ``summary_quality=model_summary``.
    Otherwise falls back to an extractive stub labeled ``stub_not_model_summary``
    — never presented as genuine model summarization.
    """
    snippets = []
    for child in children[:12]:
        extract = _extractive_snippet(str(child.get("content") or ""), max_chars=220)
        snippets.append(f"- [{child.get('item_id')}] {extract}")
    source_ids = [c.get("item_id") for c in children]
    range_key = _sha("".join(str(i or "") for i in source_ids))
    model_body: str | None = None
    model_error: str | None = None
    if summarize_fn is not None:
        try:
            prompt = (
                "Summarize the following deferred context snippets for a later model turn. "
                "Preserve checkable facts; do not invent sources.\n\n" + "\n".join(snippets)
            )
            raw = str(summarize_fn(prompt) or "").strip()
            if raw:
                model_body = raw[: max(200, budget_tokens * 4)]
        except Exception as exc:  # noqa: BLE001 — honesty path
            model_error = str(exc)[:240]
    if model_body:
        header = "MODEL HIERARCHICAL SUMMARY (status=model_summary; not evidence):\n"
        body = header + model_body
        quality = "model_summary"
        provenance = "hierarchical_summary_model"
        honesty = {
            "is_stub": False,
            "model_quality": True,
            "extractive_only": False,
            "label": "hierarchical_summary_model_with_provenance",
            "source_message_ids": source_ids,
            "range_key": range_key,
        }
        summary_status = "model"
    else:
        header = (
            "EXTRACTIVE DEFERRED-CONTEXT SUMMARY "
            "(status=stub_not_model_summary; not quality-validated):\n"
        )
        body = header + "\n".join(snippets)
        if model_error:
            body = f"{body}\n(model_summary_failed: {model_error})"
        quality = "stub_not_model_summary"
        provenance = "hierarchical_summary_stub"
        honesty = {
            "is_stub": True,
            "model_quality": False,
            "extractive_only": True,
            "label": "hierarchical_summary_stub_with_provenance",
            "source_message_ids": source_ids,
            "range_key": range_key,
            "model_error": model_error,
        }
        summary_status = "extractive_stub"
    tokens, _label = estimate_tokens_with_mode(body, tokenizer_mode=tokenizer_mode)
    # Trim if still over remaining budget.
    while tokens > max(32, budget_tokens) and len(snippets) > 1 and quality == "stub_not_model_summary":
        snippets.pop()
        body = header + "\n".join(snippets)
        if model_error:
            body = f"{body}\n(model_summary_failed: {model_error})"
        tokens, _label = estimate_tokens_with_mode(body, tokenizer_mode=tokenizer_mode)
    return {
        "item_id": f"summary_{range_key}",
        "kind": "summary",
        "content": body,
        "provenance": provenance,
        "summary_quality": quality,
        "summary_status": summary_status,
        "honesty": honesty,
        "source": "compiler_summary",
        "reliability": 0.55,
        "freshness": 0.5,
        "usefulness": 0.6,
        "temporal_valid": True,
        "tokens": tokens,
        "hash": _sha(body),
        "contradiction_group": "summary",
        "pinned": False,
        "provenance_links": source_ids,
        "is_summary_node": True,
    }


def compile_context(
    store: Gen2Store,
    *,
    goal: str,
    items: list[dict[str, Any]],
    max_tokens: int = 2048,
    model_context_size: int | None = None,
    run_id: str | None = None,
    persist: bool = True,
    response_reserve_tokens: int | None = None,
    system_reserve_tokens: int | None = None,
    request_budget_tokens: int | None = None,
    tokenizer_mode: str = "approx_chars_4",
    max_age_hours: float | None = None,
    now: str | datetime | None = None,
    hierarchical_summarization: bool = True,
    pin_overflow: str = "keep_with_note",
    summarize_fn: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """Compile ranked context with approx tokenizer, dedupe, contradiction grouping, diversity.

    When ``request_budget_tokens`` or explicit reserves are provided, context budget is the
    remainder of the full request (system + response reserved). Otherwise legacy 0.55 ratio.

    ``pin_overflow``: ``keep_with_note`` (default) keeps mandatory pins even over budget and
    sets ``overflow_note``; ``error`` raises ValueError when a pin cannot fit.

    ``summarize_fn``: optional sync model summarizer for hierarchical nodes. Failure falls
    back to an explicitly labeled extractive stub (never fake model_summary).
    """
    tok_mode = tokenizer_mode or "approx_chars_4"
    budget = int(max_tokens)
    reserve_ratio = 0.55
    reserve_note = "fixed_ratio_0.55_legacy"
    reserve_detail: dict[str, Any] = {"mode": "legacy_ratio", "ratio": reserve_ratio}
    if request_budget_tokens is not None or response_reserve_tokens is not None or system_reserve_tokens is not None:
        total = int(request_budget_tokens or model_context_size or max_tokens)
        sys_r = int(system_reserve_tokens or 0)
        resp_r = int(response_reserve_tokens if response_reserve_tokens is not None else max(256, int(total * 0.25)))
        budget = max(64, total - sys_r - resp_r)
        budget = min(budget, int(max_tokens))
        reserve_note = f"request_budget_minus_reserves:total={total}:sys={sys_r}:resp={resp_r}"
        reserve_detail = {
            "mode": "full_request_budget",
            "request_budget_tokens": total,
            "system_reserve_tokens": sys_r,
            "response_reserve_tokens": resp_r,
            "context_budget_tokens": budget,
        }
    elif model_context_size:
        budget = min(budget, max(256, int(model_context_size * reserve_ratio)))
        reserve_note = f"model_context*{reserve_ratio}"
        reserve_detail = {
            "mode": "legacy_ratio",
            "ratio": reserve_ratio,
            "model_context_size": int(model_context_size),
            "context_budget_tokens": budget,
        }

    now_dt = _parse_time(now) or datetime.now(UTC)
    effective_tokenizer = "approx_chars_4"

    normalized: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    early_dropped: list[dict[str, Any]] = []
    pin_errors: list[str] = []

    for index, raw in enumerate(items):
        content = str(raw.get("content") or "").strip()
        if not content:
            continue
        digest = _sha(re.sub(r"\s+", " ", content.lower()))
        item_id = str(raw.get("item_id") or f"item_{index}")
        pinned = _is_pinned(raw)

        # Temporal validity (F1.5)
        valid_from = _parse_time(raw.get("valid_from"))
        valid_until = _parse_time(raw.get("valid_until"))
        temporal_valid = bool(raw.get("temporal_valid", True))
        if valid_from and now_dt < valid_from:
            temporal_valid = False
        if valid_until and now_dt > valid_until:
            temporal_valid = False

        # Freshness / max age (F1.5)
        observed_at = _parse_time(raw.get("observed_at") or raw.get("freshness_at") or raw.get("updated_at"))
        stale = False
        if max_age_hours is not None and observed_at is not None:
            age = now_dt - observed_at
            if age > timedelta(hours=float(max_age_hours)):
                stale = True

        if (str(raw.get("status") or "").strip().lower() == "superseded" or raw.get("superseded_by")) and not pinned:
            early_dropped.append(
                {
                    "item_id": item_id,
                    "kind": str(raw.get("kind") or "other"),
                    "provenance": str(raw.get("provenance") or ""),
                    "tokens": estimate_tokens(content, tokenizer_mode=tok_mode),
                    "drop_reason": "superseded",
                    "why": f"superseded_by:{raw.get('superseded_by') or 'status'}",
                }
            )
            continue

        if not pinned and ("usefulness" in raw or "score" in raw):
            try:
                usefulness_probe = float(raw.get("usefulness", raw.get("score")))
            except (TypeError, ValueError):
                usefulness_probe = None
            if usefulness_probe is not None and 0.0 <= usefulness_probe < 0.2:
                early_dropped.append(
                    {
                        "item_id": item_id,
                        "kind": str(raw.get("kind") or "other"),
                        "provenance": str(raw.get("provenance") or ""),
                        "tokens": estimate_tokens(content, tokenizer_mode=tok_mode),
                        "drop_reason": "low_relevance",
                        "why": f"explicit_usefulness={usefulness_probe}",
                    }
                )
                continue

        if digest in seen_hashes and not pinned:
            early_dropped.append(
                {
                    "item_id": item_id,
                    "kind": str(raw.get("kind") or "other"),
                    "provenance": str(raw.get("provenance") or ""),
                    "tokens": estimate_tokens(content, tokenizer_mode=tok_mode),
                    "drop_reason": "duplicate",
                    "hash": digest,
                    "why": "duplicate_content_hash",
                }
            )
            continue
        if digest in seen_hashes and pinned:
            # Pinned duplicate still kept once — skip second pin of identical content.
            early_dropped.append(
                {
                    "item_id": item_id,
                    "kind": str(raw.get("kind") or "other"),
                    "provenance": str(raw.get("provenance") or ""),
                    "tokens": estimate_tokens(content, tokenizer_mode=tok_mode),
                    "drop_reason": "duplicate",
                    "hash": digest,
                    "why": "duplicate_of_already_kept_hash",
                    "pinned": True,
                }
            )
            continue
        seen_hashes.add(digest)

        if not temporal_valid and not pinned:
            early_dropped.append(
                {
                    "item_id": item_id,
                    "kind": str(raw.get("kind") or "other"),
                    "provenance": str(raw.get("provenance") or ""),
                    "tokens": estimate_tokens(content, tokenizer_mode=tok_mode),
                    "drop_reason": "stale",
                    "why": "outside_valid_from_until",
                    "valid_from": raw.get("valid_from"),
                    "valid_until": raw.get("valid_until"),
                }
            )
            continue

        if stale and not pinned:
            # Penalize heavily via freshness; optionally drop when freshness already low.
            pass

        def _score(key: str, *aliases: str, default: float) -> float:
            for name in (key, *aliases):
                if name in raw and raw[name] is not None:
                    try:
                        value = float(raw[name])
                    except (TypeError, ValueError) as exc:
                        raise ValueError(f"invalid {name}") from exc
                    if value != value or value in {float("inf"), float("-inf")}:  # NaN/inf
                        raise ValueError(f"non-finite {name}")
                    if not 0.0 <= value <= 1.0:
                        raise ValueError(f"{name} out of range [0,1]")
                    return value
            return default

        tokens, effective_tokenizer = estimate_tokens_with_mode(content, tokenizer_mode=tok_mode)
        freshness = _score("freshness", default=0.5)
        if stale:
            freshness = min(freshness, 0.15)
            if freshness <= 0.15 and float(raw.get("freshness") or 0.5) <= 0.2 and not pinned:
                early_dropped.append(
                    {
                        "item_id": item_id,
                        "kind": str(raw.get("kind") or "other"),
                        "provenance": str(raw.get("provenance") or ""),
                        "tokens": tokens,
                        "drop_reason": "stale",
                        "why": f"observed_at older than max_age_hours={max_age_hours}",
                        "observed_at": raw.get("observed_at"),
                    }
                )
                continue

        normalized.append(
            {
                "item_id": item_id,
                "kind": str(raw.get("kind") or "other"),
                "content": content,
                "provenance": str(raw.get("provenance") or ""),
                "source": str(raw.get("source") or raw.get("provenance") or "unknown"),
                "reliability": _score("reliability", "confidence", default=0.5),
                "freshness": freshness,
                "usefulness": _score("usefulness", "score", default=0.5),
                "temporal_valid": temporal_valid,
                "tokens": tokens,
                "hash": digest,
                "contradiction_group": str(raw.get("contradiction_group") or ""),
                "pinned": pinned,
                "valid_from": raw.get("valid_from"),
                "valid_until": raw.get("valid_until"),
                "observed_at": raw.get("observed_at"),
                "stale": stale,
            }
        )

    groups: dict[str, list[str]] = {}
    for item in normalized:
        key = item["contradiction_group"] or entity_key(item["content"])
        item["contradiction_group"] = key
        groups.setdefault(key, []).append(item["item_id"])

    contradiction_notes: list[str] = []
    contradiction_clusters: list[dict[str, Any]] = []
    for key, members in groups.items():
        if len(members) < 2:
            continue
        texts = [i["content"].lower() for i in normalized if i["item_id"] in members]
        neg = any("not " in t or "geen " in t or "false" in t or "contradict" in t for t in texts)
        pos = any("is " in t or "wel " in t or "true" in t or "confirms" in t for t in texts)
        if neg and pos:
            contradiction_notes.append(f"group:{key}:{','.join(members)}")
            contradiction_clusters.append(
                {
                    "cluster_id": f"cx_{_sha(key)}",
                    "group_key": key,
                    "item_ids": list(members),
                    "risk": 0.8,
                    "signal": "lexical_negation_vs_affirmation",
                    "method": "lightweight_heuristic",
                    "note": "Heuristic clustering only — not model-quality contradiction resolution.",
                }
            )
            for item in normalized:
                if item["item_id"] in members:
                    item["contradiction_risk"] = 0.8
                    item["contradiction_cluster_id"] = f"cx_{_sha(key)}"
        else:
            for item in normalized:
                if item["item_id"] in members:
                    item["contradiction_risk"] = float(item.get("contradiction_risk") or 0.1)

    def utility(item: dict[str, Any]) -> float:
        diversity_penalty = 0.0
        risk = float(item.get("contradiction_risk") or 0.1)
        pin_boost = 10.0 if item.get("pinned") else 0.0
        score = (
            pin_boost
            + 0.35 * item["usefulness"]
            + 0.25 * item["reliability"]
            + 0.15 * item["freshness"]
            + 0.15 * (1.0 if item["temporal_valid"] else 0.2)
            - 0.20 * risk
            - diversity_penalty
        )
        return score / max(1, item["tokens"])

    # Pinned first, then utility ranking for the rest.
    pinned_items = [i for i in normalized if i.get("pinned")]
    unpinned = [i for i in normalized if not i.get("pinned")]
    ranked = pinned_items + sorted(unpinned, key=utility, reverse=True)

    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = list(early_dropped)
    used = 0
    sources_seen: set[str] = set()
    overflow_notes: list[str] = []
    summary_nodes: list[dict[str, Any]] = []

    for item in ranked:
        src = item["source"]
        cost = int(item["tokens"])
        if used + cost > budget:
            if item.get("pinned"):
                if pin_overflow == "error":
                    raise ValueError(
                        f"mandatory_pin_exceeds_budget:{item['item_id']}:need={cost}:remaining={budget - used}"
                    )
                # F1.8: never silent-drop pins — keep with overflow note.
                kept.append({**item, "overflow_note": "mandatory_pin_exceeds_budget"})
                overflow_notes.append(f"mandatory_pin_kept_over_budget:{item['item_id']}")
                sources_seen.add(src)
                used += cost
                continue
            dropped.append({**item, "drop_reason": "token_budget", "why": "token_budget"})
            continue
        if (
            not item.get("pinned")
            and src in sources_seen
            and used > budget * 0.7
            and item["reliability"] < 0.7
        ):
            dropped.append({**item, "drop_reason": "low_relevance", "why": "source_diversity"})
            continue
        kept.append(item)
        sources_seen.add(src)
        used += cost

    # Hierarchical summarization stub (F1.6): compress budget-dropped (non-pinned) items.
    budget_dropped = [d for d in dropped if d.get("drop_reason") == "token_budget" and not d.get("pinned")]
    if hierarchical_summarization and budget_dropped:
        remaining = max(0, budget - used)
        if remaining >= 32:
            # Prefer items that still have content (from normalized / ranked).
            children = []
            for d in budget_dropped:
                full = next((i for i in ranked if i["item_id"] == d["item_id"]), None)
                if full:
                    children.append(full)
            if children:
                node = _hierarchical_summary_node(
                    children,
                    budget_tokens=remaining,
                    tokenizer_mode=tok_mode,
                    summarize_fn=summarize_fn,
                )
                if used + int(node["tokens"]) <= budget or remaining >= int(node["tokens"]):
                    kept.append(node)
                    summary_nodes.append(node)
                    used += int(node["tokens"])
                    # Mark dropped children as summarized rather than silently lost.
                    for d in dropped:
                        if d.get("item_id") in set(node["provenance_links"]):
                            d["drop_reason"] = "token_budget"
                            d["why"] = "summarized_into_parent"
                            d["summary_item_id"] = node["item_id"]

    # Evidence floor (unchanged behavior) — never evict pins.
    CONTENT_RETURN_LIMIT = 4000

    def _emit_item(i: dict[str, Any]) -> dict[str, Any]:
        full = i["content"]
        truncated = full[:CONTENT_RETURN_LIMIT]
        tokens_full = int(i["tokens"])
        tokens_returned, _ = estimate_tokens_with_mode(truncated, tokenizer_mode=tok_mode) if truncated != full else (tokens_full, effective_tokenizer)
        out = {
            "item_id": i["item_id"],
            "kind": i["kind"],
            "provenance": i["provenance"],
            "source": i["source"],
            "tokens": tokens_returned,
            "tokens_full_content": tokens_full,
            "truncated": truncated != full,
            "utility_per_token": round(utility(i) if not i.get("is_summary_node") else 0.0, 6),
            "content": truncated,
            "contradiction_group": i.get("contradiction_group"),
            "contradiction_risk": i.get("contradiction_risk", 0.1),
            "pinned": bool(i.get("pinned")),
            "why": "pinned_mandatory" if i.get("pinned") else ("summary_node" if i.get("is_summary_node") else "utility_per_token"),
        }
        if i.get("overflow_note"):
            out["overflow_note"] = i["overflow_note"]
        if i.get("provenance_links"):
            out["provenance_links"] = i["provenance_links"]
        if i.get("is_summary_node"):
            out["is_summary_node"] = True
            out["summary_quality"] = i.get("summary_quality") or "stub_not_model_summary"
            if i.get("honesty"):
                out["honesty"] = i["honesty"]
        if i.get("contradiction_cluster_id"):
            out["contradiction_cluster_id"] = i["contradiction_cluster_id"]
        return out

    evidence_kinds = {"knowledge", "evidence", "memory"}
    if kept and not any(i["kind"] in evidence_kinds for i in kept):
        candidate = next((i for i in ranked if i["kind"] in evidence_kinds and i not in kept), None)
        if candidate and candidate["tokens"] <= budget:
            while used + candidate["tokens"] > budget and kept:
                victim = kept[-1]
                if victim.get("pinned") or victim.get("is_summary_node"):
                    break
                kept.pop()
                used -= int(victim["tokens"])
                dropped.append({**victim, "drop_reason": "token_budget", "why": "evicted_for_evidence_floor"})
            if used + candidate["tokens"] <= budget and candidate not in kept:
                kept.append(candidate)
                used += int(candidate["tokens"])

    # Finalize drop taxonomy for message metadata.
    for row in dropped:
        original = str(row.get("drop_reason") or row.get("why") or "")
        row["drop_reason_raw"] = original
        row["drop_reason"] = canonicalize_drop_reason(original)
        if not row.get("why"):
            row["why"] = row["drop_reason"]

    mandatory_dropped = [
        d
        for d in dropped
        if d.get("pinned")
        and canonicalize_drop_reason(str(d.get("drop_reason") or d.get("why") or "")) != "duplicate"
    ]
    evidence_status = "insufficient_evidence" if mandatory_dropped or pin_errors else "ok"

    returned_used = sum(
        estimate_tokens(i["content"][:CONTENT_RETURN_LIMIT], tokenizer_mode=tok_mode) for i in kept
    )
    canonical_drop_reasons = sorted({str(i.get("drop_reason") or "") for i in dropped if i.get("drop_reason")})
    pack_preview = {
        "kept": [i["item_id"] for i in kept],
        "dropped": [
            {"item_id": i.get("item_id"), "why": i.get("why") or i.get("drop_reason"), "drop_reason": i.get("drop_reason")}
            for i in dropped
        ],
        "why": {
            "rank_key": "utility_per_token_with_pin_priority",
            "drop_reasons": canonical_drop_reasons,
            "overflow_notes": overflow_notes,
            "summary_nodes": [n["item_id"] for n in summary_nodes],
            "evidence_status": evidence_status,
        },
        "tokenizer": effective_tokenizer,
        "budget": budget,
    }
    pack = {
        "goal": goal,
        "run_id": run_id,
        "tokenizer": effective_tokenizer,
        "tokenizer_mode_requested": tok_mode,
        "tokenizer_estimate": effective_tokenizer != "tiktoken_cl100k",
        "not_provider_billing": True,
        "token_accounting": (
            "tiktoken_cl100k"
            if effective_tokenizer == "tiktoken_cl100k"
            else (
                "whitespace_words"
                if effective_tokenizer == "whitespace_words"
                else "local_estimate_chars_div_4_not_provider_billing"
            )
        ),
        "max_tokens": budget,
        "used_tokens": returned_used,
        "used_tokens_pre_truncation": used,
        "budget_reserve_note": reserve_note,
        "budget_reserve": reserve_detail,
        "selection_explain": {
            "rank_key": "utility_per_token_with_pin_priority",
            "kept_ids": [i["item_id"] for i in kept],
            "drop_reasons": canonical_drop_reasons,
            "source_diversity": len({i["source"] for i in kept}),
            "contradiction_groups": contradiction_notes,
            "contradiction_clusters": contradiction_clusters,
            "overflow_notes": overflow_notes,
            "tokenizer": effective_tokenizer,
            "budget": budget,
            "max_age_hours": max_age_hours,
            "hierarchical_summarization": hierarchical_summarization,
            "evidence_status": evidence_status,
        },
        "evidence_status": evidence_status,
        "contradiction_clusters": contradiction_clusters,
        "pack_preview": pack_preview,
        "kept": [_emit_item(i) for i in kept],
        "dropped": [
            {
                "item_id": i["item_id"],
                "kind": i.get("kind"),
                "provenance": i.get("provenance"),
                "tokens": i.get("tokens"),
                "drop_reason": i.get("drop_reason"),
                "why": i.get("why") or i.get("drop_reason"),
                "hash": i.get("hash"),
                "summary_item_id": i.get("summary_item_id"),
                "pinned": i.get("pinned"),
            }
            for i in dropped
        ],
        "metrics": {
            "kept_count": len(kept),
            "dropped_count": len(dropped),
            "source_diversity": len({i["source"] for i in kept}),
            "contradiction_groups": contradiction_notes,
            "contradiction_cluster_count": len(contradiction_clusters),
            "fill_ratio": round(returned_used / max(1, budget), 4),
            "pinned_kept": sum(1 for i in kept if i.get("pinned")),
            "summary_nodes": len(summary_nodes),
            "hierarchical_summarization_stub": any(
                n.get("summary_quality") == "stub_not_model_summary" for n in summary_nodes
            ),
            "hierarchical_summarization_model": any(
                n.get("summary_quality") == "model_summary" for n in summary_nodes
            ),
            "overflow_notes": overflow_notes,
            "effective_tokenizer": effective_tokenizer,
            "tokenizer_mode": tok_mode,
            "tokenizer_estimate": effective_tokenizer != "tiktoken_cl100k",
        },
        "pin_errors": pin_errors,
    }
    if persist:
        return store.save_context_pack(pack)
    pack["id"] = new_id("ctx")
    pack["created_at"] = utc_now()
    return pack


def chat_compiler_enabled(*, opt_in: bool | None = None, env: dict[str, str] | None = None) -> bool:
    """Default OFF. Enable only via explicit opt_in or HADES_CONTEXT_COMPILER_CHAT=1."""
    if opt_in is True:
        return True
    if opt_in is False:
        return False
    source = env if env is not None else __import__("os").environ
    flag = str(source.get("HADES_CONTEXT_COMPILER_CHAT") or "").strip().lower()
    return flag in {"1", "true", "yes", "on"}


def compile_for_chat_path(
    store: Gen2Store,
    *,
    goal: str,
    items: list[dict[str, Any]],
    max_tokens: int = 2048,
    opt_in: bool | None = None,
    env: dict[str, str] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Optional chat-path wiring — never replaces the default retrieval path unless opted in.

    Returns ``{enabled: False, used_compiler: False, ...}`` when the feature flag is off so
    callers can keep the existing context path unchanged.
    """
    if not chat_compiler_enabled(opt_in=opt_in, env=env):
        return {
            "enabled": False,
            "used_compiler": False,
            "default_path_preserved": True,
            "note": "Context Compiler chat-path is opt-in only (HADES_CONTEXT_COMPILER_CHAT or opt_in=True).",
            "items_passthrough": items,
            "goal": goal,
        }
    pack = compile_context(
        store,
        goal=goal,
        items=items,
        max_tokens=max_tokens,
        **kwargs,
    )
    return {
        "enabled": True,
        "used_compiler": True,
        "default_path_preserved": False,
        "pack": pack,
        "note": "Compiler engaged via explicit opt-in / feature flag.",
    }

def shadow_compare(
    *,
    query: str,
    legacy_chunks: list[dict[str, Any]],
    compiler_chunks: list[dict[str, Any]] | None = None,
    max_tokens: int | None = 1200,
) -> dict[str, Any]:
    """Offline A/B comparison of legacy vs compiler selection (no user-visible answer change).

    Does not invoke a model. Reports coverage/size proxies only — not live quality.
    """
    import tempfile
    from pathlib import Path

    goal = str(query or "").strip()
    legacy = list(legacy_chunks or [])
    if compiler_chunks is None:
        with tempfile.TemporaryDirectory(prefix="cc_shadow_") as tmp:
            store = Gen2Store(str(Path(tmp) / "shadow.db"))
            pack = compile_context(store, goal=goal, items=legacy, max_tokens=max_tokens)
            selected = list((pack or {}).get("items") or (pack or {}).get("selected") or [])
    else:
        selected = list(compiler_chunks)
        pack = {"items": selected, "note": "caller_supplied_compiler_chunks"}

    def _coverage(chunks: list[dict[str, Any]]) -> float:
        if not goal:
            return 0.0
        tokens = {t for t in goal.lower().split() if len(t) > 2}
        if not tokens:
            return 0.0
        hit = 0
        for ch in chunks:
            text = str(ch.get("text") or ch.get("content") or "").lower()
            hit += sum(1 for t in tokens if t in text)
        return round(min(1.0, hit / max(1, len(tokens))), 4)

    legacy_cov = _coverage(legacy)
    compiler_cov = _coverage(selected)
    return {
        "mode": "shadow",
        "not_model_quality": True,
        "query": goal,
        "legacy_chunk_count": len(legacy),
        "compiler_chunk_count": len(selected),
        "legacy_coverage_proxy": legacy_cov,
        "compiler_coverage_proxy": compiler_cov,
        "coverage_delta": round(compiler_cov - legacy_cov, 4),
        "default_path_unchanged": True,
        "pack_note": (pack or {}).get("note"),
        "metric_kind": "lexical_token_overlap_proxy",
    }



"""Bounded creative pipeline: ideas, hypothesis, script critics, storyboard."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Callable

from media.intelligence.patterns import analyze_transcript_pattern

LLMCallable = Callable[[str, str], str]


def _simple_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def originality_similarity(a: str, b: str) -> float:
    """Lightweight token Jaccard similarity (0..1)."""
    ta = set(re.findall(r"[a-z0-9']+", (a or "").lower()))
    tb = set(re.findall(r"[a-z0-9']+", (b or "").lower()))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


class CreativePipeline:
    def __init__(self, store: Any, *, llm: LLMCallable | None = None, max_repair_rounds: int = 2) -> None:
        self.store = store
        self.llm = llm
        self.max_repair_rounds = max(1, min(int(max_repair_rounds), 3))

    def generate_ideas(self, *, channel: dict[str, Any], opportunity: dict[str, Any], trend: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        topic = (trend or {}).get("display_topic") or channel.get("niche") or "general interest"
        niche = channel.get("niche") or "general"
        base_hooks = [
            ("contradiction", f"Everyone believes {topic} worked one way — the evidence says otherwise."),
            ("question", f"Why did {topic} disappear from textbooks?"),
            ("curiosity_gap", f"There's a detail about {topic} almost nobody notices."),
        ]
        ideas = []
        for idx, (hook_type, hook) in enumerate(base_hooks):
            payload = {
                "topic": topic,
                "angle": f"{niche} angle #{idx + 1}",
                "hook": hook,
                "hook_type": hook_type,
                "format": "mystery_reveal" if hook_type == "contradiction" else "explainer",
                "target_viewer": channel.get("target_audience") or "curious general audience",
                "reason": opportunity.get("explanation") or "Ranked from opportunity evidence.",
                "evidence": {"opportunity_id": opportunity.get("id"), "score": opportunity.get("score")},
                "predicted_strengths": [hook_type, "evidence_backed"],
                "risk": "low" if (opportunity.get("score") or 0) >= 60 else "moderate",
                "production_cost": "low",
                "originality": "pattern_based_not_verbatim",
                "platform_suitability": channel.get("platforms") or [],
            }
            # Reject near-duplicates against existing ideas.
            existing = self.store.list_ideas(channel_id=channel.get("id"), limit=30)
            duplicate = False
            for prior in existing:
                if originality_similarity(hook, str((prior.get("payload") or {}).get("hook") or "")) >= 0.85:
                    duplicate = True
                    break
            idea = self.store.create_idea(
                {
                    "channel_id": channel.get("id"),
                    "opportunity_id": opportunity.get("id"),
                    "payload": payload,
                    "rank_score": float(opportunity.get("score") or 0) - idx * 3,
                    "rejected": duplicate,
                }
            )
            if not duplicate:
                ideas.append(idea)
        ideas.sort(key=lambda i: float(i.get("rank_score") or 0), reverse=True)
        return ideas

    def form_hypothesis(self, *, project_id: str, channel: dict[str, Any], idea: dict[str, Any]) -> dict[str, Any]:
        payload_idea = idea.get("payload") or {}
        hypothesis = {
            "audience": channel.get("target_audience") or "general",
            "observation": "Contradiction hooks often outperform pure questions on factual niches (channel learning pending).",
            "hypothesis": (
                f"Opening with a {payload_idea.get('hook_type', 'curiosity')} hook on "
                f"{payload_idea.get('topic', 'topic')} will improve early retention."
            ),
            "format": payload_idea.get("format", "explainer"),
            "primary_success_metric": "average_view_percentage",
            "idea_id": idea.get("id"),
        }
        return self.store.save_hypothesis(project_id, hypothesis)

    def write_script(
        self,
        *,
        project_id: str,
        channel: dict[str, Any],
        idea: dict[str, Any],
        research_claims: list[dict[str, Any]],
        prior_scripts: list[str] | None = None,
        source_transcripts: list[str] | None = None,
    ) -> dict[str, Any]:
        idea_payload = idea.get("payload") or {}
        topic = idea_payload.get("topic") or channel.get("niche") or "this topic"
        claims = [c for c in research_claims if (c.get("confidence") or 0) >= 0.4 or c.get("evidence")]
        claim_lines = []
        for claim in claims[:5]:
            claim_lines.append(f"- {claim.get('claim')} (evidence: {claim.get('source_ref') or 'internal'})")
        if not claim_lines:
            claim_lines.append("- Stick to non-controversial framing until stronger evidence exists.")

        draft = (
            f"{idea_payload.get('hook') or f'Here is something unexpected about {topic}.'}\n\n"
            f"Most people think they understand {topic}. The interesting part is what the evidence actually shows.\n\n"
            + "\n".join(claim_lines)
            + f"\n\nSo the takeaway is simple: {topic} rewards curiosity more than certainty.\n"
            f"If you want more evidence-backed stories like this, follow for the next one."
        )
        if self.llm is not None:
            prompt = (
                "Write an original short-form narration script. Learn patterns, do not copy sources. "
                f"Topic: {topic}. Hook type: {idea_payload.get('hook_type')}. "
                f"Claims:\n" + "\n".join(claim_lines)
            )
            try:
                draft = self.llm("script_writer", prompt).strip() or draft
            except Exception:
                pass

        critiques: list[dict[str, Any]] = []
        body = draft
        for round_idx in range(self.max_repair_rounds):
            retention = self._retention_critic(body)
            facts = self._fact_critic(body, claims)
            originality = self._originality_critic(body, prior_scripts or [], source_transcripts or [])
            critiques.append(
                {
                    "round": round_idx + 1,
                    "retention": retention,
                    "facts": facts,
                    "originality": originality,
                }
            )
            issues = retention.get("issues", []) + facts.get("issues", []) + originality.get("issues", [])
            if not issues:
                break
            body = self._repair(body, issues)
        return self.store.save_script(project_id, body, critiques=critiques)

    def _retention_critic(self, script: str) -> dict[str, Any]:
        pattern = analyze_transcript_pattern(script)
        issues = []
        first_line = (script.strip().splitlines() or [""])[0]
        if len(first_line) < 12:
            issues.append("weak_first_second")
        if not pattern["hook"].get("curiosity_gap") and pattern["hook"].get("hook_type") == "statement":
            issues.append("flat_hook")
        if pattern["script"]["word_count"] < 40:
            issues.append("too_short")
        if not pattern["structure"].get("cta_present"):
            issues.append("missing_cta")
        return {"ok": not issues, "issues": issues, "pattern": pattern}

    def _fact_critic(self, script: str, claims: list[dict[str, Any]]) -> dict[str, Any]:
        issues = []
        # Flag absolute claims without evidence markers when no research claims exist.
        if re.search(r"\b(always|never|proven|scientists say|studies show)\b", script, re.I) and not claims:
            issues.append("unsupported_absolute_claim")
        for claim in claims:
            if (claim.get("confidence") or 0) < 0.35 and claim.get("claim") and claim["claim"].lower() in script.lower():
                issues.append(f"weak_claim_used:{claim.get('id')}")
        return {"ok": not issues, "issues": issues}

    def _originality_critic(self, script: str, prior_scripts: list[str], source_transcripts: list[str]) -> dict[str, Any]:
        issues = []
        for prior in prior_scripts:
            sim = originality_similarity(script, prior)
            if sim >= 0.72:
                issues.append(f"too_similar_prior:{sim:.2f}")
        for source in source_transcripts:
            sim = originality_similarity(script, source)
            if sim >= 0.55:
                issues.append(f"too_similar_source:{sim:.2f}")
        return {"ok": not issues, "issues": issues, "hash": _simple_hash(script)[:16]}

    def _repair(self, script: str, issues: list[str]) -> str:
        body = script
        if any(i.startswith("too_similar") for i in issues):
            body = "Here's a fresher angle.\n\n" + body
        if "missing_cta" in issues and "follow" not in body.lower():
            body = body.rstrip() + "\n\nFollow for the next evidence-backed story."
        if "flat_hook" in issues:
            body = "Most people get this wrong.\n\n" + body
        if "unsupported_absolute_claim" in issues:
            body = re.sub(r"\b(always|never|proven)\b", "often", body, flags=re.I)
            body = re.sub(r"\b(scientists say|studies show)\b", "some sources suggest", body, flags=re.I)
        if self.llm is not None:
            try:
                repaired = self.llm("final_writer", f"Repair only these issues {issues}:\n{body}")
                if repaired and len(repaired.strip()) > 40:
                    return repaired.strip()
            except Exception:
                pass
        return body

    def storyboard_from_script(self, *, project_id: str, script: str, target_duration: float = 45.0) -> dict[str, Any]:
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", script.strip()) if s.strip()]
        if not sentences:
            sentences = [script.strip() or "Placeholder narration."]
        n = len(sentences)
        slice_dur = max(1.5, float(target_duration) / n)
        scenes = []
        t = 0.0
        for idx, sentence in enumerate(sentences):
            start = round(t, 2)
            end = round(t + slice_dur, 2)
            t = end
            scenes.append(
                {
                    "scene_id": f"s{idx + 1}",
                    "start": start,
                    "end": end,
                    "narration": sentence,
                    "caption_text": sentence,
                    "visual_goal": "support narration",
                    "visual_description": f"Visual supporting: {sentence[:80]}",
                    "image_prompt": f"Documentary still, clear subject, no logos, illustrating: {sentence[:100]}",
                    "video_prompt": "",
                    "camera_motion": "slow_zoom",
                    "transition": "cut" if idx == 0 else "crossfade",
                    "sfx": "",
                    "music_intensity": 0.4,
                    "source_requirement": "none",
                    "asset_strategy": "GENERATED_IMAGE" if idx % 3 else "TEXT_GRAPHICS",
                }
            )
        # Validate coverage / timing
        if scenes and abs(scenes[-1]["end"] - target_duration) > 2.0:
            scenes[-1]["end"] = round(max(scenes[-1]["start"] + 1.0, target_duration), 2)
        return self.store.save_storyboard(project_id, scenes)

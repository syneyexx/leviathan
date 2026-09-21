from __future__ import annotations

import re
from typing import Any, Literal

from .autonomy_policies import stop_and_ask_gate
from .contracts import ReasoningProfileName, RequestKind, RequestSpec, RouteDecision, TaskFeatures
from .mode_policy import POLICY_VERSION, parse_mode_input, profile_config_key


_CODE_MARKERS = ("```", "traceback", "exception", "def ", "class ", "npm ", "pytest", "unittest")
_RESEARCH_MARKERS = (
    "research", "onderzoek", "zoek op", "zoek naar", "bronnen", "evidence",
    "actueel", "actuele", "laatste", "nieuws", "compare", "vergelijk",
    "vandaag", "today", "huidige prijs", "current price",
)
_PLAN_MARKERS = ("plan", "stappen", "roadmap", "architectuur", "ontwerp", "migreer", "implementeer")
_TOOL_EXECUTE_MARKERS = (
    "voer uit", "run ", "installeer", "start service", "roep de tool",
    "gebruik de plugin", "gebruik de tool", "execute ", "delete ", "verwijder ",
    # Dutch/English "use <plugin|tool|named capability>" — negated via _NO_TOOLS / explain paths.
    "gebruik ", "use plugin", "use the plugin", "use tool", "use the tool", "invoke ",
)
# Imperative workspace/core-tool actions (not explanations). Keep phrases specific so
# "wat is een bestand?" stays conversational while "lees bestand X" can use tools.
# Document/attachment conversion & mutation phrases must keep the tool plane available
# even when short NL would otherwise look like simple_direct chat.
_WORKSPACE_ACTION_MARKERS = (
    "lees bestand",
    "lees het bestand",
    "read file",
    "read the file",
    "open file",
    "open the file",
    "toon inhoud van",
    "show contents of",
    "schrijf naar",
    "write to file",
    "write file",
    "controleer deze repository",
    "controleer de repository",
    "check this repository",
    "check the repository",
    "inspect this repository",
    "inspect the repository",
    # PDF / document → markdown (and similar) conversion.
    "om naar markdown",
    "om naar md",
    "naar markdown",
    "naar .md",
    ".md bestand",
    "converteer ",
    "converteer de",
    "converteer dit",
    "converteer deze",
    "convert to markdown",
    "convert to md",
    "convert this",
    "convert the pdf",
    "convert the document",
    "pdf om naar",
    "zet deze pdf",
    "zet dit document",
    "zet deze om naar",
    "maak van dit document",
    "maak van deze pdf",
    "maak van deze bijlage",
    "maak van dit bestand",
    # Attachment / file mutation / knowledge ingest.
    "lees deze bijlage",
    "lees de bijlage",
    "read this attachment",
    "read the attachment",
    "sla de inhoud op",
    "sla inhoud op",
    "save the contents",
    "save the content",
    "pas dit bestand aan",
    "pas het bestand aan",
    "pas dit file aan",
    "edit this file",
    "modify this file",
    "change this file",
    "download de pagina",
    "download the page",
    "naar knowledge",
    "in knowledge",
    "into knowledge",
    "zet in knowledge",
    "zet hem in knowledge",
)
_PLUGIN_NOUN_RE = re.compile(r"\b(plugin|plugins|tool|tools|mcp)\b")
_PLUGIN_VERB_RE = re.compile(r"\b(gebruik|aanroep|invoke|uitvoer|run|roep)\w*\b")


def wants_plugin_execution(text: str) -> bool:
    """True when the user asks Chat to actually invoke a plugin/tool (any word order).

    Catches follow-ups like "daadwerkelijk de plugin gebruiken" that miss the older
    "gebruik de plugin" prefix and would otherwise stay a question with tools off.
    """
    lower = (text or "").lower()
    if not lower.strip() or any(p in lower for p in _NO_TOOLS):
        return False
    if _is_explanation_request(lower) or _has_negated_execution(lower):
        return False
    if _dutch_voer_uit(lower):
        return True
    if re.search(r"\buse (?:a |the |this |een )?(?:plugin|tool|mcp)\b", lower):
        return True
    if "daadwerkelijk" in lower and _PLUGIN_NOUN_RE.search(lower):
        return True
    verb = _PLUGIN_VERB_RE.search(lower)
    noun = _PLUGIN_NOUN_RE.search(lower)
    if not verb or not noun:
        return False
    span = abs(verb.start() - noun.start())
    return span <= 48
_MEMORY_WRITE_MARKERS = (
    "onthoud dit", "remember this", "remember that", "voortaan",
    "sla op in memory", "bewaar dit", "onthoud:", "remember:",
)
_MEMORY_NEGATION = (
    "onthoud dit niet", "onthoud dat niet", "don't remember", "do not remember",
    "niet onthouden", "vergeet dit", "don't save", "niet bewaren",
)
_DEBUG_MARKERS = ("debug", "fout", "bug", "werkt niet", "stacktrace", "faalt", "error", "waarom faalt")
_ANALYSIS_MARKERS = ("analyseer", "analyse", "beoordeel", "review", "leg uit waarom", "trade-off")
_EXPLAIN_MARKERS = (
    "leg uit", "uitleggen", "explain", "wat doet", "what does", "wat is", "what is",
    "waarom", "why ", "hoe werkt", "how does", "betekenis", "meaning of",
    "walk me through", "walk through", "houd me door", "licht toe",
)
_NEGATED_EXECUTE = (
    "do not execute", "don't execute", "dont execute", "niet uitvoeren",
    "do not run", "don't run", "dont run", "niet draaien", "niet starten",
    "do not invoke", "don't invoke", "geen uitvoering", "zonder uit te voeren",
    "without executing", "without running", "do not execute anything",
)
_COMPARE_MARKERS = ("vergelijk", "compare", " versus ", " vs ", "verschil tussen", "difference between")
_HYPOTHETICAL = ("stel dat", "suppose ", "what if", "wat als", "hypothetisch", "imaginary")
_FOLLOW_UP = (
    "waarom faalt dit", "why does this fail", "en daarna", "and then", "zoals hierboven",
    "as above", "dat", "dit", "that", "this", "dezelfde", "the same", "hetzelfde",
    "nog eens", "same again", "doe hetzelfde", "do the same",
    # Status/progress probes inherit prior work context (see status_markers below).
    "wat is de status", "hoe staat het", "wat is de stand", "voortgang",
)
_EXECUTE_NOW = (
    "voer dat nu uit", "voer het nu uit", "voer dit nu uit", "run that now",
    "execute that now", "doe dat nu", "nu uitvoeren",
)
_CORRECTION = (
    "corrigeer", "correctie", "eigenlijk", "actually", "niet meer", "in plaats van",
    "ik bedoelde", "i meant", "correction:",
)
_NO_TOOLS = (
    "gebruik geen tools", "geen tools", "without tools", "don't use tools",
    "do not use tools", "no tools", "zonder tools", "zonder plugins",
)
_NO_WEB = (
    "niet online zoeken", "niet op internet", "geen internet", "zonder internet",
    "alleen lokaal", "local only", "offline only", "don't search online",
    "do not search online", "no web", "geen web", "zonder web", "alleen deze bijlage",
    "only this attachment", "only these attachments", "don't go online",
)


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        key = item.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item.strip())
    return result


def _strip_quoted_spans(text: str) -> tuple[str, list[str]]:
    """Remove quoted regions so cited instructions are not treated as current intent."""
    quotes: list[str] = []
    pattern = re.compile(r"[\"“”]([^\"“”]{3,200})[\"“”]|'([^']{3,200})'|`([^`]{3,200})`")
    def _keep(match: re.Match[str]) -> str:
        quotes.append(match.group(0))
        return " "
    cleaned = pattern.sub(_keep, text)
    return cleaned, quotes


def _has_negated_phrase(text: str, phrases: tuple[str, ...]) -> bool:
    lower = text.lower()
    for phrase in phrases:
        if phrase in lower:
            return True
    # Generic "niet/nooit/don't + action" near tool/memory verbs
    if re.search(r"\b(niet|nooit|don't|do not|geen)\b.{0,24}\b(tool|plugin|onthoud|remember|verwijder|delete|run)\b", lower):
        return True
    return False


def _is_explanation_request(text: str) -> bool:
    lower = text.lower().strip()
    if any(marker in lower for marker in _EXPLAIN_MARKERS):
        return True
    if re.search(r"\b(leg|explain|beschrijf|uitleg)\b.+\b(doe|doet|does|delete|verwijder|command|opdracht)\b", lower):
        return True
    if re.search(r"\b(kun je|can you)\s+(uitleggen|explain)\b", lower):
        return True
    if re.search(r"\bwalk(?:\s+me)?\s+through\b", lower):
        return True
    if "explanation only" in lower or "alleen uitleg" in lower or "only explain" in lower:
        return True
    return False


def _has_negated_execution(text: str) -> bool:
    """True when the user explicitly forbids execution/running tools."""
    lower = text.lower()
    if any(p in lower for p in _NEGATED_EXECUTE):
        return True
    if re.search(
        r"\b(niet|nooit|don't|do not|geen|without)\b.{0,32}\b(uitvoer|execute|run|invoke|start)\w*\b",
        lower,
    ):
        return True
    return False


def _dutch_voer_uit(text: str) -> bool:
    """Catch 'voer X uit' even when words intervene (Voer dat nu uit)."""
    lower = text.lower()
    if any(p in lower for p in _EXECUTE_NOW):
        return True
    return bool(re.search(r"\bvoer\b.{0,40}\buit\b", lower))


def _is_choice_question(text: str) -> bool:
    lower = text.lower()
    return bool(re.search(r"\b(\w+)\s+of\s+(\w+)\b", lower) and "?" in text)


_DEPENDENCY_MARKERS = (
    "daarna", "vervolgens", "eerst ", "then ", "after that", "depends",
    "afhankelijk", "zodra", "before ", "nadat", "multi-step", "meerdere stappen",
    "opeenvolgend", "in volgorde",
)


def _has_step_dependency_markers(lower: str) -> bool:
    return any(marker in lower for marker in _DEPENDENCY_MARKERS)


def _count_independent_outcomes(text: str) -> int:
    """Cheap count of distinct asked results. Not a calibrated difficulty score."""
    numbered = len(re.findall(r"(?:^|\n)\s*(?:\d+[\.\)]|- |\* )\s+\S", text))
    questions = text.count("?")
    conjunctions = len(re.findall(r"\b(?:en daarna|and then|also implement|also add|tevens)\b", text.lower()))
    return max(1, numbered, questions, 1 + conjunctions)


def _extract_constraints(text: str) -> list[str]:
    constraints: list[str] = []
    patterns = [
        r"(?:niet|nooit|don't|do not|vermijd)\s+([^\.\n]{3,120})",
        r"(?:alleen|only|must|moet)\s+([^\.\n]{3,120})",
        r"(?:zonder|without)\s+([^\.\n]{3,80})",
        r"(?:windows|linux|offline|local-first|geen cloud)[^\.\n]{0,80}",
    ]
    lower = text.lower()
    for pattern in patterns:
        for match in re.finditer(pattern, lower, flags=re.I):
            constraints.append(match.group(0).strip())
    if "windows" in lower:
        constraints.append("Windows first-class behouden")
    if "offline" in lower or "local-first" in lower or "lokaal" in lower:
        constraints.append("Local-first / offline-core respecteren")
    if _has_negated_phrase(text, _NO_TOOLS) or any(p in lower for p in _NO_TOOLS):
        constraints.append("Geen tools gebruiken")
    if _has_negated_execution(text):
        constraints.append("Geen uitvoering / niet uitvoeren")
    if _has_negated_phrase(text, _NO_WEB) or any(p in lower for p in _NO_WEB):
        constraints.append("Geen web / alleen lokaal")
    return _unique(constraints)[:12]


def detect_speech_act(text: str, *, working_text: str | None = None) -> str:
    sample = (working_text or text).lower().strip()
    # Explicit no-execution / explanation wins over execute markers (false-execution safety).
    if _has_negated_execution(sample) and _is_explanation_request(sample):
        return "explain"
    if _has_negated_execution(sample) and not _dutch_voer_uit(sample):
        # "don't execute / explain the risk" — not an execute grant.
        if _is_explanation_request(sample) or any(m in sample for m in _EXPLAIN_MARKERS):
            return "explain"
    # "actually use a plugin" is emphasis, not a correction of the previous answer.
    if any(m in sample for m in _CORRECTION) and not wants_plugin_execution(sample):
        # Prefer explain when correction coexists with explicit explain / no-execute.
        if _is_explanation_request(sample) or _has_negated_execution(sample):
            return "explain"
        return "correct"
    if _is_explanation_request(sample):
        return "explain"
    if any(m in sample for m in _COMPARE_MARKERS):
        return "compare"
    if _is_choice_question(text) or sample.startswith(("moeten we", "should we", "shall we")):
        return "question"
    if any(m in sample for m in _HYPOTHETICAL):
        return "hypothetical"
    if any(m in sample for m in _NO_TOOLS) or _has_negated_phrase(sample, ("tool", "plugin")):
        if any(m in sample for m in _TOOL_EXECUTE_MARKERS) and not _is_explanation_request(sample):
            # Explicit execute markers without explanation still execute unless negated.
            pass
        elif any(p in sample for p in _NO_TOOLS):
            return "question" if "?" in text else "inform"
    if _has_negated_execution(sample):
        return "question" if "?" in text else "inform"
    if _dutch_voer_uit(sample) and not _is_explanation_request(sample):
        return "execute"
    if any(m in sample for m in _TOOL_EXECUTE_MARKERS) and not _is_explanation_request(sample):
        # Ignore execute markers that appear only inside a negation span.
        if not _has_negated_execution(sample):
            return "execute"
    if any(m in sample for m in _WORKSPACE_ACTION_MARKERS) and not _is_explanation_request(sample):
        if not _has_negated_execution(sample):
            return "execute"
    if wants_plugin_execution(sample) and not _is_explanation_request(sample):
        return "execute"
    if "?" in text:
        return "question"
    return "inform"


def classify_request_kind(text: str) -> RequestKind:
    working, _quotes = _strip_quoted_spans(text)
    lower = working.lower()
    speech = detect_speech_act(text, working_text=working)

    # Negated memory write is not a memory_write request.
    if any(m in lower for m in _MEMORY_NEGATION) or (
        "onthoud" in lower and re.search(r"\b(niet|nooit|don't|do not)\b", lower)
    ):
        pass  # fall through — not memory_write
    elif any(marker in lower for marker in _MEMORY_WRITE_MARKERS):
        return "memory_write"

    if speech == "explain":
        # Explanation of a delete command is analysis/question, not tool_use/high-risk execute.
        if any(marker in lower for marker in _DEBUG_MARKERS) or "traceback" in lower:
            return "debug"
        if any(marker in lower for marker in _CODE_MARKERS):
            return "analysis"
        return "analysis" if len(text) > 80 else "question"

    if any(marker in lower for marker in _DEBUG_MARKERS) or "traceback" in lower:
        return "debug"
    if any(marker in lower for marker in _CODE_MARKERS) or "refactor" in lower:
        return "code"
    if any(marker in lower for marker in _RESEARCH_MARKERS):
        return "research"

    # Tool / plugin execution before plan markers — "meerdere stappen" alone must not
    # demote an explicit plugin invoke into planning.
    wants_no_tools = (
        any(p in lower for p in _NO_TOOLS)
        or _has_negated_execution(lower)
        or "explanation only" in lower
        or "alleen uitleg" in lower
    )
    if not wants_no_tools and speech == "execute" and (
        any(marker in lower for marker in _TOOL_EXECUTE_MARKERS)
        or any(marker in lower for marker in _WORKSPACE_ACTION_MARKERS)
        or _dutch_voer_uit(lower)
    ):
        return "tool_use"
    if not wants_no_tools and speech != "explain" and wants_plugin_execution(lower):
        return "tool_use"
    if (
        not wants_no_tools
        and speech != "explain"
        and any(marker in lower for marker in ("gebruik plugin", "gebruik tool", "gebruik ", "use plugin", "use tool"))
    ):
        return "tool_use"
    if (
        not wants_no_tools
        and speech != "explain"
        and any(m in lower for m in ("meerdere stappen", "multi-step", "meerdere tools"))
        and any(m in lower for m in ("gebruik", "run ", "voer uit", "invoke"))
    ):
        return "tool_use"

    if any(marker in lower for marker in _PLAN_MARKERS) and (
        len(text) > 48
        or lower.startswith("plan ")
        or "migration" in lower
        or "migreer" in lower
        or "roadmap" in lower
    ):
        return "planning"

    if any(marker in lower for marker in _ANALYSIS_MARKERS) or speech == "compare":
        return "analysis"
    if "?" in text and len(text) < 280:
        return "question"
    if len(text) < 48 and not any(ch in text for ch in "{};"):
        return "chat"
    # Length / newline count is a cheap hint, not a multi-step verdict.
    if (
        speech not in {"explain", "question", "hypothetical"}
        and _has_step_dependency_markers(lower)
        and _count_independent_outcomes(text) >= 2
    ):
        return "multi_step"
    return "question"


def build_request_spec(
    text: str,
    *,
    prior_failures: int = 0,
    conversation_state: dict[str, Any] | None = None,
) -> RequestSpec:
    working, quoted = _strip_quoted_spans(text)
    kind = classify_request_kind(text)
    lower = working.lower()
    speech = detect_speech_act(text, working_text=working)
    constraints = _extract_constraints(working)

    wants_no_tools = (
        any(p in lower for p in _NO_TOOLS)
        or "Geen tools gebruiken" in constraints
        or _has_negated_execution(lower)
        or "explanation only" in lower
        or "alleen uitleg" in lower
    )
    wants_no_web = any(p in lower for p in _NO_WEB) or "Geen web / alleen lokaal" in constraints
    plugin_intent = wants_plugin_execution(working) or (
        speech == "execute" and _dutch_voer_uit(lower) and bool(state.get("pending_tool") or state.get("last_assistant"))
        if (state := (conversation_state or {}))
        else False
    )
    # Elliptical "voer dat nu uit" with prior pending tool → tools required.
    pending_followup_exec = bool(
        (conversation_state or {}).get("pending_tool")
        and speech == "execute"
        and not wants_no_tools
    )
    needs_tools = (
        not wants_no_tools
        and (
            kind in {"tool_use", "code", "debug", "multi_step"}
            or plugin_intent
            or pending_followup_exec
            or (speech == "execute" and _dutch_voer_uit(lower) and bool((conversation_state or {}).get("pending_tool") or (conversation_state or {}).get("last_assistant")))
        )
        and speech != "explain"
    )
    needs_research = (
        not wants_no_web
        and (kind == "research" or any(m in lower for m in _RESEARCH_MARKERS))
    )
    needs_plan = kind in {"planning", "multi_step", "code"} or (
        kind == "research" and _has_step_dependency_markers(lower)
    )
    needs_memory_write = kind == "memory_write"

    # "A of B?" is a choice question — medium ambiguity at most, not an automatic stop.
    if _is_choice_question(text) and speech in {"question", "compare", "inform"}:
        ambiguity: Literal["low", "medium", "high"] = "medium"
    elif text.count("?") > 3 and len(constraints) > 2:
        ambiguity = "high"
    elif len(constraints) > 3:
        ambiguity = "medium"
    else:
        ambiguity = "low"

    # Explanation of dangerous actions is not high operational risk.
    dangerous_tokens = ("prod", "productie", "delete", "verwijder", "drop ", "rm -", "kill")
    mentions_danger = any(token in lower for token in dangerous_tokens)
    if speech == "explain" or speech == "hypothetical":
        risk: Literal["low", "medium", "high"] = "low"
    elif mentions_danger and speech == "execute":
        risk = "high"
    elif needs_tools or needs_research:
        risk = "medium"
    else:
        risk = "low"

    acceptance: list[str] = []
    if needs_plan:
        acceptance.append("Concrete stappen of resultaat met controleerbare criteria")
    if needs_tools:
        acceptance.append("Toolresultaten expliciet meewegen; failures niet als succes presenteren")
    if needs_research:
        acceptance.append("Claims koppelen aan bronnen/evidence of onzekerheid benoemen")
    if constraints:
        acceptance.append("Expliciete gebruikersconstraints respecteren")
    if speech == "compare":
        acceptance.append("Zelfde criteria voor beide opties en trade-offs expliciet maken")

    # Compact goal summary — never replaces raw_text.
    goal = re.sub(r"\s+", " ", text).strip()
    if len(goal) > 240:
        goal = goal[:237] + "..."

    missing_info: list[str] = []
    assumptions: list[str] = []
    clarification_needed = False
    state = conversation_state or {}
    follow_up = False
    if any(m in lower for m in _FOLLOW_UP) and (
        state.get("open_questions") or state.get("recent_failures") or state.get("last_assistant")
    ):
        follow_up = True
    if follow_up and not state.get("last_assistant") and "dit" in lower:
        missing_info.append("Referent voor 'dit' ontbreekt in conversation state")
        assumptions.append("Betreft de meest recente mislukte actie of output indien aanwezig")

    # Material ambiguity only — choice questions can proceed with an explicit assumption.
    if ambiguity == "high" and risk != "low":
        clarification_needed = True
    elif missing_info and risk == "high":
        clarification_needed = True
    elif _is_choice_question(text) and ambiguity == "medium":
        assumptions.append("Keuzevraag: beantwoord vergelijkend tenzij gebruiker een harde blokkade vraagt")

    asked_output = {
        "explain": "explanation",
        "compare": "comparison",
        "execute": "execution_result",
        "correct": "corrected_answer",
        "question": "answer",
        "hypothetical": "hypothetical_analysis",
        "inform": "answer",
    }.get(speech, "answer")

    # Resolve short follow-ups against working state without an extra LLM call.
    resolved_goal = goal or "Onbekend doel"
    resolved_query = goal or text
    referent_summary = ""
    source_message_id: str | None = None
    if follow_up and state:
        last_assistant = str(state.get("last_assistant") or "").strip()
        last_user = str(state.get("last_user") or state.get("goal") or "").strip()
        recent_failures = list(state.get("recent_failures") or [])
        open_questions = list(state.get("open_questions") or [])
        last_exec = state.get("last_executed") if isinstance(state.get("last_executed"), dict) else {}
        referent_bits: list[str] = []
        if recent_failures:
            referent_bits.append(f"recente mislukking: {str(recent_failures[-1])[:200]}")
        if last_exec.get("status") in {"failed", "blocked", "partial"}:
            referent_bits.append(
                f"laatste uitvoering status={last_exec.get('status')} notes={str(last_exec.get('notes') or '')[:160]}"
            )
        if last_assistant:
            referent_bits.append(f"vorige assistant: {last_assistant[:280]}")
        if last_user:
            referent_bits.append(f"vorige gebruiker: {last_user[:200]}")
        if open_questions:
            referent_bits.append(f"open: {str(open_questions[0])[:160]}")
        referent_summary = " | ".join(referent_bits)[:600]
        source_message_id = (
            str(state.get("last_assistant_message_id") or state.get("source_message_id") or "") or None
        )
        # Status / continue questions inherit prior work context, not a new mutation grant.
        status_markers = ("status", "hoe staat", "wat is de stand", "voortgang", "progress")
        continue_markers = ("ga verder", "continue", "ga door", "verder")
        if any(m in lower for m in status_markers):
            resolved_goal = f"Status van eerder werk: {referent_summary or last_assistant[:200]}"
            resolved_query = f"{text}\n\nContext referent: {referent_summary}"
            interpretation_follow_up_kind = "status"
        elif any(m in lower for m in continue_markers):
            resolved_goal = f"Vervolg op: {last_user or last_assistant[:200]}"
            resolved_query = f"{last_user}\n{text}\n\nContext referent: {referent_summary}".strip()
            interpretation_follow_up_kind = "continue"
            assumptions.append(
                "Ga verder is geen generieke toestemming om willekeurige oude mutaties te herhalen"
            )
        elif recent_failures and any(m in lower for m in ("waarom faalt", "why does this fail", "waarom", "why")):
            resolved_goal = f"Verklaar falen: {str(recent_failures[-1])[:200]}"
            resolved_query = f"{text}\n\nFoutcontext: {str(recent_failures[-1])[:400]}\n{last_assistant[:400]}"
            interpretation_follow_up_kind = "debug_prior"
        elif "tweede bron" in lower or "second source" in lower or "de tweede" in lower:
            resolved_goal = f"Gebruik eerder genoemde tweede bron t.o.v. {last_user[:120]}"
            resolved_query = f"{text}\n\nEerdere context: {last_assistant[:500]}"
            interpretation_follow_up_kind = "referent_source"
        else:
            resolved_goal = f"{goal} (vervolg op: {(last_user or last_assistant)[:160]})"
            resolved_query = f"{text}\n\nEerdere context: {referent_summary or last_assistant[:400]}"
            interpretation_follow_up_kind = "generic_follow_up"
        # Multiple materially different referents → ask, don't guess.
        distinct_referents = sum(
            1
            for bit in (bool(recent_failures), bool(open_questions), bool(last_assistant and last_user and last_user[:40] not in last_assistant))
            if bit
        )
        if distinct_referents >= 3 and ambiguity != "low" and not any(m in lower for m in status_markers):
            missing_info.append("Meerdere mogelijke referenten in conversation state")
            clarification_needed = clarification_needed or risk != "low"
    else:
        interpretation_follow_up_kind = ""

    interpretation = {
        "speech_act": speech,
        "quoted_spans": quoted[:6],
        "negations": [c for c in constraints if c.lower().startswith(("niet", "nooit", "don't", "do not", "geen", "zonder"))],
        "follow_up": follow_up,
        "follow_up_kind": interpretation_follow_up_kind,
        "correction": speech == "correct",
        "hypothetical": speech == "hypothetical",
        "choice_question": _is_choice_question(text),
        "dangerous_mention_but_explain": bool(mentions_danger and speech == "explain"),
        "authorization_unchanged": True,
        "wants_no_web": wants_no_web,
        "wants_no_tools": wants_no_tools,
    }

    return RequestSpec(
        raw_text=text,
        kind=kind,
        goal=goal or "Onbekend doel",
        constraints=constraints,
        acceptance_hints=acceptance,
        needs_tools=needs_tools,
        needs_research=needs_research,
        needs_memory_write=needs_memory_write,
        needs_plan=needs_plan,
        risk_level=risk,
        ambiguity=ambiguity,
        speech_act=speech,
        asked_output=asked_output,
        missing_info=missing_info,
        clarification_needed=clarification_needed,
        assumptions=assumptions,
        interpretation=interpretation,
        resolved_goal=resolved_goal,
        resolved_query=resolved_query[:4_000],
        referent_summary=referent_summary,
        source_message_id=source_message_id,
        signals={
            "chars": len(text),
            "lines": text.count("\n") + 1,
            "question_marks": text.count("?"),
            "code_fence": "```" in text,
            "prior_failures": prior_failures,
            "constraint_count": len(constraints),
            "speech_act": speech,
            "follow_up": follow_up,
            "quoted_span_count": len(quoted),
            "wants_no_web": wants_no_web,
        },
    )


CLASSIFIER_SCHEMA_KEYS = (
    "intent",
    "independent_outcomes",
    "has_dependencies",
    "ambiguity",
    "freshness",
    "tools",
    "evidence_kind",
)
CLASSIFIER_MAX_INPUT_CHARS = 1_200
CLASSIFIER_MAX_TOKENS = 120


def extract_task_features(spec: RequestSpec) -> TaskFeatures:
    """Deterministic task traits. Cheap length signals are hints only."""
    text = spec.raw_text or ""
    lower = text.lower()
    independent = _count_independent_outcomes(text)
    has_deps = bool(
        spec.needs_plan
        or spec.kind in {"planning", "multi_step"}
        or (spec.kind in {"code", "debug"} and any(m in lower for m in _PLAN_MARKERS))
        or (_has_step_dependency_markers(lower) and independent >= 2)
    )
    if spec.speech_act in {"explain", "question", "hypothetical"} and spec.kind in {"chat", "question", "analysis"}:
        has_deps = False
    tools_required = bool(spec.needs_tools)
    side_effects = spec.speech_act == "execute" or spec.kind == "tool_use"
    freshness = bool(spec.needs_research)
    context_missing = bool(spec.missing_info)
    result_ambiguity = spec.ambiguity == "high" or bool(spec.clarification_needed)
    if spec.asked_output == "explanation":
        evidence_kind = "explanation"
    elif spec.needs_research:
        evidence_kind = "sources"
    elif spec.needs_tools:
        evidence_kind = "tool_results"
    elif spec.needs_plan:
        evidence_kind = "acceptance"
    else:
        evidence_kind = "none"
    prior = int(spec.signals.get("prior_failures", 0) or 0)
    direct_answer = (
        spec.speech_act in {"explain", "question", "inform"}
        and spec.kind in {"chat", "question"}
        and not tools_required
        and not freshness
        and independent <= 1
        and not has_deps
        and spec.risk_level == "low"
        and not side_effects
    )
    mixed_intent = bool(
        spec.speech_act == "inform"
        and any(m in lower for m in _TOOL_EXECUTE_MARKERS)
        and any(m in lower for m in _EXPLAIN_MARKERS)
        and spec.kind not in {"tool_use", "analysis"}
    )
    material_uncertainty = bool(
        (spec.kind == "unknown")
        or (result_ambiguity and spec.kind not in {"chat", "question"} and not spec.clarification_needed)
        or mixed_intent
    )
    cheap_hints = {
        "chars": len(text),
        "newlines": text.count("\n"),
        "question_marks": text.count("?"),
        "role": "cheap_hint_not_calibrated_confidence",
    }
    heuristic = score_complexity(spec)
    return TaskFeatures(
        speech_act=spec.speech_act,
        independent_outcomes=independent,
        has_step_dependencies=has_deps,
        result_affecting_ambiguity=result_ambiguity,
        freshness_required=freshness,
        context_available=not context_missing,
        context_missing=context_missing,
        tools_required=tools_required,
        side_effects=side_effects,
        evidence_kind=evidence_kind,
        prior_run_failures=prior,
        user_constraint_count=len(spec.constraints),
        direct_answer=direct_answer,
        material_uncertainty=material_uncertainty,
        cheap_hints=cheap_hints,
        heuristic_score=float(heuristic.get("total") or 0.0),
        heuristic_score_kind="uncalibrated_hint",
    )


def score_complexity(spec: RequestSpec) -> dict[str, float]:
    """Uncalibrated heuristic breakdown for telemetry. Not used as Adaptive confidence."""
    text = spec.raw_text
    lower = text.lower()
    signals = {
        "length_hint": min(0.5, len(text) / 8000.0),
        "structure_hint": min(0.3, text.count("\n") / 40.0 + text.count("?") / 12.0),
        "code": 2.0 if spec.kind in {"code", "debug"} or "```" in text else 0.0,
        "research": 2.0 if spec.needs_research else 0.0,
        "tools": 1.5 if spec.needs_tools else 0.0,
        "ambiguity": {"low": 0.0, "medium": 0.5, "high": 2.0}[spec.ambiguity],
        "risk": {"low": 0.0, "medium": 1.0, "high": 2.0}[spec.risk_level],
        "dependencies": 1.5 if spec.needs_plan else 0.0,
        "prior_failures": min(2.0, float(spec.signals.get("prior_failures", 0))),
        "constraint_density": min(1.5, len(spec.constraints) / 3.0),
        "independent_outcomes": min(2.0, float(_count_independent_outcomes(text) - 1)),
    }
    signals["compare"] = 1.0 if spec.speech_act == "compare" else 0.0
    signals["explanation"] = 0.5 if spec.speech_act == "explain" and spec.kind in {"analysis", "question"} else 0.0
    signals["architecture"] = (
        1.5
        if any(word in lower for word in ("architectuur", "migratie", "multi-agent", "orchestratie", "end-to-end"))
        else 0.0
    )
    signals["multi_tool"] = (
        2.0
        if spec.needs_tools and _has_step_dependency_markers(lower)
        else 0.0
    )
    if spec.risk_level == "high":
        signals["error_consequence"] = 1.5
    elif spec.kind in {"code", "debug"}:
        signals["error_consequence"] = 0.8
    else:
        signals["error_consequence"] = 0.0
    signals["freshness_need"] = 1.0 if spec.needs_research else 0.0
    signals["kind"] = "uncalibrated_hint"
    signals["total"] = sum(float(value) for key, value in signals.items() if key not in {"total", "kind"} and isinstance(value, (int, float)))
    return signals


def choose_adaptive_profile(spec: RequestSpec, features: TaskFeatures | None = None) -> ReasoningProfileName:
    traits = features or extract_task_features(spec)
    if traits.direct_answer:
        return "fast"
    if spec.speech_act in {"explain", "question", "inform"} and spec.kind in {"chat", "question"} and not traits.tools_required:
        return "fast"
    if spec.kind in {"planning", "multi_step"} and (traits.has_step_dependencies or traits.independent_outcomes >= 3):
        return "high"
    if spec.kind in {"code", "debug"} and (
        traits.has_step_dependencies or spec.risk_level == "high" or traits.prior_run_failures
    ):
        return "high"
    if spec.kind in {"code", "debug"}:
        return "standard"
    if traits.tools_required or traits.side_effects:
        if traits.has_step_dependencies or traits.independent_outcomes >= 3:
            return "high"
        return "standard"
    if traits.freshness_required or spec.kind == "research":
        return "standard"
    if spec.kind in {"analysis"} and (traits.independent_outcomes >= 2 or spec.speech_act == "compare"):
        return "standard"
    if traits.prior_run_failures >= 2:
        return "high"
    if traits.prior_run_failures:
        return "standard"
    return "fast"


def needs_structured_classification(
    spec: RequestSpec,
    features: TaskFeatures,
    *,
    selected_mode: str,
) -> bool:
    """A classifier call is never a default toll.

    Explicit Normal/Medium/High already have an execution policy. Only Adaptive
    may pay a compact classification call, and only on material uncertainty.
    """
    if selected_mode != "adaptive":
        return False
    if not features.material_uncertainty:
        return False
    if spec.kind in {"chat"} or features.direct_answer:
        return False
    return True


def classifier_prompt(spec: RequestSpec) -> str:
    snippet = (spec.raw_text or "")[:CLASSIFIER_MAX_INPUT_CHARS]
    return (
        "Classify this user request. Return JSON only with keys: "
        "intent (explain|execute|question|compare|inform), independent_outcomes (int), "
        "has_dependencies (bool), ambiguity (low|medium|high), freshness (bool), "
        "tools (bool), evidence_kind (none|explanation|sources|tool_results|acceptance). "
        "Do not grant permissions. Do not call tools.\n\n"
        f"{snippet}"
    )


def parse_classifier_output(text: str) -> dict[str, Any] | None:
    from .json_util import loads_json_object

    parsed = loads_json_object(text or "")
    if not isinstance(parsed, dict):
        return None
    if not any(key in parsed for key in CLASSIFIER_SCHEMA_KEYS):
        return None
    intent = str(parsed.get("intent") or "").strip().lower()
    if intent and intent not in {"explain", "execute", "question", "compare", "inform", "correct", "hypothetical"}:
        return None
    ambiguity = str(parsed.get("ambiguity") or "low").strip().lower()
    if ambiguity not in {"low", "medium", "high"}:
        return None
    try:
        outcomes = max(1, int(parsed.get("independent_outcomes") or 1))
    except (TypeError, ValueError):
        return None
    return {
        "intent": intent or None,
        "independent_outcomes": min(12, outcomes),
        "has_dependencies": bool(parsed.get("has_dependencies")),
        "ambiguity": ambiguity,
        "freshness": bool(parsed.get("freshness")),
        "tools": bool(parsed.get("tools")),
        "evidence_kind": str(parsed.get("evidence_kind") or "none")[:40],
    }


def apply_classifier_overlay(features: TaskFeatures, parsed: dict[str, Any] | None) -> TaskFeatures:
    """Overlay validated classifier fields. Never grants tools or permissions."""
    if not parsed:
        return features
    independent = int(parsed.get("independent_outcomes") or features.independent_outcomes)
    has_deps = bool(parsed.get("has_dependencies")) or features.has_step_dependencies
    freshness = bool(parsed.get("freshness")) or features.freshness_required
    # Classifier may notice structure; it cannot invent tool rights.
    tools_required = features.tools_required
    result_ambiguity = features.result_affecting_ambiguity or str(parsed.get("ambiguity") or "") == "high"
    evidence_kind = str(parsed.get("evidence_kind") or features.evidence_kind)
    intent = str(parsed.get("intent") or features.speech_act)
    direct_answer = (
        intent in {"explain", "question", "inform"}
        and not tools_required
        and not freshness
        and independent <= 1
        and not has_deps
        and not features.side_effects
    )
    return TaskFeatures(
        speech_act=intent or features.speech_act,
        independent_outcomes=independent,
        has_step_dependencies=has_deps,
        result_affecting_ambiguity=result_ambiguity,
        freshness_required=freshness,
        context_available=features.context_available,
        context_missing=features.context_missing,
        tools_required=tools_required,
        side_effects=features.side_effects,
        evidence_kind=evidence_kind,
        prior_run_failures=features.prior_run_failures,
        user_constraint_count=features.user_constraint_count,
        direct_answer=direct_answer,
        material_uncertainty=False,
        cheap_hints=dict(features.cheap_hints),
        heuristic_score=features.heuristic_score,
        heuristic_score_kind=features.heuristic_score_kind,
    )


def maybe_escalate_profile(
    profile: ReasoningProfileName,
    *,
    observed_failure: bool = False,
    evidence_gap: bool = False,
    tool_failure: bool = False,
    selected_mode: str = "adaptive",
    signal: str | None = None,
) -> ReasoningProfileName:
    """Scale Adaptive up when a concrete observation appears. Explicit modes stay put."""
    order: list[ReasoningProfileName] = ["fast", "standard", "high", "maximum"]
    resolved = profile_config_key(profile)
    if resolved not in order:
        return profile
    if selected_mode and selected_mode != "adaptive":
        return resolved  # type: ignore[return-value]
    if signal in {"invalid_tool_argument", "capability_missing", "repeated_no_new_info"}:
        return resolved  # type: ignore[return-value]
    if signal == "provider_transient":
        return resolved  # type: ignore[return-value]
    if not (observed_failure or evidence_gap or tool_failure or signal in {"acceptance_unmet", "missing_source", "contradictory_result", "context_mismatch"}):
        return resolved  # type: ignore[return-value]
    idx = order.index(resolved)  # type: ignore[arg-type]
    return order[min(idx + 1, len(order) - 1)]


def maybe_early_stop(
    profile: ReasoningProfileName,
    *,
    checklist_all_met: bool = False,
    evidence_sufficient: bool = False,
) -> bool:
    """Heavy routes may stop once the answer is sufficiently supported."""
    if profile in {"high", "maximum", "standard"} and checklist_all_met and evidence_sufficient:
        return True
    return False


def should_require_plan(spec: RequestSpec, profile: str, features: TaskFeatures) -> bool:
    if profile in {"fast", "normal"}:
        return False
    if features.direct_answer or spec.kind in {"chat", "question"}:
        return False
    if spec.speech_act in {"explain", "question"} and not spec.needs_tools and not features.has_step_dependencies:
        return False
    if profile in {"standard", "medium"}:
        return bool(features.has_step_dependencies and spec.needs_plan)
    return bool(spec.needs_plan or features.has_step_dependencies)


def should_require_llm_critic(spec: RequestSpec, profile: str, features: TaskFeatures) -> bool:
    """LLM critic is for execution/acceptance gaps, not every High reply."""
    if features.direct_answer:
        return False
    if spec.speech_act in {"explain", "question", "hypothetical"} and spec.risk_level == "low" and not spec.needs_tools:
        return False
    if spec.kind in {"chat", "question"} and not spec.needs_tools and not spec.needs_plan:
        return False
    if spec.kind in {"code", "multi_step", "planning"} or spec.risk_level == "high":
        return True
    if spec.needs_tools and profile in {"high", "maximum", "standard", "medium"}:
        return True
    if profile in {"high", "maximum"} and (
        spec.needs_plan or spec.needs_research or spec.kind in {"analysis", "debug", "research"}
    ):
        return True
    return False


def build_route_decision(
    spec: RequestSpec,
    *,
    requested_profile: str | None,
    network_policy: str,
    plugin_tools_enabled: bool,
    explicit_agent: str | None = None,
    features: TaskFeatures | None = None,
    mode_resolution: Any | None = None,
) -> RouteDecision:
    traits = features or extract_task_features(spec)
    resolution = mode_resolution
    if resolution is None:
        try:
            resolution = parse_mode_input(requested_profile, source="stored", allow_unknown=True)
        except Exception:
            resolution = None
    selected_mode = getattr(resolution, "selected_mode", None) or (
        "adaptive" if not requested_profile or requested_profile == "adaptive" else parse_mode_input(requested_profile, source="stored").selected_mode
    )
    explicit = bool(getattr(resolution, "explicit", selected_mode != "adaptive"))

    if explicit and selected_mode != "adaptive":
        profile: ReasoningProfileName = getattr(resolution, "effective_policy", None) or profile_config_key(requested_profile)  # type: ignore[assignment]
        if profile not in {"fast", "standard", "high", "maximum"}:
            profile = profile_config_key(profile)  # type: ignore[assignment]
    else:
        profile = choose_adaptive_profile(spec, traits)

    allow_web = network_policy == "allow" and spec.needs_research
    # Autonomy-on may offer tools for actionable routes. Simple direct conversational
    # answers must not receive tool schemas that burn the Normal/fast budget.
    # Keyword needs_tools biases ranking / target / rounds; it must not zero the
    # payload for non-simple actionable turns (analysis/debug/tool/research/work).
    allow_tools = bool(plugin_tools_enabled)
    if "Geen tools gebruiken" in spec.constraints or bool((spec.interpretation or {}).get("wants_no_tools")):
        allow_tools = False
    if "Geen web / alleen lokaal" in spec.constraints or bool((spec.interpretation or {}).get("wants_no_web")):
        allow_web = False

    require_verification = should_require_llm_critic(spec, profile, traits)

    simple_direct = traits.direct_answer or (
        spec.kind in {"chat", "question"}
        and spec.speech_act in {"explain", "question", "inform"}
        and not spec.needs_tools
        and spec.risk_level == "low"
    )
    # Direct conversational answer ≠ tool execution. Keep autonomy for non-simple routes.
    if simple_direct and not spec.needs_tools:
        allow_tools = False

    if explicit_agent and explicit_agent not in {"auto", "generalist", "chat"}:
        target = "specialist_agent"
        agent_id = explicit_agent
        rationale = f"Expliciet gekozen agent '{explicit_agent}' binnen veilige specialistroute."
    elif simple_direct:
        target = "direct_chat"
        agent_id = "chat"
        rationale = "Duidelijke vraag → direct antwoord zonder planner/critic."
    elif spec.kind in {"planning", "multi_step", "code"} and should_require_plan(spec, profile, traits):
        target = "work_runtime"
        agent_id = "executor"
        rationale = "Meerdere afhankelijkheden/planbare stappen → Work Runtime."
    elif spec.needs_research and allow_web:
        target = "research"
        agent_id = "research_planner"
        rationale = "Actuele of brongebonden researchvraag met toegestaan netwerk."
    elif allow_tools and spec.needs_tools:
        target = "tool_loop"
        agent_id = "executor"
        rationale = "Uitvoerende toolbehoefte binnen enabled plugin registry."
    elif spec.kind in {"analysis", "debug"}:
        target = "analysis"
        agent_id = "executor"
        rationale = "Analyse/debug zonder verplichte multi-agent keten."
    else:
        target = "direct_chat"
        agent_id = "chat"
        rationale = "Eenvoudige of informatieve vraag → direct chat path."

    max_tool_rounds = {"fast": 1, "standard": 3, "high": 5, "maximum": 8}.get(profile, 3)
    if not allow_tools:
        max_tool_rounds = 0
    # Optional bias: when tools are offered but keyword router did not require them,
    # keep at least one round so the model can still call core tools on actionable routes.
    elif not spec.needs_tools:
        max_tool_rounds = max(1, min(max_tool_rounds, {"fast": 1, "standard": 2, "high": 3, "maximum": 4}.get(profile, 2)))

    missing_for_gate = list(spec.missing_info) if spec.clarification_needed else []
    ask = stop_and_ask_gate(
        ambiguity=spec.ambiguity if spec.clarification_needed else "low",
        risk_level=spec.risk_level,
        conflicting_constraints=False,
        missing_required_inputs=missing_for_gate,
    )
    stop_ask = ask.action == "stop_and_ask" and spec.clarification_needed
    if stop_ask:
        allow_tools = False
        max_tool_rounds = 0
        rationale = f"{rationale} Stop-and-ask: {ask.reason}."
    elif spec.assumptions:
        rationale = f"{rationale} Aanname: {spec.assumptions[0]}"

    decision_reason = getattr(resolution, "decision_reason", "") or (
        f"adaptive:{profile}" if selected_mode == "adaptive" else f"explicit:{selected_mode}"
    )
    if selected_mode == "adaptive":
        decision_reason = f"adaptive_chose_{profile};{traits.speech_act}/{spec.kind}"

    return RouteDecision(
        target=target,  # type: ignore[arg-type]
        profile=profile,
        agent_id=agent_id,
        rationale=rationale,
        allow_tools=allow_tools,
        allow_web=allow_web,
        max_tool_rounds=max_tool_rounds,
        require_verification=require_verification,
        stop_and_ask=stop_ask,
        ask_questions=list(ask.questions) if stop_ask else [],
        selected_mode=str(selected_mode),
        effective_policy=str(profile),
        decision_reason=decision_reason,
        policy_version=POLICY_VERSION,
    )

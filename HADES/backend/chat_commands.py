"""Deterministic chat slash commands and natural-language harvest intents.

Runs before the LLM so actions like site document harvest are reliable.
Moral/content policy is NOT enforced here — that belongs in the user system prompt
and/or the local model. Network/filesystem policies remain deterministic gates.
"""

from __future__ import annotations

import re
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
HARVEST_RE = re.compile(
    r"\b("
    r"download|downloaden|haal\s+op|oogst|harvest|crawl|"
    r"ebooks?|e-books?|pdfs?|documenten|boeken"
    r")\b",
    re.IGNORECASE,
)
SLASH_RE = re.compile(r"^/(?P<cmd>[a-zA-Z_-]+)(?:\s+(?P<args>.*))?$", re.DOTALL)

HELP_TEXT = """Beschikbare HADES-commando's:

- `/help` — deze lijst
- `/harvest <url>` — download gelinkte documenten (PDF/EPUB/DOCX/HTML) en importeer in Knowledge
- `/download <url>` — alias van `/harvest`
- `/crawl <url>` — alias van `/harvest`
- `/remember <tekst>` — maak een geheugenvoorstel ter review
- `/voice <transcript>` — maak een taakconcept uit een lokale STT-/plak-transcriptie
- `/plan <vraag>` — forceer planmodus voor deze beurt (doorgeven aan het model)
- `/verify <vraag>` — forceer verificatiemodus voor deze beurt

Natuurlijke taal werkt ook, bijvoorbeeld:
`Download elke ebook die gelinkt staat op https://example.com/`

Vereist: Instellingen → netwerkbeleid op `allow`.
Bij `ask` is expliciete netwerkgoedkeuring vereist (harvest start niet stilzwijgend).
"""


def extract_urls(text: str) -> list[str]:
    found: list[str] = []
    for match in URL_RE.findall(text or ""):
        cleaned = match.rstrip(").,;]>'\"")
        parsed = urlparse(cleaned)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            found.append(cleaned)
    return list(dict.fromkeys(found))


def _parse_harvest_limits(args: str, settings: dict[str, Any] | None = None) -> tuple[int | None, int | None, int | None]:
    cfg = settings or {}

    def _nullable_int(key: str, default: int) -> int | None:
        if key in cfg:
            value = cfg[key]
            if value is None:
                return None
            return int(value)
        return int(default)

    max_documents = _nullable_int("research_harvest_max_documents", 40)
    max_pages = _nullable_int("research_harvest_max_pages", 25)
    max_depth = _nullable_int("research_harvest_max_depth", 2)
    clamp_docs = cfg["research_harvest_clamp_documents"] if "research_harvest_clamp_documents" in cfg else 100
    clamp_pages = cfg["research_harvest_clamp_pages"] if "research_harvest_clamp_pages" in cfg else 80
    clamp_depth = cfg["research_harvest_clamp_depth"] if "research_harvest_clamp_depth" in cfg else 4
    md = re.search(r"max_documents?\s*=\s*(\d+)", args, re.I)
    mp = re.search(r"max_pages?\s*=\s*(\d+)", args, re.I)
    depth = re.search(r"max_depth\s*=\s*(\d+)", args, re.I)
    if md:
        value = max(1, int(md.group(1)))
        max_documents = value if clamp_docs is None else max(1, min(int(clamp_docs), value))
    if mp:
        value = max(1, int(mp.group(1)))
        max_pages = value if clamp_pages is None else max(1, min(int(clamp_pages), value))
    if depth:
        value = max(0, int(depth.group(1)))
        max_depth = value if clamp_depth is None else max(0, min(int(clamp_depth), value))
    return max_documents, max_pages, max_depth


def detect_harvest_intent(text: str, settings: dict[str, Any] | None = None) -> dict[str, Any] | None:
    content = (text or "").strip()
    if not content:
        return None
    cfg = settings or {}
    slash = SLASH_RE.match(content)
    if slash and slash.group("cmd").lower() in {"harvest", "download", "crawl"}:
        args = (slash.group("args") or "").strip()
        urls = extract_urls(args) or extract_urls(content)
        if not urls:
            return {"error": "Gebruik: /harvest <url> — eventueel met max_documents=N"}
        max_documents, max_pages, max_depth = _parse_harvest_limits(args, cfg)
        return {
            "kind": "harvest",
            "url": urls[0],
            "max_documents": max_documents,
            "max_pages": max_pages,
            "max_depth": max_depth,
            "authorized_downloads": True,
        }

    urls = extract_urls(content)
    if not urls:
        return None
    if not HARVEST_RE.search(content):
        return None
    # Natural language: "Download elke ebook ... https://..."
    max_documents, max_pages, max_depth = _parse_harvest_limits("", cfg)
    return {
        "kind": "harvest",
        "url": urls[0],
        "max_documents": max_documents,
        "max_pages": max_pages,
        "max_depth": max_depth,
        "authorized_downloads": True,
    }


def detect_slash_command(text: str, settings: dict[str, Any] | None = None) -> dict[str, Any] | None:
    content = (text or "").strip()
    slash = SLASH_RE.match(content)
    if not slash:
        return None
    cmd = slash.group("cmd").lower()
    args = (slash.group("args") or "").strip()
    if cmd in {"help", "commands"}:
        return {"kind": "help"}
    if cmd in {"harvest", "download", "crawl"}:
        return detect_harvest_intent(content, settings=settings)
    if cmd in {"remember", "memory"}:
        if not args:
            return {"error": "Gebruik: /remember <feit of voorkeur>"}
        return {"kind": "remember", "text": args}
    if cmd in {"voice", "transcript", "spraaktaak"}:
        if not args:
            return {"error": "Gebruik: /voice <transcriptie van lokale STT of plaktekst>"}
        return {"kind": "voice_task", "text": args}
    if cmd == "plan":
        if not args:
            return {"error": "Gebruik: /plan <vraag of taak>"}
        return {"kind": "passthrough", "mode": "plan", "text": args, "reasoning_profile": "high"}
    if cmd == "verify":
        if not args:
            return {"error": "Gebruik: /verify <vraag of claim>"}
        return {"kind": "passthrough", "mode": "verify", "text": args, "reasoning_profile": "maximum"}
    return None


def harvest_succeeded(result: dict[str, Any]) -> bool:
    """Honest success: at least one verified document ingested (crawl-only empty finds are not success)."""
    ingested = int(result.get("documents_ingested") or 0)
    failures = result.get("failures") or []
    pages = int(result.get("pages_crawled") or 0)
    page_sources = result.get("page_sources") or []
    if ingested > 0:
        return True
    # HTML-only harvests may only produce page_sources; count those as ingest evidence.
    if isinstance(page_sources, list) and len(page_sources) > 0 and not failures:
        return True
    if pages > 0 and not failures and ingested == 0 and not page_sources:
        # Crawl ran but nothing was persisted — not a successful knowledge harvest.
        return False
    return False


def format_harvest_reply(result: dict[str, Any], *, ok: bool | None = None) -> str:
    docs = result.get("documents") or []
    failures = result.get("failures") or []
    succeeded = harvest_succeeded(result) if ok is None else bool(ok)
    headline = (
        f"Site-harvest voltooid voor `{result.get('seed_url')}`."
        if succeeded
        else f"Site-harvest mislukt of leeg voor `{result.get('seed_url')}`."
    )
    lines = [
        headline,
        f"- Pagina's gecrawld: {result.get('pages_crawled', 0)}",
        f"- Documentlinks gevonden: {result.get('documents_discovered', 0)}",
        f"- Documenten geïmporteerd in Knowledge: {result.get('documents_ingested', 0)}",
    ]
    if docs:
        lines.append("")
        lines.append("Geïmporteerde documenten:")
        for item in docs[:20]:
            title = item.get("title") or item.get("uri") or item.get("id")
            lines.append(f"- {title} (`{item.get('id')}`)")
        if len(docs) > 20:
            lines.append(f"- … en {len(docs) - 20} meer")
    if failures:
        lines.append("")
        lines.append(f"Mislukt ({len(failures)}):")
        for item in failures[:10]:
            lines.append(f"- {item.get('url')}: {item.get('error')}")
    lines.append("")
    if succeeded and docs:
        lines.append("Documenten staan in Knowledge/Files en verschijnen in Brain als kennisbronnen.")
    elif not succeeded:
        lines.append("Geen betrouwbare harvest — controleer URL, netwerkbeleid en failures hierboven.")
    else:
        lines.append("Geen documenten geïmporteerd; crawl had geen bruikbare downloads.")
    return "\n".join(lines)


async def maybe_handle_chat_command(
    *,
    content: str,
    network_policy: str,
    harvest_fn: Callable[..., Awaitable[dict[str, Any]]],
    remember_fn: Callable[[str], dict[str, Any]] | None = None,
    voice_task_fn: Callable[[str], dict[str, Any]] | None = None,
    settings: dict[str, Any] | None = None,
    approved_network: bool = False,
) -> dict[str, Any] | None:
    """Return a structured command result or None to continue normal chat.

    Passthrough commands (`/plan`, `/verify`) return handled=False with rewrite metadata
    so the caller can continue orchestration with an adjusted user turn.
    """
    slash = detect_slash_command(content, settings=settings)
    if slash and slash.get("kind") == "help":
        return {"handled": True, "ok": True, "command": "help", "message": HELP_TEXT, "result": None}
    if slash and slash.get("error"):
        return {"handled": True, "ok": False, "command": "slash", "message": slash["error"], "result": None}
    if slash and slash.get("kind") == "remember":
        if remember_fn is None:
            return {
                "handled": True,
                "ok": False,
                "command": "remember",
                "message": "Geheugenvoorstellen zijn hier niet beschikbaar.",
                "result": None,
            }
        try:
            proposal = remember_fn(str(slash["text"]))
        except Exception as exc:
            return {
                "handled": True,
                "ok": False,
                "command": "remember",
                "message": f"Onthouden mislukt: {exc}",
                "result": None,
            }
        return {
            "handled": True,
            "ok": True,
            "command": "remember",
            "message": (
                "Geheugenvoorstel aangemaakt ter review.\n"
                f"- id: `{proposal.get('id')}`\n"
                f"- inhoud: {slash['text']}\n\n"
                "Open Geheugen om te bevestigen of te vergeten."
            ),
            "result": proposal,
        }
    if slash and slash.get("kind") == "voice_task":
        if voice_task_fn is None:
            return {
                "handled": True,
                "ok": False,
                "command": "voice",
                "message": "Spraak→taak is hier niet beschikbaar.",
                "result": None,
            }
        try:
            created = voice_task_fn(str(slash["text"]))
        except Exception as exc:
            return {
                "handled": True,
                "ok": False,
                "command": "voice",
                "message": f"Spraak→taak mislukt: {exc}",
                "result": None,
            }
        proposal = created.get("proposal") if isinstance(created, dict) else created
        task = created.get("task") if isinstance(created, dict) else None
        title = proposal.get("title") if isinstance(proposal, dict) else "—"
        priority = proposal.get("priority") if isinstance(proposal, dict) else "—"
        agent = proposal.get("agent") if isinstance(proposal, dict) else "—"
        task_line = f"- task id: `{task.get('id')}`\n" if isinstance(task, dict) else ""
        return {
            "handled": True,
            "ok": True,
            "command": "voice",
            "message": (
                "Taak aangemaakt uit transcriptie (plak/lokale STT — geen cloud-STT; dit pad doet zelf geen ASR).\n"
                f"- titel: {title}\n"
                f"- prioriteit: {priority}\n"
                f"- agent: {agent}\n"
                f"{task_line}\n"
                "Open Taken → Spraak → taak om te starten of bij te sturen."
            ),
            "result": created,
        }
    if slash and slash.get("kind") == "passthrough":
        return {
            "handled": False,
            "ok": True,
            "command": slash.get("mode"),
            "rewrite_content": slash.get("text"),
            "reasoning_profile": slash.get("reasoning_profile"),
            "message": None,
            "result": {"mode": slash.get("mode")},
        }

    intent = detect_harvest_intent(content, settings=settings)
    if not intent:
        return None
    if intent.get("error"):
        return {"handled": True, "ok": False, "command": "harvest", "message": intent["error"], "result": None}
    if network_policy == "block":
        return {
            "handled": True,
            "ok": False,
            "command": "harvest",
            "message": "Netwerkbeleid staat op 'block'. Zet Instellingen → netwerk op 'allow' om documenten te harvesten.",
            "result": None,
            "approval_required": False,
            "failure_class": "POLICY_BLOCK",
        }
    if network_policy == "ask" and not approved_network:
        return {
            "handled": True,
            "ok": False,
            "command": "harvest",
            "message": (
                "Netwerkbeleid staat op 'ask'. Expliciete goedkeuring is vereist voordat harvest "
                "documenten downloadt. Bevestig netwerktoegang of zet beleid op 'allow'."
            ),
            "result": {
                "seed_url": intent.get("url"),
                "approval_kind": "network",
                "max_pages": intent.get("max_pages"),
                "max_depth": intent.get("max_depth"),
                "max_documents": intent.get("max_documents"),
            },
            "approval_required": True,
            "failure_class": "APPROVAL_REQUIRED",
        }
    if network_policy not in {"allow", "ask"}:
        return {
            "handled": True,
            "ok": False,
            "command": "harvest",
            "message": f"Onbekend netwerkbeleid '{network_policy}'; harvest geweigerd (fail-closed).",
            "result": None,
            "approval_required": False,
            "failure_class": "POLICY_BLOCK",
        }
    try:
        result = await harvest_fn(
            intent["url"],
            max_pages=intent["max_pages"],
            max_depth=intent["max_depth"],
            max_documents=intent["max_documents"],
            authorized_downloads=True,
            include_html_pages=True,
        )
    except Exception as exc:
        return {
            "handled": True,
            "ok": False,
            "command": "harvest",
            "message": f"Harvest mislukt: {exc}",
            "result": None,
        }
    ok = harvest_succeeded(result if isinstance(result, dict) else {})
    payload = result if isinstance(result, dict) else {}
    return {
        "handled": True,
        "ok": ok,
        "command": "harvest",
        "message": format_harvest_reply(payload, ok=ok),
        "result": {
            "seed_url": payload.get("seed_url"),
            "pages_crawled": payload.get("pages_crawled"),
            "documents_discovered": payload.get("documents_discovered"),
            "documents_ingested": payload.get("documents_ingested"),
            "document_ids": [item.get("id") for item in (payload.get("documents") or [])],
            "failure_count": len(payload.get("failures") or []),
        },
    }

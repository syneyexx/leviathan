# Chatbot / LLM / retrieval audit — 2026-09-10

Branch: `cursor/chatbot-llm-audit-71b1`  
Basis: nieuwste `main` (`1887b84`, inclusief Plugin Runtime bugfixes)

## Scope

Nagekeken:

1. Connectie met LM Studio / modelresolutie
2. Vraagverwerking (`send_message` → understand → route → tools/model → verify → answer)
3. Informatie-ophalen (memory, knowledge, workspace, web refresh, conversation state)

## Wat niet werkte

### 1. Verified knowledge write-back miste het net gegeven antwoord (P0)

**Probleem:** Bij geverifieerde conversation learning riep chat `knowledge.index_conversation(..., include_assistant=True)` aan *vóór* `add_message(assistant, ...)`. `list_messages()` bevatte dus het nieuwe antwoord niet. Oudere assistant-berichten konden wél als “verified” geïndexeerd worden; het actuele antwoord niet.

**Oplossing:** Voor verified write-back wordt een transcript opgebouwd met de bestaande berichten plus de pending assistant-turn (`transcript_with_answer`), zodat het geverifieerde antwoord wel in Knowledge belandt.

### 2. Conversation state werd niet gebruikt bij intent-understanding (P0)

**Probleem:** `build_request_spec(..., conversation_state=...)` ondersteunde follow-ups (`last_assistant`, `recent_failures`, `open_questions`), maar `send_message` gaf die state nooit door. Working state werd alleen later als context-blob meegestuurd. Bovendien schreef `build_conversation_working_state` `last_assistant` / `recent_failures` überhaupt niet weg.

**Oplossing:**

- Prior working state + failure count worden *vóór* routing geladen
- `resolve_reasoning_profile(..., conversation_state=prior_state, prior_failures=...)` is aangesloten
- Working state bewaart nu `last_assistant` en `recent_failures` (failures wissen bij completed)

### 3. Expliciet gekozen model sloeg LM Studio-discovery over (P1)

**Probleem:** `resolve_model(preferred)` returnde meteen het UI-model zonder te checken of het geladen was → typische 503 i.p.v. fallback naar een wel geladen lokaal model.

**Oplossing:** Altijd eerst geladen models discoveren; voorkeursmodel blijft leidend als het geladen is, anders bounded lokale fallback.

### 4. Research-route was oneerlijk / te laat (P1)

**Probleem:** Router kon `target: "research"` zetten, maar chat viel altijd terug op tool/chat zonder ResearchRunner. Web refresh gebeurde *vóór* routing en alleen bij “fresh web”-markers — research-intent kon dus zonder web-ingest blijven, terwijl metadata wél “research” claimde.

**Oplossing:**

- Understand/route eerst; daarna web refresh met `force=True` bij research-intent
- Retrieval ná die refresh
- `actual_target` is eerlijk: `research` alleen bij attempted web refresh, anders `direct_chat` + note

### 5. `tool_loop_called` was te vaak true (P1)

**Probleem:** `bool(tool_log) or (tool_rounds is None or tool_rounds > 0)` markeerde tool-loop als gebruikt zodra tools *toegestaan* waren, ook zonder tool-aanroep.

**Oplossing:** `executed.tool_loop_called = bool(tool_log)`.

### 6. Temperature bias van high/maximum werd niet toegepast (P1)

**Probleem:** `PROFILE_CONFIGS` definieert `temperature_bias` (−0.05 / −0.1), maar `chat_payload` gebruikte alleen de ruwe profile-temperature.

**Oplossing:** Bias wordt toegepast en geclamped op `[0, 2]`.

### 7. Streaming stond effectief uit door dode `and False` (P1)

**Probleem:** In `run_model_with_optional_tool` stond `(max_rounds is not None and False)` — streaming voor pure tekstpaden bleef daardoor uit.

**Oplossing:** Stream wanneer er een `run_id` is en de payload geen tools bevat.

### 8. Workspace-retrieval was metadata-only (P2)

**Probleem:** Indexed files leverden alleen naam/pad/extensie/status als “content” (≤2k), geen chunk-preview → zwakke of misleidende workspace-hits.

**Oplossing:** Bij `source_id` worden de eerste knowledge-chunks als preview meegenomen.

### 9. Dode branch in conversation working state (P2)

**Probleem:** `elif status == "completed" and not linked_task_id` stond binnen `if linked_task_id:` en was onbereikbaar.

**Oplossing:** Dode branch verwijderd.

## Bewust niet veranderd

- Volledige `ResearchRunner`-integratie in chat (aparte productroute via Research-pagina/workflows). Chat research blijft web-refresh + retrieval + model, nu met eerlijke `actual_target`.
- Live LM Studio end-to-end op deze host: **UNVERIFIED_ON_HOST**.
- Pre-existing failures in tool-discovery tests (`test_reasoning` / `test_gen2_reasoning_contracts`) — falen ook op tip `main`, niet door deze wijzigingen.

## Verificatie

```text
python3 -m pytest backend/tests/test_chatbot_llm_pipeline_fixes.py -q
→ 12 passed
```

Gerelateerde suites (intent / orchestration / answer quality) blijven groen. Live chat met LM Studio is hier niet uitgevoerd.

## Bestanden

| Bestand | Wijziging |
|---|---|
| `backend/main.py` | resolve_model, chat_payload bias, web refresh force, send_message order/state, write-back, tool/research honesty, stream gate, workspace preview |
| `backend/reasoning/profiles.py` | `conversation_state` doorgeven |
| `backend/reasoning/conversation_state.py` | `last_assistant` / `recent_failures`; dode branch weg |
| `backend/tests/test_chatbot_llm_pipeline_fixes.py` | regressies |
| `docs/engineering/CHATBOT_LLM_AUDIT_REPORT_2026-09-10.md` | dit rapport |

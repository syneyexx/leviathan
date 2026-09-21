# Plugin Manager / Runtime — bugfixrapport

Datum: 2026-09-10  
Branch: `cursor/plugin-runtime-bugfixes-dc7b`  
Scope: Plugin Manager, Plugin Runtime, tool shortlist/invoke, MCP-expansie, service lifecycle

## Samenvatting

HADES kon plugins al installeren, shortlisten en uitvoeren, maar meerdere policy- en lifecycle-paden waren onjuist of onveilig. Dit rapport beschrijft wat er mis was, hoe het is gerepareerd, en wat is geverifieerd.

## Wat er mis was en hoe het is gefixt

### 1. Handmatige Run keurde stilletjes alle `ask`-capabilities goed
**Probleem:** `approved_by_user: true` (Run-knop) werd OR-gewijs doorgegeven als goedkeuring voor network/file/subprocess. Globale `ask`-policy werd daardoor nooit HITL.  
**Fix:** Capability-flags zijn ontkoppeld van Run-approval. Alleen expliciete `approved_*` of een duurzame approval tellen. FE stuurt die flags apart mee; zonder flags opent de API een durable approval (428).

### 2. Gen2 envelope-gate degradeerde gewone tools naar `inspect`
**Probleem:** Een `else`-tak zette `sandbox_action = "inspect"` voor alle CLI-tools die niet write/read/network/health waren. Subprocess-containment viel weg.  
**Fix:** Default blijft `subprocess`; `inspect` alleen voor health/status/logs/doctor.

### 3. Succesvolle convert schakelde plugins automatisch in
**Probleem:** Ready convert zette `enabled=True` + `trust=verified`. Autonomous shortlist kon de plugin zien vóór expliciete user-enable (UI werkte dit deels om met een latere disable).  
**Fix:** Ready convert houdt `enabled=False` (trust blijft `verified` per contract). User moet inschakelen. Privileged MCP-expand mag Ready-but-disabled aanroepen.

### 4. MCP-expansie forceerde tijdelijk Ready/enabled en wist failure
**Probleem:** `expand_mcp_tools` zette `enabled=True`, `status=ready`, `clear_failure=True` en herstelde daarna — race + valse Ready.  
**Fix:** Geen state-mutatie meer. Expand skip bij non-ready/structural failure; privileged invoke zonder enable-eis.

### 5. `isolation=container` claimde Docker zonder te isoleren
**Probleem:** Zonder Docker: fallback. Met Docker: label bleef `container`, uitvoering bleef native subprocess.  
**Fix:** Container valt altijd terug op `restricted_env` met eerlijke note (`container_not_implemented_...` / `container_unavailable_...`).

### 6. Service start/stop had geen per-plugin lock
**Probleem:** `_service_locks` bestond maar werd niet gebruikt → parallel start/stop kon race’en.  
**Fix:** `_service_lock_for(plugin_id)` rond start, stop en reconcile.

### 7. `replace_plugin_tools` hardcodeerde `enabled=1`
**Probleem:** Repair/MCP merge bewaarde disabled tools, maar INSERT zette altijd enabled.  
**Fix:** `int(bool(tool.get("enabled", True)))`.

### 8. Update / rollback / delete hardcodeerden `approved=True`
**Probleem:** Mutaties bypass’ten ask-policy.  
**Fix:** Endpoints nemen `PluginApprovalInput`; FE stuurt expliciete approvals.

### 9. `.HadesPlugin` zonder integrity-map werd geaccepteerd
**Probleem:** Lege/ontbrekende integrity bij `source/`-layout skipte hash-checks.  
**Fix:** Fail-closed: niet-lege integrity-map verplicht.

### 10. HTTP/TCP healthchecks konden non-loopback raken
**Probleem:** Reconcile/start kon willekeurige hosts raken (SSRF-achtig).  
**Fix:** Non-loopback alleen als plugin network-capability/permission heeft; reconcile forceert `allow_remote=False`.

### 11. “Already healthy” start claimde succes zonder HADES-beheer
**Probleem:** Als iets de healthcheck beantwoordde, returnte start `completed` / `already_running` ook bij een externe poort.  
**Fix:** Succes alleen bij managed PID/in-memory proces; anders `failed` + `needs_attention`.

### 12. Ontbrekende trust defaultte naar `verified`
**Probleem:** Raw fixtures zonder trust waren autonomously eligible.  
**Fix:** Missing trust → `untrusted` (fail closed). DB-rijen normaliseren nog steeds.

### 13. `finish_tool_call` overschreef metadata
**Probleem:** Finish zonder merge gooide create-time metadata weg.  
**Fix:** Read-merge-write van metadata.

## Wat er al goed stond

- argv + `shell=False`
- globale `block` wint
- autonomous keurt `ask` niet stil goed
- service start vereist healthcheck
- dependency failure blijft zichtbaar + disabled
- restart reconciliation van service state
- zip/path safety bij import

## Verificatie

Focused regressions (`tests.test_plugin_runtime_bugfixes`) + platform/catalog/API plugin-paden: **PASS**.

Belangrijkste nieuwe asserts:
- convert blijft disabled tot enable
- manual Run + network `ask` → 428 zonder capability-flag
- envelope default = subprocess
- integrity verplicht
- container fallback note
- tool enabled-bit behouden
- MCP expand muteert state niet

## Resterende aandachtspunten (niet in deze fix)

- Windows PID-identity na herstart blijft zwakker dan `/proc`
- Geen live Docker-container executor (bewust niet geclaimd)
- UI toont nog geen dedicated dependency-status API
- Native service start mist deels “nog alive na health” t.o.v. Popen-pad

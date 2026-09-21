# Research rondes/agents + Expert-fixatie — rapport

Datum: 2026-09-10  
Branch: `cursor/research-rounds-agents-expert-26ef`  
Basis: verse `origin/main` (incl. #68/#69 bugfixes)

## Wat er fout was

### 1. Expert-niveau kon (bijna) nooit “af” komen
De dekkingsscore voor Expert gebruikte alleen **webdomeinen** voor diversiteit. Bij lokaal onderzoek (of weinig domeinen) bleef de score structureel onder de 90%-drempel, ook met genoeg bronnen. Expert eindigde daardoor vaak permanent in `needs_more_evidence`.

### 2. Expert-rondes klopten niet met de settings
`expert_max_cycles` werd vermenigvuldigd met 3 (`cycles * 3`) bovenop een default van 18 rondes. De settings-UI beloofde “evidence-rondes”, maar de runner deed iets anders — onvoorspelbaar en zwaar.

### 3. Geen controle op diepte vanaf de Research-pagina
Gebruikers konden Quick/Standard/Deep/Expert kiezen, maar **niet** het aantal rondes of parallelle research-agents. Diepere research was daardoor niet echt stuurbaar.

### 4. Bijkomende Expert/web-bugs
- Discovery-rondes riepen `ingest_url(..., False)` aan → geautoriseerde PDF/EPUB-downloads werden genegeerd.
- Zonder web (of met netwerk op `block`) draaide Expert **geen** iteratieve gap-rondes.

## Hoe het is opgelost

| Fix | Detail |
|---|---|
| UI controls | Research-pagina: inputs voor **Researchrondes** (1–60) en **Research agents** (1–8); depth-presets vullen defaults. |
| API/DB | `ResearchCreate.max_rounds` / `agent_count`; kolommen op `research_projects` (migratie 11). |
| Expert rounds | `expert_max_cycles` = rondebudget 1:1; project-`max_rounds` wint. |
| Coverage | Lokale unieke URI’s tellen mee in diversiteit → Expert kan ≥90% halen met sterke lokale evidence (zonder fake mastery). |
| Parallel agents | Queries per ronde verdeeld over N Research Workers. |
| Downloads + lokaal | Discovery respecteert `authorized_downloads`; deep/expert doen lokale gap-filling als web uit/geblokkeerd is. |

## Verificatie

```text
python3 -m unittest tests.test_research_rounds_agents_expert -v
→ 6 PASS

python3 -m unittest tests.test_stt_research_coverage \
  tests.test_audit_silent_sinks_honesty \
  tests.test_audit_research_folder_ingest_event -v
→ 10 PASS
```

Nog **UNVERIFIED_ON_HOST**: live Expert-run met LM Studio + DuckDuckGo tegen een echte Windows-installatie.

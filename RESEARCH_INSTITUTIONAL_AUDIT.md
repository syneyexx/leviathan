# LEVIATHAN Research — Institutional / SpaceX-grade audit

**Repo:** [syneyexx/leviathan](https://github.com/syneyexx/leviathan)  
**Commit gelezen:** `a1bacb5d` / tree `fe9edbb8` (main, sept 2026)  
**Scope:** alles behalve `editor/` en `Data/HADES/`  
**Toon:** chief engineer review. Geen complimenten als troostprijs. Wat werkt, blijft. Wat theater is, gaat eruit.

---

## 0. Verdict in één adem

Je hebt de **ethiek** van institutioneel research bijna af.

Je hebt de **machine** van institutioneel research bijna niet.

Op bijna elk object staat een eerlijk sticker:

- `scorecard_is_not_probability_answer_is_true`
- `heuristic_entailment_is_not_proof`
- `discovery_metadata_not_evidence`
- `UNMEASURED` mag geen PASS worden
- `model output != observation`

Dat is zeldzaam. De meeste “AI research agents” liegen in de UI. Jij liegt in de comments, en bouwt er dan toch een regex-epistemologie onder.

**SpaceX-analogie:** je hebt op elk onderdeel een label *“this is not flight-certified.”* Dat is discipline. Het is geen Flight Readiness Review. Een FRR eist: onafhankelijke test, reconstructeerbare telemetrie, fault tree, red team, configuration-controlled article, en een chief engineer die tekent. Jij hebt de stickers. Je hebt geen artikel.

Als dit systeem morgen een memo schrijft waar een investering, een trade, of een architectuurbesluit op rust, dan rust dat besluit op:

1. DuckDuckGo HTML-scrape (default “WEB SEARCH READY”)
2. zins-split + token-Jaccard ≥ 0.15 als “entailment”
3. twee URL’s op dezelfde host = `SUPPORTED`
4. `arxiv.org` = `peer_reviewed`
5. scorecard `overall ≥ 0.5` = `quality_pass`
6. auto-promote naar Brain, errors geslikt
7. een UI die sources “Collected Evidence” noemt

Dat is een **research notebook met een control-plane jas**. Het is geen institutional research desk.

---

## 1. Wat je wél al hebt (niet weggooien)

Dit is het kapitaal. Bouw hierop. Bouw er geen tweede systeem naast.

| Pilaar | Waar | Waarom het mag blijven |
|---|---|---|
| Citation ledger | `research/evidence.py` | `citation → evidence → source → snapshot`. Dat is de enige juiste keten. |
| Discovery ≠ evidence | `sources.from_web_search` | `DISCOVERED_BUT_UNVERIFIED`. Volwassen. |
| Conflict policy | `conflicts.py` | `preserve_both`. Geen stille winner. |
| UNMEASURED discipline | `quality_scorecard.py` | Geen report → citation_validity is None, niet 1.0. |
| Zero-evidence gate | scorecard W117 | `allow_web` + 0 evidence → cap 0.35 + `INSUFFICIENT_EVIDENCE`. |
| TEAM contract vorm | `team_policy.py` | Mandatory criteria, fail-closed zonder evidence ids. |
| Web readiness honesty | `web_readiness.py` | “outbound aan ≠ search configured”. |
| SSRF intent | `ssrf.py` | Scheme allowlist, private/loopback, redirect revalidate op fetch. |
| Robots fail-closed | `web.py` | Beter dan de meeste crawlers. |
| Job/control vs execution | `ResearchService` + workers | Juiste splitsing. |
| Reproducibility *idee* | `graph.ReproducibilityBundleExporter` | Juiste reflex. Nu nog geen replay. |
| Frontend config-comment | `config/research.ts` | “labels/layout — not live fixture data”. Iemand heeft nagedacht. |

Houd deze invarianten heilig. De rest van dit document is hoe je ze **afdwingt** in plaats van **declareert**.

---

## 2. Diagnose in één zin

> LEVIATHAN Research is een gedetermineerde retrieval-lus met een quality-contract-vernis, specialist-rollen die alleen query-strings veranderen, en een operator-UI die de donkere API (claim-graph, citation-audit, quality, events, conflicts) niet toont.

De lus, letterlijk:

```
plan (4 canned subquestions + token-salad)
  → ThreadPool workers (zelfde code, andere query)
  → local search + optioneel GET
  → zinnen met query-token-overlap = “evidence”
  → claims gegroepeerd op YEAR-gestripte string
  → conflicts via jaartal/negatie-regex
  → markdown-dump van bullets
  → optioneel 800-token model dat mag herformuleren, niet denken
```

`AnalysisMode.MODEL` verandert **alleen** `ReportBuilder.generate`. Niet de planner, niet de extractor, niet de claim-status, niet TEAM.

---

## 3. Kill list — stop hiermee deze week

Dit is geen “later”. Dit is stop-the-line.

1. **Stop TEAM `int * None`.** `coordinator.py` post-wave: `workers_n * hard_ceiling` terwijl TEAM `rounds=None`. Eerste barrier = `TypeError` → `FAILED`. Open-ended quality loop overleeft golf 1 niet.
2. **Stop `service.plan()` TEAM crash.** `research_workers * plan.rounds` met `rounds=None`. `/plan` op TEAM = 500 vóór de run.
3. **Stop post-wave `should_stop` i.p.v. `team_should_stop`.** Twee policies, de zwakke wint (als de crash gefixt is).
4. **Stop `COMPLETED` + `progress_pct=100` bij resterende critical gaps** (NORMAL/CUSTOM).
5. **Stop auto-promote naar Knowledge** (`LEVIATHAN_RESEARCH_AUTO_PROMOTE_VERIFIED_KNOWLEDGE` default `true`). Failed research wordt institutioneel geheugen. Errors worden geslikt.
6. **Stop `_select_spans` fallback naar de eerste zinnen van het document** als overlap 0 is. Dat mint nep-evidence.
7. **Stop `arxiv.org` / `.edu` / `doi.org`-in-URL = `peer_reviewed`.** Preprint is preprint.
8. **Stop `len(source_ids) ≥ 2` = `SUPPORTED`.** Twee pagina’s op dezelfde host zijn geen onafhankelijke bevestiging.
9. **Stop “earliest year wins”** in `claims.py`. De oudste jaartal wordt support, nieuwere contradict. Institutioneel wil je de *laatste primaire* meten, of splitsen in tijdsgebonden claims.
10. **Stop vacuous `conflict_handling = 1.0`** als er geen disputes zijn.
11. **Stop `freshness = 0.45` bij ontbrekende publicatiedatum.** Onbekend is 0 of UNMEASURED, geen “medium-fresh”.
12. **Stop `INTERPRETATION` + `PARTIALLY_SUPPORTED` meetellen als citation success.**
13. **Stop DDG HTML scrape als `search_configured() = True` / “WEB SEARCH READY”.** Best-effort is best-effort.
14. **Stop UTF-8-decode van PDF-bytes op de web-fetch path.** Uploads hebben `pypdf`. Fetch niet. arXiv-PDF = garbage-in-ledger.
15. **Stop `prefer_primary_sources: … or True`** in `question_model.to_plan_edits`. Dat is altijd True.
16. **Stop `except Exception: pass` in `planner.build_plan`.** Stille degradatie naar 4 canned questions.
17. **Stop `ResearchMockPage` in de tree als lie-fabriek** (78%/54% KPIs, toast-only Start). Of `?mock=1` non-prod, of weg.
18. **Stop “Collected Evidence” voor sources.** Sources zijn sources. Spans zijn evidence.
19. **Stop `<Link to="/evidence">` vanuit Research.** Dat is de *training/verification vault*, niet `research_evidence`.
20. **Stop job COMPLETED terwijl het project nog `RESEARCHING` is.** `execute_queued_run` early-return + worker `_complete`.
21. **Stop `result is None` → `JobState.COMPLETED`** in de research entrypoint.
22. **Stop availability-probe fail-open.** Exception → `(True, None)` = UI liegt “worker ready”.
23. **Stop `list_projects(limit=100)` dispatcher.** Project 101 blijft QUEUED.
24. **Stop claim-IDs als `uuid4()` bij elke `analyze_project`.** Claims zijn niet stabiel over waves.
25. **Stop de naam-botsing.** `/research`, `/trading/lab` (Research Lab), `/trading/onderzoek` zijn drie producten. Eén woord.
26. **Stop `test_research_integrity_w1.py` / `w23` die market-sim poison prices testen.** Naam-witwas. Integrity-coverage is fake.
27. **Stop `verify_institutional_runtime.py` citeren als research-gate.** Die verifier zet `research: false`. Het is een trading/IBOR-examen.
28. **Stop permanente “Draft”-badge** op Insights na `completed`.
29. **Stop daemon-threads zonder lease/timeout** als “run”. Hung `fetch_page` = hung wave = hung job.
30. **Stop SHA256 afkappen tot 24 hex** en dat “content_hash” noemen.

---

## 4. Gelaagde upgrade-lijst

Elke laag is een programma, geen brainstorm. Binnen een laag: P0 = deze sprint, P1 = 30 dagen, P2 = 90 dagen.

---

### Laag 0 — Epistemische hygiëne (handhaven, dan afdwingen)

Je hebt de woorden. Maak er **invarianten met tanden** van.

| # | Wat | Hoe | P |
|---|---|---|---|
| 0.1 | Vijf lagen nooit collapsen in de UI | search hit ≠ fetched source ≠ evidence span ≠ supported claim ≠ knowledge document. Contract-test tegen `Leviathan_system_frontend.md` §11. | P0 |
| 0.2 | Status-vocabulaire unificeren | Claim: `UNSUPPORTED` (0 spans), niet “Unmeasured”. UNMEASURED reserveren voor “meting niet gedraaid”. | P0 |
| 0.3 | `quality_pass` herdefiniëren | Vereist: `citation_validity MEASURED`, 0 `critical_unsupported`, `independent_corroboration ≥ 0.5`, geen open `critical` gaps, evidence_gate `OK`. Drempel 0.5 overall is een speelgoedhek. | P0 |
| 0.4 | COMPLETED vs COMPLETED_WITH_INTEGRITY_FAILURES | Citation-audit mag niet alleen een event zijn (W109 A12). | P0 |
| 0.5 | Analysis-mode banner | Persistente `DETERMINISTIC_FALLBACK` vs `MODEL`. Academic Review-template blokkeren zonder MODEL. | P0 |
| 0.6 | Geen stille degradatie | Elke fallback (question model crash, model_caller None, web skip, empty extract) = event + zichtbaar in UI. | P0 |

---

### Laag 1 — Vraagvorming (PI, geen mad-libs)

`planner.py` + `question_model.py` zijn het begin van elk slecht rapport.

**Wat het nu is**

- 4 canned subquestions: *What is established / What evidence / What contradictions / What open questions.*
- Queries = topic + eerste 8 tokens + `"{token} {topic}"`.
- Entities = quoted strings + `[A-Z][A-Za-z…]`.
- Geo = `in|for` + CapitalizedWord.
- Freshness-jaren hardcoded `"2024 OR 2025 OR 2026"`.
- Enricher-hook bestaat, wordt **nooit** meegegeven.
- `build_plan` slikt exceptions.

**Upgrade**

| # | Wat | Detail | P |
|---|---|---|---|
| 1.1 | `ResearchQuestionModel` persistenteren op het project | Niet alleen plan-edits. Operator moet entities, ambiguities, exclusions, temporal/geo scope kunnen editen vóór Run. | P0 |
| 1.2 | Verwijder `except Exception: pass` | Fail the plan. Geen stille canned questions. | P0 |
| 1.3 | Verwijder `or True` op `prefer_primary_sources` | | P0 |
| 1.4 | Jaarliterals → `datetime.now(timezone.utc).year` | Hardcoded 2024–2026 is al een tijdbom. | P0 |
| 1.5 | Subquestions per vraagtype | Comparison, causal, prevalence, mechanism, timeline, actor-intent — elk een vast protocol, niet 4 templates. | P1 |
| 1.6 | Echte decompositie achter `AnalysisMode.MODEL` | Model mag subquestions voorstellen; operator keurt goed; ledger slaat de goedgekeurde set op. Deterministic path blijft inspecteerbaar. | P1 |
| 1.7 | Pre-registered analysis plan | TEAM/expert: locking van subquestions + stopping_criteria + source-class eisen **voor** de eerste fetch. `stopping_criteria` zijn nu display-strings; `should_stop` leest ze niet. | P1 |
| 1.8 | Ambiguïteiten forceren | Als entities leeg of vraag < N tekens: `WAITING_FOR_INPUT`, niet RUN. | P1 |
| 1.9 | Query portfolio typed | `site:arxiv.org`, DOI/PMID detectie, `filetype:pdf`, date windows, adversary queries. Route query-class → provider. | P1 |
| 1.10 | Plan history in de UI | API bestaat (`plan_history`). Pagina gebruikt het niet. | P0 |

**Institutionele lat:** een RAND-analist mag de vraag niet “begrijpen” en gaan zoeken. Eerst: definities, scope, uitsluitingen, wat zou de conclusie falsifiëren.

---

### Laag 2 — Acquisitie (bibliotheek, geen hobbycrawler)

`web.py` is een **DDG HTML-scraper + GET + regex-`<article>` + sha256 van een 2 MB UTF-8-slice naar `.txt`**.

Default `search_mode=auto` + outbound aan → `DuckDuckGoHtmlSearchProvider` → `search_configured()=True` → readiness **“WEB SEARCH READY”**. Dat is de gevaarlijkste zin in de module.

**Configured adapters (alleen met endpoint):** generic JSON, SearxNG, Brave. Geen Google, Bing, Crossref, OpenAlex, Semantic Scholar, PubMed, arXiv API, Unpaywall.

| # | Wat | Detail | P |
|---|---|---|---|
| 2.1 | DDG nooit `READY` | `BEST_EFFORT` mag. `search_available=true` alleen bij configured provider met geslaagde probe. | P0 |
| 2.2 | Start Research disabled tot readiness READY of expliciet local-only | UI zet `allowWeb: true` op templates; route-default is `False`. Split-brain. | P0 |
| 2.3 | PDF op fetch-path | `content-type: application/pdf` of `.pdf` → dezelfde parser als uploads. Nooit `%PDF` als UTF-8 `plain`. | P0 |
| 2.4 | Paywall classifier | 402/403/login/cookie-wall/laag woord-aantal. Zet `meta.paywalled=true` (nu checkt quality het veld dat fetch **nooit zet**). | P0 |
| 2.5 | Echte readability | trafilatura / readability-lxml. Regex `<article>` faalt op SPA’s. | P1 |
| 2.6 | Provider mesh | Crossref works, OpenAlex, Semantic Scholar Graph, PubMed E-utilities, arXiv API, Unpaywall, DataCite. | P1 |
| 2.7 | DOI first-class | Kolom `doi` op `ResearchSource`. Resolve via `https://doi.org/{doi}` Accept CSL-JSON. | P1 |
| 2.8 | Unpaywall OA routing | Bij DOI: als `is_oa`, fetch `best_oa_location.url_for_pdf`. Stamp `oa_status`, license, version. | P1 |
| 2.9 | arXiv abs+pdf als gelinkte sources | `export.arxiv.org/api/query` + pdf. Class = `preprint`, upgrade naar VOR bij DOI. | P1 |
| 2.10 | PubMed/PMC | esearch/efetch XML, PMID/PMCID, MeSH, abstract. | P1 |
| 2.11 | GROBID/ScienceParse voor scholarly PDF | title, abstract, body, refs, tables, figures. Bind location `{page,x0,y0,x1,y1}`. | P1 |
| 2.12 | WARC snapshots | Originele bytes + response headers + `WARC-Date` + `WARC-Payload-Digest`. Text extract = derived artifact. `.txt` is geen snapshot. | P1 |
| 2.13 | Hash-stack | sha256 raw, sha256 normalized text, simhash near-dup. Dedup `(canonical_url, payload_digest)` **met versions**. Nu: zelfde hash **verbergt** recapture. | P1 |
| 2.14 | Change detection | `If-None-Match` / `If-Modified-Since`. Event `source_changed`. | P2 |
| 2.15 | Federated typed search | Planner detecteert DOI/PMID/arXiv-id → niet DDG. | P1 |
| 2.16 | Brave/Searx contract tests | Recorded JSON fixtures. Pagination, language, raw payload bewaren. | P1 |
| 2.17 | Rate limits in Redis (niet in-process 0.5s dict) | Token buckets per eTLD + per API-quota (S2, NCBI). | P2 |
| 2.18 | JS-headless als aparte capability | Gated, eigen SSRF/robots/budget. Niet regex op lege SPA-shells. | P2 |
| 2.19 | Coordinator `sync_web_page` per FETCHED `WEB_PAGE` | Nu alleen `brain_sync(project, report)` aan het eind. Evidence-pages kunnen buiten Knowledge blijven. | P0 |
| 2.20 | Fix `_fetch_url_source_inline` | Gate op fetch-capability, niet `web_unavailable_reason` (search ≠ fetch). | P0 |
| 2.21 | Live CI canary | `verify_research_web_live.py` nightly + WARC fixtures in unit tests. Nu: **niet in CI**. | P1 |
| 2.22 | Local retriever: embeddings écht gebruiken | `LocalResearchRetriever` wrapt HybridRetriever met `use_embeddings=False`. | P1 |
| 2.23 | Uploads: DOCX/HTML/XML/EPUB + OCR_REQUIRED | Geen stille junk-PDF-string-literals. | P1 |
| 2.24 | Fetch retries | 3 attempts, backoff. robots/403 **niet** van `max_sources` aftrekken. Empty body = event, geen span. | P0 |
| 2.25 | Seed-ingest voor alle workers | Nu alleen worker 1 / round 1. TEAM met 8 workers: 7 specialisten zijn blind voor operator-primary text. | P0 |

---

### Laag 3 — Bron-ontologie (TLD is geen peer review)

`source_quality._classify_source` is de module-header die zegt “not simplistic TLD heuristics” en daarna TLD doet.

```
.gov / .mil            → official_primary, authority 0.75
.edu / arxiv / pubmed / doi.org-in-uri / scholar-in-host
                       → peer_reviewed, authority 0.80, expertise 0.85
/docs/ / readthedocs   → technical_docs, primary
rest web               → journalism 0.50
```

Een studentpagina op `.edu` is peer-reviewed. Een arXiv-preprint is peer-reviewed. `doi.org` in een pad is peer-reviewed.

| # | Wat | Detail | P |
|---|---|---|---|
| 3.1 | Class uit bibliografisch type | Crossref `type`: `journal-article`, `posted-content`, `report`, `dataset`. Niet TLD. | P1 |
| 3.2 | `preprint` als class | arXiv = preprint tot VOR-DOI bestaat. | P0 |
| 3.3 | First-class IDs | `doi`, `pmid`, `pmcid`, `arxiv_id`, `issn`, `orcid` op `ResearchSource`. | P1 |
| 3.4 | Retraction Watch + Crossref `update-to:retraction` | Geciteerde DOI met retraction → claim `DISPUTED`, `quality_pass=False`. **Nul hits in de codebase nu.** | P1 |
| 3.5 | Author COI / funding | Crossref funder, OpenAlex affiliations, ICMJE-parse. Penalty als funder ∈ claim-entity. | P2 |
| 3.6 | Primary = originating measurement | Filing, dataset, paper, telemetry — niet “nieuws over het paper”. | P1 |
| 3.7 | SpaceX-grade source types | `dataset`, `technical_report`, `FAA/FCC filing`, `SEC 10-K`, `NASA NTRS`, `patent`, `telemetry_log`, `contractor_report`. | P2 |
| 3.8 | Relevance op body, niet title+URI token-hit | | P1 |
| 3.9 | Accessibility uit OA/paywall, niet “heeft snapshot_path → 0.9” | | P1 |

---

### Laag 4 — Evidence-extractie (begrijpen, niet overlap)

`runner._select_spans`: score = `|query_tokens ∩ sentence_tokens|`. Score 0 → **eerste N zinnen ≥ 20 chars**, truncate 800. Cap default 3–4 spans per source.

Dat is geen extractie. Dat is een grep met een glimlach.

| # | Wat | Detail | P |
|---|---|---|---|
| 4.1 | Score 0 = geen span | Event `NO_EVIDENCE_EXTRACTED`. Nooit document-prefix minten. | P0 |
| 4.2 | Passage retrieval die je al hebt | HybridRetriever + claim-conditioned highlighting. Cap per **subquestion**, niet per source. | P1 |
| 4.3 | Span attestation | Bij ingest: `(content_hash, start, end, quote_hash)`. Resolve moet `snapshot[start:end] == span_text` (of fuzzy + `ocr_uncertain`). Nu: file-exists ≠ quote-in-file. | P0 |
| 4.4 | Tables/captions/units | Sentence-splitter mist cellen. GROBID TEI. | P1 |
| 4.5 | `max_evidence_per_source=4` is te laag voor technical docs | Per-subquestion budget. | P1 |
| 4.6 | Twee evidence-systemen joinen | Research `[e:]` en vault `ev:` ontmoeten elkaar nooit in `ClaimAnalyzer`. Een claim over een testrun eist `ev:` ARTIFACT_HASH VERIFIED **plus** `[e:]` span. | P1 |

---

### Laag 5 — Claims / NLI / identiteit

`ClaimAnalyzer` (module docstring: *“deterministic”*):

1. Split op `(?<=[.!?])\s+`
2. Keep als `len≥20` EN (jaar-regex OF launch-werkwoorden OF `len>40`). Max 6 zinnen/span.
3. Normaliseer: quotes weg, whitespace, **jaren → `"YEAR"`**, lowercase, `[:400]`. Groepeer.
4. Status: ≥2 jaren → `DISPUTED` (vroegste jaar = support); anders ≥2 `source_id` → `SUPPORTED`; anders `WEAKLY_SUPPORTED`.
5. `UNRESOLVED` wordt **nooit** gezet.
6. Elke analyze: nieuwe `uuid4()` claim_ids.

Tweede pass: Jaccard overlap 0.15 + Engelse negatie-regex.

Retrieval gebruikt een **andere** formule: claim-recall @ 0.20, mét Nederlandse negaties.

| # | Wat | Detail | P |
|---|---|---|---|
| 5.1 | Stabiele claim-ID | `(normalized predicate, entities, time, geo, metric, population)` — niet uuid-per-wave. | P0 |
| 5.2 | NLI i.p.v. Jaccard 0.15 | DeBERTa-v3 MNLI of SciNLI. Lexical = prefilter. Drempels: `p(entail)≥0.85` support, `p(contra)≥0.7` dispute, anders insufficient. Model-id + checksum in bundle. | P1 |
| 5.3 | Eén entailment-spec | Research Jaccard@0.15 ≠ retrieval recall@0.20. Versioneren in `bundle.manifest.entailment_spec`. | P0 |
| 5.4 | `SUPPORTED` eist independent clusters ≥ 2 **en** NLI-pass **en** ≥1 primary | Zelfde host = `WEAKLY_SUPPORTED`. | P0 |
| 5.5 | Kill earliest-year-wins | Temporal disagreement → gesplitste dated claims `(proposition, t0, t1)`. Nieuwste primaire wint niet automatisch; beide blijven, met tijd. | P0 |
| 5.6 | OpenIE/IE voor claim-identiteit | “X launched YEAR” mag niet over bedrijven heen mergen. | P1 |
| 5.7 | HypothesisBoard ↔ ResearchClaim | Nu een derde, losse teller (`s≥2 and c==0 → SUPPORTED`). Eén object. Counts = independent clusters, niet evidence-ids. Twee Reddit-comments zijn geen MODERATE. | P1 |
| 5.8 | Numerieke claims | Extraheer waarde ± error, n, CI (GROBID). Beta(1+s,1+c) over clusters, 90% CI. Nooit punt-“0.87”. | P2 |
| 5.9 | Recency decay per claim-class | Fysische constante: geen. Regulatory/market/launch: half-life. Gewicht `exp(-λ Δt)` op `published_at`, niet `fetched_at`. | P2 |
| 5.10 | Taal | EN+NL wordlists missen “failed to / ruled out / inconsistent with / no evidence of”. Multilingual NLI; regex = debug overlay. | P1 |

---

### Laag 6 — Onafhankelijkheid / corroboratie

`cluster_dependent_sources`: content_hash → wire-hint (`via reuters`) → eTLD+1.

**Niet geclusterd:** NYT/IHT/Wirecutter, zelfde auteur, preprint↔journal, RSS-kopieën, cache vs origin, vertalingen, Elsevier-imprints. `arxiv.org` + `nature.com` van hetzelfde paper = twee clusters. Reuters op 40 kranten zonder “via reuters” in de titel = 40 clusters.

Scorecard-target: `min(clusters/2, 1)` — twee clusters = vol.

Claim-**status** gebruikt clusters **niet**. Alleen de scorecard.

| # | Wat | Detail | P |
|---|---|---|---|
| 6.1 | Independence graph | Wikidata P127 owned-by, OpenAlex institutions, ISSN-L, Crossref container-title, ORCID-overlap, simhash body. | P1 |
| 6.2 | Status gebruikt clusters | Zie 5.4. | P0 |
| 6.3 | UI: cluster-kaart | Favicon-letter is geen independence map. Badge claims met cluster-count. Target ≥2 zichtbaar. | P1 |
| 6.4 | Diversiteit-noemer | Niet `unique_domains / 3.0`. Gebruik `max(5, 0.3×source_count)` of Shannon over clusters. Drie blogs ≠ 1.0. | P0 |

---

### Laag 7 — Conflicts, dissent, red team

`ConflictDetector` is regex op jaren/getallen/populatie/metric/negatie. Policy hard-coded `preserve_both` / `resolution: unresolved`. Dat is de juiste default. Het is geen reconciliation.

“Adversarial verification” in de coordinator: event met drie canned questions, alleen bij `depth in {deep, expert}` **en** als er al conflicts zijn. Geen extra retrieval. Geen devil’s-advocate worker.

`MISSING_COUNTEREVIDENCE` alleen als het plan-woord `"contradict"` bevat.

`assignments.py` heeft rollen (`contradiction_hunter`, `academic_sources`). `_worker_round` leest ze **niet**. Alleen query-strings. Odd workers krijgen een reversed leftover.

| # | Wat | Detail | P |
|---|---|---|---|
| 7.1 | Assignments afdwingen in `_worker_round` | Filter fetch op `preferred_source_types`. Contradiction-lane moet negated/conflict queries doen, niet `"{query} contradiction hunter"`. Fail worker-round als `success_criteria` onvervuld. | P0 |
| 7.2 | Altijd adversarial query per `SUPPORTED` claim | `criticism`, `failed replication`, `retraction`, `limitation`. Niet alleen als het plan “contradict” zegt. | P0 |
| 7.3 | ACH / competing hypotheses object | ≥2 live hypotheses, evidence voor/tegen, residual unknowns. Geen conflict-bullet. | P1 |
| 7.4 | Mandatory dissenting brief | TEAM/expert: minstens één DISPUTED of expliciet `no_conflict_found` met de query die daarvoor gedraaid is. | P1 |
| 7.5 | Human adjudication | Voor `direct_contradiction`: wie, wanneer, evidence ids, rationale. Immutable. `preserve_both` is geen handtekening. | P1 |
| 7.6 | `crit:conflicts_surfaced` niet SATISFIED op afwezigheid | Geen conflicts + geen high gaps ⇒ “conflicts surfaced” is leugen. | P0 |
| 7.7 | Steelman-view in UI | Beide kanten, geen winner. API `listResearchConflicts` wordt niet gerenderd. | P0 |

---

### Laag 8 — Scorecard die je niet kunt gamen

Huidige gewichten en games:

| Dim | W | Formula | Game |
|---|---|---|---|
| coverage | 0.15 | answered/planned; answered = token overlap len>3 | Brede subquestions + junk spans |
| citation_validity | 0.18 | SUPPORTED+PARTIAL+INTERPRETATION; UNMEASURED zonder report (goed) | Partial/hedge telt als valid |
| source_diversity | 0.12 | unique_domains / **3.0** | 3 blogs = 1.0 |
| primary_source_presence | 0.12 | primary-class / min(3, n) | `.edu`/arxiv |
| freshness | 0.08 | step fn; **missing date = 0.45** | Ondated = medium-fresh |
| independent_corroboration | 0.15 | mean min(clusters/2, 1) | Twee same-family hosts |
| conflict_handling | 0.10 | **geen disputes → 1.0 vacuous** | Nooit conflict detecteren maxed de dim |
| unresolved_critical_gaps | 0.10 | geen → 1.0; anders 0.0 | Critical gaps niet emitteren |

`quality_pass = gate OK AND overall ≥ 0.5`.

Gap EIG is een constante (`NO_EVIDENCE=0.85`, `CONTRADICTION=0.9`) — geen model.

Coverage “answered” via bag-of-words: “What is Starship’s payload to LEO?” is beantwoord door een zin met “payload” en “Starship”.

| # | Wat | Detail | P |
|---|---|---|---|
| 8.1 | Anti-gaming pack | (a) diversity-noemer 6.4; (b) conflict_handling UNMEASURED bij 0 disputes; (c) missing published_at freshness 0 of UNMEASURED; (d) PARTIAL gewicht 0.5; (e) INTERPRETATION telt niet mee; (f) quality_pass zoals 0.3. | P0 |
| 8.2 | Coverage via NLI | Subquestion beantwoord iff ≥1 NLI-supported claim die de vraag entailed. | P1 |
| 8.3 | EIG kalibreren of verwijderen | Hardcoded 0.85 is cosplay-kwantiteit. Of hold-out eval, of ordinal {low,med,high} zonder float. | P1 |
| 8.4 | Scorecard in de UI | API `getResearchQuality` bestaat. Pagina haalt het niet op. TEAM belooft “shows exactly what prevents completion” en toont marketingcopy. | P0 |
| 8.5 | Vacuous 1.0 nooit groen | `N/A — no disputes recorded`. | P0 |
| 8.6 | Templates → required profile | Academic: citation_validity MEASURED + primary ≥ 0.5 + 0 UNCITED factual. Unmet → kan niet `completed`. Depth is nu een budget-hint, geen protocol. | P1 |

---

### Laag 9 — Rapport dat een VP tekent

`ReportBuilder.generate` is een concatenatie:

- Executive = *“collected N sources, N spans, N claims, N conflicts.”*
- Findings = `({status}) {proposition} [e:…]`
- Uncertainty default als leeg: *“Coverage appears complete relative to the stored plan, within budget.”*
- Model-narratief: 800 tokens, “Only restate findings”, non-authoritative.
- HTML = headings/li/p escape. Geen tables, geen graph.

Dat is een inventory dump. Het is geen research report.

**Institutioneel rapport-minimum (elke TEAM/expert run):**

1. Vraag + definities + scope + uitsluitingen
2. Methode (providers, datum, budgets, analysis_mode, parser versions)
3. Findings met `[e:]` die resolven, **en** onafhankelijkheidsgraad
4. Competing hypotheses / dissent
5. Wat zou deze conclusie falsifiëren
6. Wat is UNMEASURED vs gemeten
7. Kill-criteria die wel/niet raakten
8. Classification van zekerheid per finding (niet overall 0.73)
9. Operator-of-record / signed-off (zelfs als “local operator”)
10. Reproducibility bundle hash

| # | Wat | P |
|---|---|---|
| 9.1 | Verwijder “Coverage appears complete…” als coverage None is | P0 |
| 9.2 | Model mag niet `COMPLETED` un-blocken als het faalt | P0 |
| 9.3 | Structured findings (JSON) naast markdown | P1 |
| 9.4 | Per-finding certainty band + cluster count + primary/secondary mix | P1 |
| 9.5 | “What would change this conclusion” verplicht | P1 |
| 9.6 | Export markdown/html/json in de UI | Client heeft export; chrome niet. Bundle-client **ontbreekt**. | P0 |

---

### Laag 10 — Reproducibility als flight article

Huidige bundle: JSON dump van SQLite-rijen + opnieuw gegenereerde graph (nieuwe `edge_*` UUIDs), `sha256[:24]`, lokale `snapshot_path`. Geen `import_bundle` / `replay`. Bodies niet inlined. RetrievalTrace (die wél bestaat) zit er niet in.

Een SpaceX-artikel is bit-reproducible: configuratie, software-rev, telemetrie, test-stand.

| # | Wat | Detail | P |
|---|---|---|---|
| 10.1 | CAS voor snapshots | Embed blobs of content-addressed store. Pad op één machine is geen artifact. | P1 |
| 10.2 | `ResearchService.replay_bundle(path)` | `{bit_identical_claims, diffs}`. | P1 |
| 10.3 | Manifest | parser/extractor/NLI versions, retrieval traces, query list, fetch timestamps, HTTP status, robots, IP, cert fingerprint, UA. | P1 |
| 10.4 | Volledige sha256, niet 24 hex | | P0 |
| 10.5 | Stabiele edge-IDs | `sha1(claim_id, evidence_id, relation)`, geen uuid4-at-export. | P0 |
| 10.6 | Quality contract als stored artifact | Nu in event-payload. Persist `QualityContract` + per-revision verdicts. `artifact_revision = sha256(report\|evidence_ids\|claim_ids)`, niet `rev:{run_id[:8]}`. | P0 |
| 10.7 | RetrievalTrace in de bundle | | P1 |

---

### Laag 11 — Control plane / TEAM / jobs (dit is nu kapot)

P0-bugs die TEAM tot theater maken:

| # | Bug | File |
|---|---|---|
| 11.1 | `workers_n * hard_ceiling` met `None` | `coordinator.py` ~701 |
| 11.2 | `plan.budget.research_workers * plan.rounds` met `None` | `service.py` ~802 |
| 11.3 | Post-wave altijd `gaps.should_stop`, nooit `team_should_stop` | `coordinator.py` ~725 |
| 11.4 | Contract pas ná synthesis geëvalueerd; in-loop `acceptance=None` | coordinator |
| 11.5 | `BLOCKED` / `WAITING_FOR_INPUT` in `RESUMABLE_STATUSES` maar `resume()` laat alleen INTERRUPTED/FAILED/CANCELLED/PLANNED/DRAFT | `service.resume` |
| 11.6 | `deepen()` alleen COMPLETED/INTERRUPTED/FAILED | service |
| 11.7 | Job COMPLETED terwijl project RESEARCHING | `execute_queued_run` + worker `_complete` |
| 11.8 | Entrypoint `result is None` → COMPLETED | `entrypoints/research.py` |
| 11.9 | Budget-extension voor critical gaps is **dead code** | `should_stop` returnt eerst `budget_exhausted`; coordinator break vóór extend-block |
| 11.10 | NORMAL/CUSTOM altijd COMPLETED @ 100% | coordinator einde |
| 11.11 | TEAM mid-run `progress_pct = 5 + round_number` — golfnummer als percent, terwijl comments zeggen dat ze dat niet zouden doen | coordinator |
| 11.12 | `validate_budget_input` “reject” TEAM rounds met `pass` | `budgets.py` |
| 11.13 | API default `executionMode=normal` overschrijft depth-preset rounds naar 2×10 | `resolve_execution_budget` |
| 11.14 | Dispatcher `list_projects(limit=100)` | service |
| 11.15 | Availability probe fail-open | service |
| 11.16 | Daemon threads, geen join/timeout/lease; PID-reuse als owner | runner recover |
| 11.17 | Resume mint nieuwe run_id + worker UUIDs; geen round-idempotency | coordinator.run |
| 11.18 | In-process busy-check racy t.o.v. CAS | service |
| 11.19 | `_fail` slikt `fenced_transition` errors | worker.py |
| 11.20 | `worker_context` kan een **nieuwe** JobRuntime bouwen → split-brain leases | worker_context.py |

**TEAM zoals bedoeld:** stop op ACCEPTED of named blocker. COMPLETED alleen op contract.

**TEAM zoals geïmplementeerd:** crash na golf 1, of (na patch) stop via fixed-budget functie, evalueer contract één keer, parkeer in `BLOCKED` zonder legale resume.

| # | Fix | P |
|---|---|---|
| 11.A | Nooit vermenigvuldigen met `None`. `effective_round_ceiling`. `total_worker_rounds=0` als unbounded. | P0 |
| 11.B | Post-wave `team_should_stop`. Verdicts **elke wave**. Geen synthesis tot ACCEPTED of named blocker. | P0 |
| 11.C | `POST .../continue` voor BLOCKED/WAITING. | P0 |
| 11.D | Job blijft RUNNING + heartbeat tot project terminal is. | P0 |
| 11.E | PID niet als owner; `kernel_job_id` + fencing token. | P0 |
| 11.F | Wave timeout. Fetch hang ≠ eternal job. | P0 |
| 11.G | Routes: `GET /quality-contract`, `GET /acceptance`. | P1 |
| 11.H | Plan `stopping_criteria` daadwerkelijk parsen. | P1 |

---

### Laag 12 — Operator surface (Gotham, geen mood board)

De **backend is dichter bij institutional dan de UI toegeeft.** De pagina is een drie-koloms mood board.

Donkere API die de pagina **niet** aanroept, terwijl de client de methods al heeft:

`listResearchConflicts`, `getResearchQuality`, `getResearchCitationAudit`, `getResearchReport`, `listResearchEvents`, `getResearchCoverage`, `getResearchSourceAssessments`, `getResearchPlanHistory`, `deepen`, `resume`, `plan`.

Claim-graph en reproducibility bundle: backend ja, **client-method ontbreekt**.

| # | Wat | P |
|---|---|---|
| 12.1 | ResearchPage = workspace: Report \| Claims \| Evidence \| Conflicts \| Quality \| Events \| Audit | P0 |
| 12.2 | Claim inspector: proposition → spans → source → snapshot hash + fetched_at + parse_status + cluster-id | P0 |
| 12.3 | `/research/:id/evidence` — nooit linken naar vault `/evidence` | P0 |
| 12.4 | KPI = evidence_count, niet source count. Panel title = Sources. | P0 |
| 12.5 | Caps 8 sources / 5 claims eruit. Virtualized tables. | P0 |
| 12.6 | Timeline binden aan events, niet phase-ordinal cartoon | P0 |
| 12.7 | Badge = `project.status`, niet eeuwige Draft | P0 |
| 12.8 | Spinner alleen in synthesizing / report_generation | P0 |
| 12.9 | TEAM quality panel live | P0 |
| 12.10 | Resume / deepen / plan-edit / export / “pack for audit” knoppen | P0 |
| 12.11 | Project rail (Lab heeft dit al) | P0 |
| 12.12 | Failed poll → stale banner + timestamp | P0 |
| 12.13 | `wait_reason` / `kernel_job_id` tonen (W109 A01) | P0 |
| 12.14 | Web-on-by-default eruit tot READY | P0 |
| 12.15 | Code/Images tabs weg of implementeren | P1 |
| 12.16 | Academic source-class filters die `preferredSourceTypes` raken | P1 |
| 12.17 | Mock page: delete of `?mock=1` + CI fail bij import in routed page | P0 |
| 12.18 | Drie producten hernoemen | Research Desk / Strategy Lab / News Orchestra. Docs “Onderzoek & Kennis” splitten. | P0 |
| 12.19 | Knowledge Library: `research_project_id` + scorecard op rijen | P1 |
| 12.20 | Corpus browser per project | snapshot hash, parse, robots, published_at, cluster | P1 |
| 12.21 | Event rail (goedkoopste Gotham-win — data ligt er al) | P0 |
| 12.22 | Decision log / append-only (Onderzoek heeft “Beslissingsketen”; Research niet) | P1 |
| 12.23 | Kill-criteria op Start, tonen welke vuurde | P1 |
| 12.24 | `ResearchEpisodeBinding` op Lab-create: `research_project_id` of expliciet `UNBOUND`. Unbound ≠ “evidence-backed alpha”. | P1 |

Hero-tagline *“Deeper answers. Broader context. Higher conviction.”* is het tegengestelde van je backend-ethiek. Conviction is het product van onafhankelijke clusters + NLI + primary sources, geen marketing.

---

### Laag 13 — Evaluation coupling (flywheel, geen eiland)

Research quality voedt **niet** `Data/modules/evaluation/*`. Training promotion is champion/challenger voor **modellen**. Research “promotion” is silent brain-ingest.

Eval-ablations: memory/critic/reranker/delegation/depth/neuro — niet citation validity of source independence. Geen `component="research"`.

`judge_calibration.py` zegt: uncalibrated LLM judge → UNMEASURED. Research templates verkopen “Deep / Academic” alsof een depth-string een meting is.

| # | Wat | P |
|---|---|---|
| 13.1 | Auto-promote default **false** | P0 |
| 13.2 | Promote = operator-knop, gated op quality_pass + 0 critical_unsupported | P0 |
| 13.3 | `ResearchPromotionRecord` | decided_by, gates=`quality_scorecard.public_dict()`, lineage `research_project → knowledge_document`. Kopieer `training/promotion.py` discipline. | P1 |
| 13.4 | Sealed research eval suite | web-unconfigured mag niet PASS; allow_web + 0 evidence = FAIL; claim zonder span = FAIL; promote-without-audit = FAIL. | P1 |
| 13.5 | Die suite voeden in knowledge-promotion gate | P1 |
| 13.6 | `scripts/verify_research_runtime.py` als release-autoriteit | web honesty, snapshot presence, citation resolve, quality gate, no-promote-on-fail, UI importeert geen mocks. | P1 |
| 13.7 | `verify_institutional_runtime.py` niet citeren als research PASS | P0 |
| 13.8 | Gold questions met bekende primary sources | TEAM mag niet COMPLETED met `critical_unsupported`. NORMAL mag niet promoten op `SINGLE_SOURCE`. | P1 |

---

### Laag 14 — Security (SSRF is een checklist, geen bar)

`ssrf.py` is 125 regels. Beter dan niks.

**Covered:** http/https; localhost / `*.local` / `metadata.google.internal`; private/loopback/link-local/multicast/reserved; IPv4-mapped IPv6; 169.254/16; 0.0.0.0/8; fetch-path redirect revalidate (`follow_redirects=False`).

**Holes:**

1. **DNS rebind TOCTOU** — `getaddrinfo` daarna lost httpx opnieuw op. Geen IP-pin.
2. **`DuckDuckGoHtmlSearchProvider` `follow_redirects=True`** — check ná follow. Classic redirect-SSRF.
3. **CGNAT `100.64.0.0/10`** — `is_private` is False.
4. **Cloud metadata hostnames** naast Google: AWS/IMDSv2, Kubernetes, Consul, `*.internal`.
5. **Geen `.internal` / `.corp` / `.lan` suffix-block.**
6. **Geen decimal/octal/hex IP, unicode localhost, userinfo, port-allowlist.**
7. **Null-byte check is `pass`** — dode code (`ssrf.py:60–62`).
8. Tests: `resolve_dns=False`. `test_http_provider_rejects_localhost_search_results` **patched `assert_safe_url` weg**.
9. **Retry-After als `float()`** — HTTP-date crasht of wordt genegeerd.

| # | Wat | P |
|---|---|---|
| 14.1 | IP pinnen op de socket (custom httpx transport) | P0 |
| 14.2 | Nooit `follow_redirects=True` | P0 |
| 14.3 | Block 100.64/10, IPv6 metadata, `.internal/.corp/.lan` | P0 |
| 14.4 | Verwijder de `pass` op control chars; reject | P0 |
| 14.5 | Tests met `resolve_dns=True` + fake resolver | P0 |
| 14.6 | DDG-path dezelfde redirect-revalidate als fetch | P0 |

---

### Laag 15 — Tests die geen naam-witwas zijn

| Bestand | Wat het écht test | Research-acquisitie? |
|---|---|---|
| `test_research_web_w109_w118.py` | DDG regex op **hand-HTML**; chain failover met **lambda stub**; probe met fake_search; localhost filter met **assert_safe_url gepatcht** | Nul packets |
| `test_research_system.py` | Local RAG e2e met `UnconfiguredWebProvider` | Local ledger |
| `test_research_hardening.py` | Workers; txt upload; **empty PDF fail**; comment “Text PDF via pypdf is hard” | Nooit succesvolle PDF-extract |
| `test_research_external_execution.py` | Job queue freeze | Execution ownership |
| `test_research_model_control_plane.py` | Fake `model_caller` | Niet acquisitie |
| `test_research_integrity_w1.py` | **Market-sim TRAIN/VAL/SEALED poison prices** | **Verkeerd subsysteem** |
| `test_e2e_research_integrity_w23.py` | Hold-strategy gym | **Verkeerd subsysteem** |
| `verify_research_web_live.py` | Echte search→fetch | **Niet in CI** |
| `w109_research_trading_gap_matrix.json` | Line numbers van oude `web.py` | Stale |
| `verify_institutional_runtime.py` | IBOR/SoD/recon | `research: false` |

Always-pass fixtures: inject `UnconfiguredWebProvider` zodat web-round een logged skip is en local docs toch `COMPLETED`. Stub `chain._fallback.search`. Quality-gate test bouwt een **COMPLETED empty project** — geen run, geen fetch. PDF-success vervangen door `.md`. `DuckDuckGoHtmlSearchProvider` geïmporteerd en **nooit constructed**.

| # | Wat | P |
|---|---|---|
| 15.1 | Hernoem of split `test_research_integrity_w1/w23` | P0 |
| 15.2 | TEAM TypeError-test: quality_contract run mag niet crashen na wave 1 | P0 |
| 15.3 | `plan()` TEAM mag geen 500 | P0 |
| 15.4 | `_select_spans` score 0 mint geen prefix-spans | P0 |
| 15.5 | Two same-host URLs ≠ SUPPORTED | P0 |
| 15.6 | arXiv ≠ peer_reviewed | P0 |
| 15.7 | Vacuous conflict_handling ≠ 1.0 in quality_pass pad | P0 |
| 15.8 | allow_web + 0 evidence mag niet `quality_pass` | bestaat deels; must FAIL status, niet alleen cap 0.35 | P0 |
| 15.9 | Snapshot golden tests + robots tests + Brave/Searx shape tests | P1 |
| 15.10 | Live canary nightly | P1 |
| 15.11 | UI contract: `/research` importeert geen mocks | P0 |
| 15.12 | Promote-without-audit = FAIL | P0 |
| 15.13 | PDF fetch path: `%PDF` mag nooit als `plain` in ledger | P0 |
| 15.14 | Replay bundle bit-identical op fixture | P1 |

---

### Laag 16 — SpaceX-programma (hoe je dit runden alsof het vliegt)

Geen extra features. Een **flight program**.

**Rollen (ook als jij ze allemaal bent):**

| Rol | Verantwoordelijkheid |
|---|---|
| Chief Engineer | Tekent COMPLETED. Zonder handtekening is het DRAFT. |
| Responsible Engineer (Research) | Eigenaar van ledger-invarianten. |
| Quality / GNC analog | Eigenaar van scorecard + NLI drempels. Mag niet dezelfde persoon zijn die de extractor schrijft, op papier. Split in PRs. |
| Red team | Adversarial queries, retraction checks, “how would this memo be wrong”. |
| Release captain | `verify_research_runtime.py` is de gate. Groen op de verkeerde exam = geen ship. |

**Gates (kopieer NASA FRR-mentaliteit, niet de bureaucratie):**

```
G0  Invariants hold (tests 15.2–15.8, 15.11–15.13)
G1  Acquisition: configured provider OR explicit local-only; DDG ≠ READY
G2  Every COMPLETED report: 0 UNCITED factual, 0 unresolved citations, span attestation
G3  Every SUPPORTED claim: ≥2 independent clusters + NLI pass + ≥1 primary-class
G4  TEAM: contract SATISFIED or named BLOCKED (resumable). No TypeError. No 100% op gaps.
G5  Promote to Brain: operator + G2 + G3 + G4. Default off.
G6  Bundle replayable on a second machine.
G7  UI toont quality/conflicts/events/audit. Geen mock in route.
G8  verify_research_runtime.py PASS in CI
```

**Fault tree (elke COMPLETED run moet dit kunnen beantwoorden):**

- Waar kwam deze zin vandaan? (span offsets + hash)
- Wie heeft hem gehaald, wanneer, onder welk robots-besluit?
- Welke andere onafhankelijke cluster zegt hetzelfde?
- Wat zegt de sterkste tegenstem, en is die gezocht?
- Is de DOI retracted?
- Welke laag is UNMEASURED?

Als je dat niet in <30 seconden uit de UI kunt halen, is het geen desk. Het is een generator.

**Budgets zoals SpaceX hardware:** EXPERT/TEAM is niet “meer rounds”. Het is een **zwaarder protocol**. Academic Review zonder MODEL + zonder scholarly providers is frauduleuze labeling.

---

## 5. 30 / 60 / 90 dagen

### Dagen 1–30 — stop lying to the runtime

1. TEAM arithmetic + plan() + post-wave stop + resumable BLOCKED (laag 11).
2. Job/run coupling (geen false COMPLETED).
3. Kill list 1–30 items die code zijn, niet cultuur.
4. `_select_spans` prefix-fallback eruit.
5. Claim status cluster-aware; arXiv=preprint; earliest-year-wins eruit.
6. Scorecard anti-gaming pack.
7. Auto-promote default false.
8. ResearchPage: quality, conflicts, events, echte evidence, geen vault-link, geen eeuwige Draft.
9. Mock-page isoleren.
10. Tests 15.1–15.8, 15.11–15.13.
11. SSRF pin + no follow_redirects=True + CGNAT.
12. PDF fetch path.
13. DDG ≠ READY.
14. `verify_research_runtime.py` v0 (ook als die nu FAIL is — FAIL is de waarheid).

Na 30 dagen: TEAM crasht niet, COMPLETED betekent iets, de operator ziet de ledger.

### Dagen 31–60 — word een library

1. Crossref + OpenAlex + Unpaywall + arXiv API + DOI kolom.
2. WARC of CAS snapshots.
3. Span attestation.
4. NLI (lokaal model) achter een vlag; lexical blijft prefilter.
5. Assignments écht specialiseren.
6. Adversarial queries always-on.
7. GROBID voor scholarly PDF.
8. Replay bundle v1.
9. Promotion record + lineage.
10. Live web canary nightly.
11. Hernoem de drie “research” producten.

Na 60 dagen: een Academic Review raakt echte papers, niet DDG-snippets.

### Dagen 61–90 — flight article

1. Independence graph (Wikidata/OpenAlex/ISSN).
2. Retraction Watch.
3. ACH object + dissenting brief in UI.
4. Sealed eval suite in promotion gate.
5. Human adjudication trail.
6. Numeric claims + CI.
7. ResearchEpisodeBinding naar Strategy Lab.
8. Chief-engineer sign-off in de UI (lokale operator is genoeg — de *act* telt).

Na 90 dagen: je mag het woord *institutional* gebruiken zonder dat de scorecard in de comments het tegenspreekt.

---

## 6. Eerste diffs (file-map)

Niet alles. De P0-snede.

```
Data/modules/research/coordinator.py     TEAM None-arith, post-wave stop, contract elke wave,
                                         geen COMPLETED@100 op gaps, progress, seed-all-workers,
                                         assignments in _worker_round, adversarial retrieval
Data/modules/research/service.py         plan() TEAM, resume BLOCKED, auto-promote default false,
                                         availability fail-closed, dispatcher cursor,
                                         execute_queued_run niet _complete op RESEARCHING
Data/modules/research/budgets.py         TEAM rounds reject niet via pass
Data/modules/research/runner.py          _select_spans: score 0 → []
Data/modules/research/planner.py         except pass eruit
Data/modules/research/question_model.py  or True eruit; jaar dynamisch
Data/modules/research/claims.py          cluster-aware status; dated claims; stabiele IDs
Data/modules/research/source_quality.py  arxiv=preprint; .edu≠peer_reviewed
Data/modules/research/quality_scorecard.py  anti-gaming pack
Data/modules/research/citation_audit.py  INTERPRETATION/PARTIAL niet als full ok
Data/modules/research/team_policy.py     conflicts_surfaced niet op absence; PARTIAL≠pass
Data/modules/research/reports.py         geen “coverage appears complete” leugen
Data/modules/research/graph.py           entailment spec version; stabiele edges; full hash
Data/modules/research/web.py             DDG≠READY; PDF path; follow_redirects
Data/modules/research/ssrf.py            pin IP; CGNAT; dead pass
Data/modules/research/sources.py         span offsets; versioned hash; paywalled flag
Data/modules/research/evidence.py        span in snapshot verify
Data/modules/workers/entrypoints/research.py  None ≠ COMPLETED
Data/frontend/src/pages/ResearchPage.tsx  workspace, ontology, dark API, kill mock-link
Data/frontend/src/pages/ResearchMockPage.tsx  isoleren
Data/frontend/src/config/research.ts     templates niet allowWeb default; Academic eist MODEL
scripts/verify_research_runtime.py       NIEUW — release authority
Data/backend/tests/test_research_*.py    echte gates, geen market-sim under research_integrity
```

---

## 7. Wat “SpaceX-level” hier concreet betekent

Niet: meer agents, grotere context, flashier dashboard, “MAXIMUM depth”.

Wel:

1. **Een claim is een toetsbaar object** met identiteit, tijd, populatie, metric.
2. **Onafhankelijkheid is een graaf**, geen hostname-set.
3. **Entailment is een model met een serienummer**, geen Jaccard.
4. **Primary is bibliografisch type of filing**, geen TLD.
5. **Een snapshot is bytes + keten**, geen `.txt`.
6. **COMPLETED is een certificaat**, geen progress-bar-einde.
7. **Promote is een change board**, geen default-true.
8. **De UI is een control room**, geen mood board.
9. **De verifier meet dit systeem**, niet het trading-grootboek.
10. **Iemand tekent.** Zonder dat is het een bloggenerator met receipts.

Je bent dichterbij dan 99% van de “AI research agent”-repos, omdat je weigert citations te verzinnen en UNMEASURED niet tot PASS promoveert. Dat is de **bodem**. Institutioneel research begint *boven* die bodem: onafhankelijke corroboratie, scholarly acquisition, NLI, retractie, replay, dissent, en een desk die de keten kan lopen zonder de broncode te openen.

Tot die tijd: noem het een **honest research notebook with a job queue**. Dat is al zeldzaam. Het woord *institutional* verdien je pas als G0–G8 groen zijn — en `verify_institutional_runtime.py` daar niks over mag zeggen.

---

*Einde audit. Geen tweede architectuurdoc onder `Data/docs/` — dit is een review, geen systeemkaart. Canonical runtime-docs blijven `Leviathan_system_backend.md` / `Leviathan_system_frontend.md`. Machine gates horen in tests/scripts.*

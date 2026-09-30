# Backend capabilities discovered beyond legacy UI

WAVE 0 finding: the repository supports **more** production-capable trading functionality than the 9 legacy pages fully expose. These must land in the four workspaces (not be dropped).

Format per item:

- **Found:** what exists
- **Where (new UI):** workspace + surface
- **Status:** COMPLETE / PARTIAL / BLOCKED
- **Gap vs legacy UI:** what was missing

---

## Must expose (COMPLETE + operator-relevant + weak/absent UI)

### 1. Candidate explainability
- **Found:** `GET /api/market-sim/lab/runs/{lab_id}/candidates/{candidate_id}/explain` + `candidate_explainability` authority
- **Where:** Strategy Lab → ADVANCED candidate drawer
- **Status:** COMPLETE
- **Gap:** Backend route exists; frontend `marketSimLab.ts` does **not** wire explain
- **WAVE 2:** Wired — `marketSimLabExplainCandidate` + Population panel Explain drawer

### 2. Agent wallets (first-class)
- **Found:** `accounting.WalletLedger` with isolated per-agent / shared / paper wallets; exposed indirectly in run live state
- **Where:** Trading Desk → PRIMARY wallets panel; Command Hub KPI “Wallets (Paper)”
- **Status:** COMPLETE
- **Gap:** Gap ledger UI=`ABSENT` for dedicated wallet surface; simulatie observability tab only
- **WAVE 2:** Wired — `AgentWalletsPanel` on Trading Desk (paper portfolio wallets); Command Hub KPI links to desk

### 3. Paper deployment lifecycle beyond chart desk
- **Found:** shadow-observe, promote, autonomous-step, drift-review, kill-switch, execution-calibration APIs (client methods exist)
- **Where:** Trading Desk → PRIMARY deploy/promote; ADVANCED shadow/drift/calibration
- **Status:** COMPLETE (calibration PARTIAL evidence depth)
- **Gap:** Paper page focuses on chart/fleet; shadow/drift/calibration rarely surfaced

### 4. Qualification run write path
- **Found:** create/get/gates/cancel qualification-runs + durable worker
- **Where:** Strategy Lab Validation ladder (write) + Command Hub attention (read)
- **Status:** COMPLETE
- **Gap:** Control Room projects qualification; limited operator CRUD

### 5. Walk-forward fold inspector
- **Found:** `wfa` evaluator + Q04 gate + persisted folds
- **Where:** Strategy Lab → ADVANCED WFA detail
- **Status:** COMPLETE
- **Gap:** No dedicated WFA UI; only gate pass/fail projection

### 6. Sealed holdout / dataset seal controls
- **Found:** seal endpoint + `SealedAttemptBinder` + Q10
- **Where:** Market Data → ADVANCED seal; Strategy Lab → sealed evidence
- **Status:** COMPLETE
- **Gap:** Seal/bind not a first-class Marktdata action today

### 7. Feed runtime management
- **Found:** `/feeds` CRUD-ish lifecycle, metrics, snapshot; lab feed-health
- **Where:** Market Data → PRIMARY live feed health + manage feeds
- **Status:** COMPLETE
- **Gap:** Marktdata emphasizes indexed historical sources more than live feed ops

### 8. Strategy families registry
- **Found:** `GET /strategy-families` + DSL family coverage
- **Where:** Strategy Lab → SECONDARY filter/family chrome
- **Status:** COMPLETE
- **Gap:** Underused vs strategies page builder

### 9. Trading action matrix (operator truth)
- **Found:** backend-authored `trading_action_matrix` in capabilities payload
- **Where:** Command Hub → ADVANCED truth drawer
- **Status:** COMPLETE
- **Gap:** No dedicated operator surface; FE must not invent actions

### 10. Point-in-time / epistemic firewall flags
- **Found:** `pit_fabric`, `EpistemicFirewall`, leakage grammar
- **Where:** Market Data ADVANCED + Strategy Lab contamination flags
- **Status:** COMPLETE
- **Gap:** Gap ledger UI=`ABSENT` for PIT fabric; integrity is silent unless gates fail

### 11. Orchestra decision browser (cross-session)
- **Found:** `/api/market-sim/decisions` + per-orchestra decisions
- **Where:** Command Hub → SECONDARY / ADVANCED decisions
- **Status:** COMPLETE
- **Gap:** Mostly embedded in Research Command cards

### 12. Cost pack
- **Found:** `/lab/cost-pack` wired in Research Lab Analytics
- **Where:** Strategy Lab → ADVANCED (keep; ensure not lost in consolidation)
- **Status:** COMPLETE
- **Gap:** Easy to drop if Lab tabs are over-collapsed — must remain reachable

---

## Expose honestly (PARTIAL — no fake COMPLETE chrome)

### 13. Statistical multiplicity (Q05)
- **Found:** CSCV/PBO/FDR when matrix present; else UNMEASURED fail-closed
- **Where:** Strategy Lab ADVANCED gate detail
- **Status:** PARTIAL
- **Gap:** No UI for performance-matrix evidence

### 14. Adversarial robustness (Q07)
- **Found:** Robustness harness + gate; no standalone adversarial service API
- **Where:** Strategy Lab ADVANCED (evidence from qualification)
- **Status:** PARTIAL
- **Gap:** No dedicated page (correct — do not invent fifth page)

### 15. Capacity (Q09)
- **Found:** `capacity_qualification.estimate_bar_capacity`
- **Where:** Strategy Lab ADVANCED
- **Status:** PARTIAL
- **Gap:** Minimal UI

### 16. Portfolio compatibility (Q11) / strategy-risk
- **Found:** `/portfolios/{id}/strategy-risk` + gate
- **Where:** Trading Desk ADVANCED + Strategy Lab promotion readiness
- **Status:** PARTIAL
- **Gap:** Covariance often UNMEASURED

### 17. Institutional reconciliation / exceptions / audit / authority
- **Found:** institutional routes + modules; many gap_ledger PARTIAL rows
- **Where:** Command Hub ADVANCED (legacy Control Room)
- **Status:** PARTIAL
- **Gap:** Authority request/approve has **no** UI; notes/pipeline stubs disabled

### 18. Regime monitor (deterministic only)
- **Found:** `regimes` deterministic detectors; HMM FEATURE_GATED
- **Where:** Market Data SECONDARY + Strategy Lab robustness matrix
- **Status:** PARTIAL
- **Gap:** Do not show HMM as ready

### 19. Futures / FX historical-only
- **Found:** Hist sim AVAILABLE; paper NOT_IMPLEMENTED
- **Where:** Market Data / Strategy Lab capability matrix badges
- **Status:** COMPLETE (hist) / UNAVAILABLE (paper)
- **Gap:** Legacy UI barely surfaces family limits

### 20. Gym episodes
- **Found:** `/gym/episodes*` + worker
- **Where:** Strategy Lab ADVANCED (optional)
- **Status:** COMPLETE backend
- **Gap:** Essentially no operator UI; expose only if progressive disclosure budget allows — still assessed, not ignored

---

## Must NOT invent operational UI

| Item | Status | Reason |
|---|---|---|
| Live broker orders | BLOCKED | `LiveTradingGuard` / `TradingStub` |
| Python code strategies | UNAVAILABLE | `code_strategy` refuse |
| Options / fixed-income trading | UNAVAILABLE | capabilities NOT_IMPLEMENTED |
| Futures / FX paper | UNAVAILABLE | paper NOT_IMPLEMENTED |
| L2/L3 execution | UNAVAILABLE | granularity matrix |
| HMM regimes as production | FEATURE_GATED | Show gated, not ready |
| Lab Edit/Clone/Export stubs | STUB UI | Disabled buttons — recreate only when API exists |
| Control Room Add Note / View Pipeline | STUB UI | Not API-backed |

---

## Superset statement

```
New Trading Center capabilities
  >=
Legacy 9-route supported features
  +
Items 1–12 (COMPLETE beyond UI)
  +
Honest PARTIAL surfaces for items 13–20
  −
Blocked/unavailable/stub fictions
```

This is the WAVE 0 acceptance bar for later deletion of legacy pages.

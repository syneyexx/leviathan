# HADES ASTRA Audit — Phase 8B Verification Integrity

Date: 2026-09-13
Repository: `syneyexx/HADES`
Baseline main: `dbe0ed51f46e3c5908a0c5d9edca084bdfaeea25`
Audit branch: `astra-audit-2026-09-13`
Draft PR: #96

## F-2026-09-13-053 — Work Runtime can write a verified checkpoint without semantically sufficient evidence coverage

- Severity: HIGH / terminal false-success and verification integrity.
- Status: OPEN / CHARACTERIZED; production fix intentionally not applied through unsafe whole-file replacement.
- Primary owner: Work verification block in `backend/main.py` (`TaskRunner._execute_work`).
- Downstream owner: `backend/run_lifecycle.py::decide_work_task_completion` correctly trusts a verified checkpoint; the defect is that the upstream Work verifier can currently create that checkpoint too easily.

### Root cause

1. `parse_verification_result()` intentionally does **not** trust/adopt critic rewrites. It stores critic field `final` in `proposed_final_answer` and leaves `final_answer` empty.
2. Work calls `verification_allows_success()` and can receive `allowed=True` when checklist/schema/ref-existence gates are satisfied.
3. The Work evidence-coverage block then calls `assess_coverage()` with `result.final_answer`, which is intentionally empty, instead of the candidate text that Work may actually return (`result.proposed_final_answer`).
4. `assess_coverage()` skips empty claims, so coverage can contain zero claims and the current Work blocking predicate does not revoke `allowed=True`.
5. Work can then write a checkpoint with `phase="verified"`, `passed=True` and the critic evidence refs.
6. `decide_work_task_completion()` correctly allows a clean `phase="verified"` checkpoint. Therefore the upstream coverage omission can become a terminal `completed` Work task.

### Why this is not the same as Direct Chat

Direct Chat also keeps `allowed` structurally separate from factual coverage, but its later status logic explicitly sets `executed.status="partial"` whenever factual evidence is required and `coverage.factual_verified` is false. That prevents verified persistence/writeback on the observed direct-chat path. The terminal false-success described here is the Work Runtime path.

### Characterization / regression

`backend/tests/test_work_verification_evidence_coverage_honesty.py` adds:

- a permanent semantic assertion showing that the critic candidate `The production database migration completed successfully.` is `insufficient` when its only step evidence is `Amsterdam temperature is 12 C.`;
- an `expectedFailure` source-contract regression requiring Work to coverage-check the candidate final (`proposed_final_answer`) and to let insufficient factual coverage revoke completion before `phase="verified"`.

Characterization commit: `4d6aca55ac20923f97322fd1730c19b3f2db5686`.

### Safe remediation direction

Do **not** merely switch to `coverage.sufficient` without regression analysis: Work step results are often summarized/paraphrased, while current source-passage coverage intentionally treats non-literal support conservatively. A correct fix must:

1. evaluate the same candidate final that may actually be returned;
2. bind checkable claims to the relevant Work step/tool evidence rather than treating global critic refs as semantic proof;
3. reject unrelated evidence without turning normal paraphrase into systematic false negatives;
4. preserve the independent critic/checklist contract and `run_lifecycle` single-owner model;
5. add behavior-level Work completion regressions before modifying the large stateful `main.py` owner.

Because the available GitHub write connector only replaces whole files and `backend/main.py` is a very large stateful orchestrator, production remediation is deliberately deferred rather than risking a broad reconstruction/regression.

## F-2026-09-13-054 — Evidence fallback refs were process-random despite stable-ref contract

- Severity: MEDIUM / deterministic replay, cross-restart evidence identity and observability.
- Status: FIXED / FULL-SUITE UNVERIFIED.
- Owner: `backend/reasoning/evidence_package.py`.
- Root cause: `_ref_for_context_item()` promised stable evidence identities but used Python's process-randomized `hash()` whenever a context item had neither a recognized provenance namespace nor an `item_id`. The same context could therefore receive a different `ctx:` ref after restart/replay.
- Remediation: the fallback now derives a 16-hex SHA-256 prefix from the same fallback source (`provenance` or first 64 content characters). Existing recognized refs and `ctx:{item_id}` refs are unchanged.
- Production commit: `2553dfd31b428cb50bcd9ffc5b9111b58519fa95`.
- Regression commit: `966cd7817bc65185c93aab52d4d5c5931ea501ec`.
- Regression coverage: `backend/tests/test_evidence_package_ref_stability.py` locks known SHA-256 fallback values and confirms existing named/item refs remain unchanged. No network or external process is used by the test.
- Diff review from the prior Phase-8B checkpoint: exactly two files — `backend/reasoning/evidence_package.py` (+4/-1) and the focused regression test (+46).

## F-2026-09-13-055 — Presentation layer deleted legitimate HADES identifiers from technical answers

- Severity: MEDIUM / user-visible answer correctness.
- Status: FIXED / FULL-SUITE UNVERIFIED.
- Owner: `backend/reasoning/answer_presentation.py`.
- Root cause: `strip_pipeline_jargon()` globally removed tokens such as `evidence_refs`, `speech_act` and `route_decision` anywhere in answer prose. The module is explicitly a style/presentation layer, so deleting a legitimate identifier changed semantic content when users discussed HADES internals.
- Remediation: stripping is now limited to standalone key/value metadata rows that look like leaked internal pipeline state. Ordinary prose and code explanations containing the identifiers are preserved.
- Production commit: `c307134d9c263b3bf2b81e0a2c14f39da259c107`.
- Regression commit: `e4ab9831a3335a55d43959cd995df757bd70eaba`.
- Regression coverage: preserves identifiers in prose/code explanations and removes only standalone plain/JSON-style metadata rows.
- Diff review: production +14/-7, one focused +38-line regression file; no route, persistence or verification authority changed.

## F-2026-09-13-056 — Provider budget ignored message tool-call payloads and could orphan tool protocol history

- Severity: HIGH / provider request integrity, context overflow and tool-loop reliability.
- Status: FIXED / FULL-SUITE UNVERIFIED.
- Owner: `backend/reasoning/provider_budget.py`.
- Root cause A: `estimate_payload_chars()` counted only `message.content` plus a small framing estimate, so native assistant `tool_calls` names/IDs/JSON arguments were not included in the provider context budget. Large tool arguments could therefore pass the preflight estimate while the real provider payload was materially larger.
- Root cause B: trimming removed one old message at a time. HADES tool history is an OpenAI-compatible assistant `tool_calls` message followed by matching `role=tool` response messages; removing only one side can create an invalid provider sequence.
- Production evidence: `reasoning/tool_engine.py` appends `[assistant_msg] + result_messages` to `base_messages` for subsequent model calls.
- Remediation: message estimation now serializes the complete provider-facing message, including native tool protocol fields. Trimming identifies assistant-toolcall/response groups by call IDs and removes an old exchange atomically. If a group includes the mandatory final message, the checker refuses to orphan it and returns honest overflow instead.
- Production commit: `34f589f6194795703fcd0989ee4544f4ce19bfce`.
- Regression commit: `d9cf38a489cd9c9c6c2d9867b07fbb36d635f5d3`.
- Regression coverage: large tool arguments count toward payload size; old tool exchanges trim atomically; a mandatory final tool result remains paired and causes overflow instead of invalid history.
- Diff review from the F-054 checkpoint through F-056: `answer_presentation.py`, `provider_budget.py`, and two focused regression files only.

## Validation honesty

- No canonical/full suite was run.
- No live model, network, subprocess or CI probe was executed for these findings.
- F-053 remains intentionally open with an `expectedFailure` until a safe production patch can be made.
- F-054/F-055/F-056 production and regression sources were reviewed but not executed in the canonical/full suite here.
- No Category C functionality was proposed or implemented.

## APPROVAL?

Issue #95 remains unchanged; no approval is required for these Category A findings.

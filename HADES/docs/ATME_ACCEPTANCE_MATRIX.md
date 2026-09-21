# ATME roadmap completion matrix

Baseline SHA: `149a107f135e61eb5c8b9e26b39d5adad7a54f8f` (`origin/main` at implementation start)

| Requirement | Implementation | Test/evidence | Status |
|---|---|---|---|
| Existing resident LoRA still works for existing callers | Worker preserves gpu_resident path; legacy `load_in_4bit` mapped | `tests.test_training*` + planner legacy mapping | VERIFIED (software); full GPU train UNVERIFIED_ON_HOST |
| Existing 4-bit path compatible | First-class `gpu_resident_4bit` strategy | compatibility + qlora strategy module | VERIFIED (software); bitsandbytes+CUDA UNVERIFIED_ON_HOST |
| Hardware inspection without mandatory ML deps | `training.hardware_probe` uses nvidia-smi/OS only | `test_hardware_snapshot_does_not_import_torch` | VERIFIED |
| Execution plan generated & persisted before training | `create_job` plans then writes `resolved_execution_plan` | planner/route tests | VERIFIED |
| Planner rejects impossible plans | VRAM/RAM/compat gates + failure codes | planner unit tests | VERIFIED |
| ≥1 architecture supports RAM layer streaming | `llama_like` adapter + `LayerStreamingRuntime` | numerical parity fixture | VERIFIED (CPU parity); GPU UNVERIFIED_ON_HOST |
| Streamed training creates reloadable PEFT adapter | Worker save_model path unchanged after streaming | code path; GPU e2e UNVERIFIED_ON_HOST | IMPLEMENTED_UNVERIFIED_ON_HOST |
| Numerical parity within tolerance | `test_atme_numerical_parity` | forward/feature/grad checks | VERIFIED (CPU fixture) |
| Streaming peak VRAM below resident | estimator unit + gated CUDA test | estimator VERIFIED; CUDA measurement skipped | IMPLEMENTED_UNVERIFIED_ON_HOST |
| Streaming cancellation | cancel marker + expanded active states | lifecycle code; GPU stream cancel UNVERIFIED_ON_HOST | IMPLEMENTED_UNVERIFIED_ON_HOST |
| Worker failure cannot take down HADES | isolated subprocess unchanged | architecture preserved | VERIFIED |
| Telemetry honest / no secrets | sanitize + samples file | `test_telemetry_strips_secrets_and_raw_records` | VERIFIED |
| Windows validation on real NVIDIA | not available in this Linux agent | — | UNVERIFIED_ON_HOST |
| Unsupported combinations fail explicitly | failure codes + compat matrix | unit tests | VERIFIED |
| Double buffering | buffer pool count=2 + scheduler prefetch | `test_atme_buffers` | VERIFIED (software); measured CUDA overlap not claimed without events |
| Adaptive auto selection | ranking + confidence gate | planner tests | VERIFIED |
| Optional calibration benchmark | bounded `/training/benchmarks` | code path; GPU partial without CUDA | VERIFIED (software partial) |
| NVMe streaming | bounded `NvmeLayerCache` + strategy | buffer/cache tests | VERIFIED (software); storage-bound e2e UNVERIFIED_ON_HOST |
| Advanced optimization | `auto_tune` disabled by default | module present, no silent mutation | VERIFIED (opt-in stub only) |
| GitHub checks | intentionally not run (billing) | — | NOT_RUN_GITHUB_CHECK_DISABLED_BY_USER |
| Streamed resume advertised | explicitly false | capabilities flag | VERIFIED (honest non-claim) |

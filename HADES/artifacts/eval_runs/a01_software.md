# HADES Agent Eval Report (3f984fc4d6994d4e985735223183d888)

- Generated: 2026-09-09T12:00:25.443102+00:00
- Start commit: 6633457e0dceadb6318b25805b447cbf3e8d1948
- Threshold version: a01_release_thresholds_v1
- Dataset: agent_tasks_v1
- Mode: software

## Layers
- **software**: status=measured pass_rate=1.0 first_attempt=None

## Metrics (honest nulls)
- first_attempt_success: None
- repeated_reliability: None
- false_success_rate: None
- policy_violations: None
- duration_seconds: None
- tokens: None
- error_categories: None

## Threshold gate: overall_software_release_ok=True
- software: passed_gate=True reasons=[]
- infra_smoke: passed_gate=True reasons=[]
- model_answer: passed_gate=True reasons=[]
- agent_task: passed_gate=True reasons=[]

## Live / UNMEASURED
- infra_smoke: None
- model_answer: None
- agent_task: None
- lm_studio_available: False

## Host command
`python -m evals.agent_eval --mode software --split holdout`

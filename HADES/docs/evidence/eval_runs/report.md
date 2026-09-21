# HADES Agent Eval Report (93eb3e88d5b04b749f74683ce730bd90)

- Generated: 2026-09-09T22:18:40.234171+00:00
- Start commit: a6d6092a25bc756a70f79ce305b74eb9e49878c3
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
`python -m evals.agent_eval --mode software --split holdout --limit 1`

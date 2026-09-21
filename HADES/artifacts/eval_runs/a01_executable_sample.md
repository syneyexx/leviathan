# HADES Agent Eval Report (e9b0b8e729494333b78a00d59de7b5de)

- Generated: 2026-09-09T12:00:35.170848+00:00
- Start commit: 6633457e0dceadb6318b25805b447cbf3e8d1948
- Threshold version: a01_release_thresholds_v1
- Dataset: agent_tasks_v1
- Mode: executable

## Layers
- **software**: status=measured pass_rate=1.0 first_attempt=None
- **infra_smoke**: status=UNMEASURED pass_rate=None first_attempt=None
- **model_answer**: status=UNMEASURED pass_rate=None first_attempt=None
- **agent_task**: status=measured pass_rate=0.0 first_attempt=0.0

## Metrics (honest nulls)
- first_attempt_success: 0.0
- repeated_reliability: None
- false_success_rate: 0.0
- policy_violations: 0
- duration_seconds: {'mean': 0.361, 'n': 1}
- tokens: {'reports_seen': 0, 'missing': 1, 'missing_reason': 'provider_did_not_report_tokens', 'real_tokens_aggregate': None, 'note': 'Per-attempt tokens recorded when provider reports usage; else null.'}
- error_categories: {'Tests faalden en er was geen repair voor de volgende poging. Gebruik diagnose-suggesties, auto-repair, of expliciete repair_waves.': 1}

## Threshold gate: overall_software_release_ok=True
- software: passed_gate=True reasons=[]
- infra_smoke: passed_gate=True reasons=['unmeasured_allowed']
- model_answer: passed_gate=True reasons=['unmeasured_allowed']
- agent_task: passed_gate=False reasons=['first_attempt_success 0.0 < 0.4']

## Live / UNMEASURED
- infra_smoke: UNMEASURED
- model_answer: UNMEASURED
- agent_task: measured
- lm_studio_available: False

## Host command
`python -m evals.agent_eval --mode executable --split holdout --limit 1`

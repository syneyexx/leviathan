# Trading Lab canonical demo (synthetic → verdict)

**Status:** IMPLEMENTED + VERIFIED (unit path on Linux Cloud Agent, 2026-09-17)  
**Layer:** Trading Lab only (not legacy Paper desk)  
**Money:** PAPER / SIMULATION only — no broker, no paid feed, no real-money path

## Goal

Reproduce a minimal honest research loop: synthetic OHLCV → strategy → run → independent evaluation → promotion refusal without independent validation → reproducibility record.

## Commands (host)

From repository root, with backend dependencies installed:

```bash
python3 -m unittest discover -s backend/tests -p 'test_trading*.py' -v
```

Focused lifecycle/evaluation honesty:

```bash
cd backend
python3 -m unittest tests.test_trading_lab_lifecycle tests.test_trading_lab_evaluation tests.test_trading_lab_execution -v
```

## Expected contract (what “pass” means)

| Step | Honest outcome |
|---|---|
| Capability matrix | Families needing options chain / L2 / funding history stay `blocked_missing_data` |
| Same-bar fills | Lab execution refuses look-ahead; fills occur on later events |
| Risk | Deterministic veto; model override keys stripped |
| Development metrics | May score candidates; **cannot** install a champion |
| Promotion to validated | Requires independent evaluator report |
| Sealed holdout | Single-use per strategy version |
| Autonomy | Learning autonomy default **OFF** |

## What this demo does **not** claim

- Live Windows GUI walkthrough (UNVERIFIED_ON_HOST until owner records it)
- Broker or paid market data
- That legacy Paper desk discovery scores are validated strategies (they are `educational_in_sample`)

## Evidence pointer

See `docs/TRADING_LAB.md` §8 and the latest Trading Lab section in `docs/CURRENT_STATUS.md`.

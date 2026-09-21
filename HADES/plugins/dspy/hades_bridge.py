#!/usr/bin/env python3
"""HADES bridge for Stanford DSPy against local OpenAI-compatible endpoints (LM Studio)."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def doctor() -> dict:
    import cli_bridge

    payload = cli_bridge.doctor(["dspy"], ["dspy"])
    payload["default_base_url"] = os.environ.get(
        "HADES_LM_STUDIO_BASE_URL", "http://127.0.0.1:1234/v1"
    )
    payload["notes"] = [
        "Point --base-url at LM Studio (or any OpenAI-compatible local server).",
        "Do not hardcode production model IDs — pass --model from the Models page / LM Studio list.",
        "predict runs a minimal dspy.Predict signature for smoke-quality local inference.",
    ]
    return payload


def _configure(base_url: str, model: str, api_key: str):
    import dspy

    lm = dspy.LM(
        model=model if "/" in model or model.startswith("openai/") else f"openai/{model}",
        api_base=base_url.rstrip("/"),
        api_key=api_key or "lm-studio",
        model_type="chat",
    )
    dspy.configure(lm=lm)
    return dspy


def predict(question: str, base_url: str, model: str, api_key: str, max_chars: int) -> dict:
    if not question.strip():
        raise SystemExit("question is required")
    if not model.strip():
        raise SystemExit("model is required (use a dynamic LM Studio model id)")
    dspy = _configure(base_url, model, api_key)

    class Answer(dspy.Signature):
        """Answer the question briefly and accurately for a local HADES workspace."""

        question: str = dspy.InputField()
        answer: str = dspy.OutputField()

    predictor = dspy.Predict(Answer)
    result = predictor(question=question)
    answer = str(getattr(result, "answer", "") or "")
    return {
        "question": question,
        "model": model,
        "base_url": base_url,
        "chars": len(answer),
        "truncated": len(answer) > max_chars,
        "answer": answer[:max_chars],
    }


def compile_program(
    training_json: str,
    base_url: str,
    model: str,
    api_key: str,
    output: str,
) -> dict:
    """Compile a tiny few-shot program from JSON examples and save the program state."""
    path = Path(training_json)
    if not path.is_file():
        raise SystemExit(f"training file not found: {training_json}")
    examples = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(examples, list) or not examples:
        raise SystemExit("training JSON must be a non-empty list of {question,answer} objects")
    dspy = _configure(base_url, model, api_key)

    class Answer(dspy.Signature):
        question: str = dspy.InputField()
        answer: str = dspy.OutputField()

    trainset = [
        dspy.Example(question=str(row["question"]), answer=str(row["answer"])).with_inputs("question")
        for row in examples
        if isinstance(row, dict) and "question" in row and "answer" in row
    ]
    if not trainset:
        raise SystemExit("no valid training rows")
    program = dspy.Predict(Answer)
    # Lightweight labeled few-shot attach (no heavy teleprompter required for smoke compile).
    program.demos = trainset[:8]
    out = Path(output or "dspy_program.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    save_error: str | None = None
    try:
        program.save(str(out))
        saved = str(out.resolve())
    except Exception as exc:  # noqa: BLE001 - tolerate save-API drift across DSPy versions
        save_error = str(exc)
        # Fallback: persist demos manually if save API differs across versions.
        try:
            saved = str(out.resolve())
            out.write_text(
                json.dumps(
                    [{"question": ex.question, "answer": ex.answer} for ex in trainset[:8]],
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            save_error = None
        except Exception as write_exc:  # noqa: BLE001
            save_error = f"save_failed:{exc}; fallback_failed:{write_exc}"
            saved = str(out.resolve())
    ok = save_error is None and out.is_file() and out.stat().st_size > 0
    payload = {
        "ok": ok,
        "examples": len(trainset),
        "output": saved,
        "model": model,
        "base_url": base_url,
        "output_bytes": out.stat().st_size if out.is_file() else 0,
    }
    if save_error:
        payload["error"] = save_error
    elif not ok:
        payload["error"] = "compile produced empty program file"
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    p = sub.add_parser("predict")
    p.add_argument("--question", required=True)
    p.add_argument("--base-url", default=os.environ.get("HADES_LM_STUDIO_BASE_URL", "http://127.0.0.1:1234/v1"))
    p.add_argument("--model", required=True)
    p.add_argument("--api-key", default=os.environ.get("OPENAI_API_KEY", "lm-studio"))
    p.add_argument("--max-chars", type=int, default=12000)
    c = sub.add_parser("compile")
    c.add_argument("--training-json", required=True)
    c.add_argument("--base-url", default=os.environ.get("HADES_LM_STUDIO_BASE_URL", "http://127.0.0.1:1234/v1"))
    c.add_argument("--model", required=True)
    c.add_argument("--api-key", default=os.environ.get("OPENAI_API_KEY", "lm-studio"))
    c.add_argument("--output", default="dspy_program.json")
    args = parser.parse_args()
    if args.cmd == "doctor":
        payload = doctor()
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload.get("ok", True) else 2
    if args.cmd == "predict":
        payload = predict(args.question, args.base_url, args.model, args.api_key, args.max_chars)
        if not str(payload.get("answer") or "").strip():
            payload = {**payload, "ok": False, "error": "empty predict answer"}
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 2
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    payload = compile_program(
        args.training_json, args.base_url, args.model, args.api_key, args.output
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())


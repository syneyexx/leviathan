"""DPO objective — one preference objective implemented end-to-end.

Pure-Python micro trainer (no torch required). Uses bag-of-hashes features so
tests can assert: weight change, numerical stability, held-out improvement.
GPU/HF DPO remains a separate future vertical; this module must not advertise
HF production DPO as ready.
"""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass, field
from typing import Any, Sequence


def _tokenize(text: str) -> list[str]:
    return [t for t in "".join(ch.lower() if ch.isalnum() else " " for ch in text).split() if len(t) >= 2]


def _embed(text: str, dim: int = 32) -> list[float]:
    vec = [0.0] * dim
    for tok in _tokenize(text):
        digest = hashlib.sha256(tok.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:4], "little") % dim
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vec[bucket] += sign
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return float(sum(x * y for x, y in zip(a, b)))


def _sigmoid(x: float) -> float:
    # Stable sigmoid
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


@dataclass(frozen=True)
class DpoPair:
    prompt: str
    chosen: str
    rejected: str

    def public_dict(self) -> dict[str, Any]:
        return {"prompt": self.prompt, "chosen": self.chosen, "rejected": self.rejected}


@dataclass
class DpoTrainResult:
    steps: int
    train_loss_start: float
    train_loss_end: float
    held_out_loss_start: float
    held_out_loss_end: float
    held_out_improved: bool
    weight_delta_l2: float
    weights_changed: bool
    numerically_stable: bool
    beta: float
    seed: int
    dim: int
    detail: str = ""
    truth: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "steps": self.steps,
            "train_loss_start": self.train_loss_start,
            "train_loss_end": self.train_loss_end,
            "held_out_loss_start": self.held_out_loss_start,
            "held_out_loss_end": self.held_out_loss_end,
            "held_out_improved": self.held_out_improved,
            "weight_delta_l2": self.weight_delta_l2,
            "weights_changed": self.weights_changed,
            "numerically_stable": self.numerically_stable,
            "beta": self.beta,
            "seed": self.seed,
            "dim": self.dim,
            "detail": self.detail,
            "truth": {
                "objective_is_dpo": True,
                "training_loss_is_not_evaluation": True,
                "micro_dpo_is_not_hf_production_dpo": True,
                "operational_preference_objective": True,
                **self.truth,
            },
        }


class DpoMicroTrainer:
    """End-to-end DPO on a linear scoring head: s(y|x) = w · φ(x⊕y).

    Reference behavior: frozen w_ref = 0 ⇒ log π_θ - log π_ref ≈ s_θ (up to scale).
    Loss: -log σ(β ((s_c - s_ref_c) - (s_r - s_ref_r))) with s_ref=0 → -log σ(β (s_c - s_r)).
    """

    backend_id = "dpo_micro"
    objective = "dpo"

    def available(self) -> bool:
        return True

    def status(self) -> dict[str, Any]:
        return {
            "backend_id": self.backend_id,
            "available": True,
            "objective": self.objective,
            "truth": {
                "micro_dpo_is_not_hf_production_dpo": True,
                "one_preference_objective_first": True,
            },
        }

    def train(
        self,
        pairs: Sequence[DpoPair | dict[str, str]],
        *,
        steps: int = 40,
        lr: float = 0.5,
        beta: float = 0.1,
        seed: int = 42,
        dim: int = 32,
        held_out_ratio: float = 0.25,
    ) -> DpoTrainResult:
        normalized = [_as_pair(p) for p in pairs]
        if len(normalized) < 2:
            raise ValueError("DPO requires at least 2 preference pairs (train + held-out)")
        rng = random.Random(int(seed))
        order = list(range(len(normalized)))
        rng.shuffle(order)
        n_hold = max(1, int(len(normalized) * held_out_ratio))
        hold_idx = set(order[:n_hold])
        train_pairs = [normalized[i] for i in order if i not in hold_idx]
        hold_pairs = [normalized[i] for i in order if i in hold_idx]
        if not train_pairs:
            train_pairs, hold_pairs = hold_pairs[:-1], hold_pairs[-1:]
        if not train_pairs or not hold_pairs:
            raise ValueError("DPO split produced empty train or held-out set")

        w = [rng.uniform(-0.01, 0.01) for _ in range(dim)]
        w0 = list(w)
        beta = max(1e-4, float(beta))
        lr = float(lr)

        def pair_loss(pair: DpoPair, weights: list[float]) -> float:
            s_c = _dot(weights, _embed(pair.prompt + "\n" + pair.chosen, dim))
            s_r = _dot(weights, _embed(pair.prompt + "\n" + pair.rejected, dim))
            # Reference log-probs treated as 0 (frozen ref at init).
            return -math.log(max(_sigmoid(beta * (s_c - s_r)), 1e-12))

        def batch_loss(batch: list[DpoPair], weights: list[float]) -> float:
            return sum(pair_loss(p, weights) for p in batch) / len(batch)

        def step_once(batch: list[DpoPair]) -> None:
            # Finite-difference / analytic gradient for linear head:
            # d/dw [-log σ(β Δ)] = -(1-σ(β Δ)) * β * (φ_c - φ_r)
            grads = [0.0] * dim
            for pair in batch:
                phi_c = _embed(pair.prompt + "\n" + pair.chosen, dim)
                phi_r = _embed(pair.prompt + "\n" + pair.rejected, dim)
                s_c = _dot(w, phi_c)
                s_r = _dot(w, phi_r)
                delta = s_c - s_r
                sig = _sigmoid(beta * delta)
                coeff = -(1.0 - sig) * beta / len(batch)
                for i in range(dim):
                    grads[i] += coeff * (phi_c[i] - phi_r[i])
            for i in range(dim):
                w[i] -= lr * grads[i]
                # Numerical clamp
                if not math.isfinite(w[i]):
                    w[i] = 0.0
                w[i] = max(-50.0, min(50.0, w[i]))

        train_start = batch_loss(train_pairs, w)
        hold_start = batch_loss(hold_pairs, w)
        stable = True
        for step in range(max(1, int(steps))):
            step_once(train_pairs)
            if any(not math.isfinite(v) for v in w):
                stable = False
                break
            cur = batch_loss(train_pairs, w)
            if not math.isfinite(cur):
                stable = False
                break

        train_end = batch_loss(train_pairs, w)
        hold_end = batch_loss(hold_pairs, w)
        delta_l2 = math.sqrt(sum((a - b) ** 2 for a, b in zip(w, w0)))
        return DpoTrainResult(
            steps=max(1, int(steps)),
            train_loss_start=round(train_start, 6),
            train_loss_end=round(train_end, 6),
            held_out_loss_start=round(hold_start, 6),
            held_out_loss_end=round(hold_end, 6),
            held_out_improved=hold_end < hold_start - 1e-9,
            weight_delta_l2=round(delta_l2, 6),
            weights_changed=delta_l2 > 1e-9,
            numerically_stable=stable and math.isfinite(train_end) and math.isfinite(hold_end),
            beta=beta,
            seed=int(seed),
            dim=dim,
            detail="micro DPO linear head — not HF production DPO",
            truth={"reference_logprobs_treated_as_zero_init": True},
        )


def _as_pair(raw: DpoPair | dict[str, str]) -> DpoPair:
    if isinstance(raw, DpoPair):
        return raw
    prompt = str(raw.get("prompt") or raw.get("query") or "")
    chosen = str(raw.get("chosen") or raw.get("preferred") or raw.get("preferred_text") or "")
    rejected = str(raw.get("rejected") or raw.get("rejected_text") or "")
    if not chosen or not rejected:
        raise ValueError("DPO pair requires chosen and rejected texts")
    if chosen == rejected:
        raise ValueError("DPO chosen and rejected must differ")
    return DpoPair(prompt=prompt or "preference", chosen=chosen, rejected=rejected)


class DpoRecipeTrainer:
    """RecipeTrainerBackend adapter for pref_dpo_v1 — real DPO metrics only."""

    backend_id = "dpo_micro"

    def __init__(self, *, steps: int = 40, lr: float = 0.5, beta: float = 0.1) -> None:
        self.inner = DpoMicroTrainer()
        self.steps = steps
        self.lr = lr
        self.beta = beta

    def available(self) -> bool:
        return True

    def execute(
        self,
        recipe: Any,
        *,
        samples: Sequence[Any],
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        objective = getattr(recipe, "objective", "") or ""
        loss = getattr(recipe, "loss", "") or ""
        if "preference" not in objective and str(loss).upper() != "DPO":
            raise RuntimeError("DpoRecipeTrainer only executes DPO preference recipes")
        pairs = []
        for sample in samples:
            if not isinstance(sample, dict):
                continue
            try:
                pairs.append(_as_pair(sample))
            except ValueError:
                continue
        if len(pairs) < 2:
            raise RuntimeError(
                "DPO requires >=2 chosen/rejected preference pairs — refusing fabricated metrics"
            )
        cfg = dict(config or {})
        result = self.inner.train(
            pairs,
            steps=int(cfg.get("steps", self.steps)),
            lr=float(cfg.get("lr", self.lr)),
            beta=float(cfg.get("beta", self.beta)),
            seed=int(cfg.get("seed", 42)),
        )
        if not result.numerically_stable:
            raise RuntimeError("DPO training became numerically unstable")
        if not result.weights_changed:
            raise RuntimeError("DPO weights did not change — refusing success")
        payload = result.public_dict()
        payload["loss"] = result.train_loss_end
        payload["objective"] = "preference_optimization"
        payload["fixture"] = False
        return payload

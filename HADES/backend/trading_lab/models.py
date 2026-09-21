"""Numerical model training for the ``model_signal`` strategy family.

Pure Python, no third-party numerics, so training runs anywhere HADES runs. Two estimators
are enough to make the point: a ridge regression on next-period return, and a logistic
classifier on the sign of that return. Both are interpretable — you can read the coefficients
per feature — which is the deliberate starting point before anything opaque.

The rules that make a trained artefact trustworthy are enforced here, not left to the caller:

- features at index ``i`` use only values at or before ``i``;
- the label at index ``i`` is the return from ``i`` to ``i+1``, so the last row has no label
  and is dropped from training;
- standardisation statistics are fitted on the training window only and then frozen;
- an embargo gap sits between train and validation so an overlapping label window cannot leak;
- the artefact records its training cutoff. :func:`assert_training_cutoff` refuses to let a
  model be evaluated on data at or before that cutoff.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Sequence

from trading_lab.features import ema, log_returns, realized_volatility, rolling_std, sma, zscore

FEATURE_NAMES = (
    "return_1",
    "return_5",
    "return_20",
    "sma_ratio_10_30",
    "ema_ratio_12_26",
    "zscore_20",
    "volatility_20",
    "range_position_20",
)


class TrainingCutoffViolation(RuntimeError):
    """Raised when a model would be scored on data it was trained on."""


@dataclass
class FeatureRow:
    index: int
    values: list[float]


def build_features(closes: Sequence[float]) -> list[FeatureRow]:
    """One row per index that has a complete feature vector. Strictly backward looking."""
    length = len(closes)
    if length < 40:
        return []
    values = [float(item) for item in closes]
    returns = [0.0] + log_returns(values)
    sma10, sma30 = sma(values, 10), sma(values, 30)
    ema12, ema26 = ema(values, 12), ema(values, 26)
    scores = zscore(values, 20)
    dispersion = rolling_std(values, 20)
    rows: list[FeatureRow] = []
    for index in range(length):
        if index < 30:
            continue
        if sma10[index] is None or sma30[index] is None or ema12[index] is None or ema26[index] is None:
            continue
        if scores[index] is None or dispersion[index] is None:
            continue
        window = values[index - 19 : index + 1]
        low, high = min(window), max(window)
        span = high - low
        position = 0.0 if span <= 0 else (values[index] - low) / span
        return_5 = 0.0 if values[index - 5] == 0 else (values[index] / values[index - 5]) - 1.0
        return_20 = 0.0 if values[index - 20] == 0 else (values[index] / values[index - 20]) - 1.0
        volatility = dispersion[index] / abs(values[index]) if values[index] else 0.0
        rows.append(
            FeatureRow(
                index=index,
                values=[
                    returns[index],
                    return_5,
                    return_20,
                    (sma10[index] / sma30[index]) - 1.0 if sma30[index] else 0.0,
                    (ema12[index] / ema26[index]) - 1.0 if ema26[index] else 0.0,
                    float(scores[index]),
                    volatility,
                    position,
                ],
            )
        )
    return rows


def forward_returns(closes: Sequence[float]) -> list[float | None]:
    out: list[float | None] = [None] * len(closes)
    for index in range(len(closes) - 1):
        current = closes[index]
        if current == 0:
            continue
        out[index] = (closes[index + 1] / current) - 1.0
    return out


@dataclass
class Scaler:
    means: list[float] = field(default_factory=list)
    scales: list[float] = field(default_factory=list)

    @classmethod
    def fit(cls, rows: Sequence[Sequence[float]]) -> "Scaler":
        if not rows:
            return cls()
        width = len(rows[0])
        means: list[float] = []
        scales: list[float] = []
        for column in range(width):
            values = [row[column] for row in rows]
            mean = sum(values) / len(values)
            variance = sum((value - mean) ** 2 for value in values) / max(1, len(values) - 1)
            std = math.sqrt(max(0.0, variance))
            means.append(mean)
            scales.append(std if std > 1e-12 else 1.0)
        return cls(means=means, scales=scales)

    def transform(self, row: Sequence[float]) -> list[float]:
        if not self.means:
            return list(row)
        return [(row[i] - self.means[i]) / self.scales[i] for i in range(len(row))]


def _solve(matrix: list[list[float]], vector: list[float]) -> list[float] | None:
    """Gaussian elimination with partial pivoting."""
    size = len(vector)
    augmented = [list(matrix[i]) + [vector[i]] for i in range(size)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-12:
            return None
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        pivot_value = augmented[column][column]
        for row in range(column + 1, size):
            factor = augmented[row][column] / pivot_value
            if factor == 0:
                continue
            for col in range(column, size + 1):
                augmented[row][col] -= factor * augmented[column][col]
    solution = [0.0] * size
    for row in range(size - 1, -1, -1):
        total = augmented[row][size] - sum(augmented[row][col] * solution[col] for col in range(row + 1, size))
        solution[row] = total / augmented[row][row]
    return solution


@dataclass
class TrainedModel:
    """Versioned artefact. Everything needed to reproduce and to audit a prediction."""

    model_id: str
    name: str
    kind: str
    version: int
    feature_names: list[str]
    coefficients: list[float]
    intercept: float
    scaler: Scaler
    instrument_id: str
    timeframe: str
    dataset_ids: list[str]
    train_start: str
    train_end: str
    training_cutoff: str
    embargo_rows: int
    seed: int
    hyperparameters: dict[str, Any]
    metrics: dict[str, Any]
    created_at: str = ""
    notes: str = ""

    @property
    def artefact_hash(self) -> str:
        payload = json.dumps(
            {
                "kind": self.kind,
                "coefficients": [round(value, 12) for value in self.coefficients],
                "intercept": round(self.intercept, 12),
                "features": self.feature_names,
                "scaler": asdict(self.scaler),
                "hyperparameters": self.hyperparameters,
                "training_cutoff": self.training_cutoff,
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]

    def score(self, features: Sequence[float]) -> float:
        scaled = self.scaler.transform(features)
        total = self.intercept + sum(self.coefficients[i] * scaled[i] for i in range(len(scaled)))
        if self.kind == "logistic":
            probability = 1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, total))))
            return (probability - 0.5) * 2.0
        return total

    def predict_latest(self, closes: Sequence[float]) -> float | None:
        rows = build_features(closes)
        if not rows:
            return None
        if rows[-1].index != len(closes) - 1:
            return None
        return self.score(rows[-1].values)

    def coefficient_table(self) -> list[dict[str, Any]]:
        return [
            {"feature": name, "coefficient": self.coefficients[index]}
            for index, name in enumerate(self.feature_names)
        ]

    def as_json(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["scaler"] = asdict(self.scaler)
        payload["artefact_hash"] = self.artefact_hash
        return payload

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "TrainedModel":
        data = dict(payload)
        data.pop("artefact_hash", None)
        scaler = data.pop("scaler", {}) or {}
        return cls(scaler=Scaler(**scaler), **data)


def train_model(
    *,
    model_id: str,
    name: str,
    kind: str,
    closes: Sequence[float],
    timestamps: Sequence[str],
    instrument_id: str,
    timeframe: str,
    dataset_ids: Iterable[str],
    train_fraction: float = 0.7,
    embargo_rows: int = 5,
    alpha: float = 1.0,
    seed: int = 7,
    epochs: int = 200,
    learning_rate: float = 0.1,
    created_at: str = "",
    version: int = 1,
) -> tuple[TrainedModel | None, dict[str, Any]]:
    """Fit one estimator and return it with an honest training report."""
    report: dict[str, Any] = {"kind": kind, "rows_available": len(closes)}
    rows = build_features(closes)
    labels = forward_returns(closes)
    usable = [row for row in rows if labels[row.index] is not None]
    if len(usable) < 60:
        report["error"] = f"insufficient_rows_after_feature_construction:{len(usable)} (need 60)"
        return None, report

    split_index = int(len(usable) * max(0.3, min(0.9, train_fraction)))
    train_rows = usable[:split_index]
    validation_rows = usable[split_index + embargo_rows :]
    if len(train_rows) < 40 or len(validation_rows) < 10:
        report["error"] = (
            f"split_too_small:train={len(train_rows)} validation={len(validation_rows)} "
            f"after an embargo of {embargo_rows} rows"
        )
        return None, report

    scaler = Scaler.fit([row.values for row in train_rows])
    train_x = [scaler.transform(row.values) for row in train_rows]
    train_y = [float(labels[row.index]) for row in train_rows]

    if kind == "ridge":
        fit = _fit_ridge(train_x, train_y, alpha=alpha)
    elif kind == "logistic":
        fit = _fit_logistic(train_x, [1.0 if value > 0 else 0.0 for value in train_y], alpha=alpha, epochs=epochs, learning_rate=learning_rate, seed=seed)
    else:
        report["error"] = f"unknown_model_kind:{kind}"
        return None, report
    if fit is None:
        report["error"] = "normal_equations_singular: features are collinear on this training window"
        return None, report
    coefficients, intercept = fit

    train_end_index = train_rows[-1].index
    training_cutoff = timestamps[min(train_end_index + 1, len(timestamps) - 1)]
    model = TrainedModel(
        model_id=model_id,
        name=name,
        kind=kind,
        version=version,
        feature_names=list(FEATURE_NAMES),
        coefficients=coefficients,
        intercept=intercept,
        scaler=scaler,
        instrument_id=instrument_id,
        timeframe=timeframe,
        dataset_ids=list(dataset_ids),
        train_start=timestamps[train_rows[0].index],
        train_end=timestamps[train_end_index],
        training_cutoff=training_cutoff,
        embargo_rows=embargo_rows,
        seed=seed,
        hyperparameters={"alpha": alpha, "train_fraction": train_fraction, "epochs": epochs, "learning_rate": learning_rate},
        metrics={},
        created_at=created_at,
    )

    model.metrics = {
        "train": _score_rows(model, train_rows, labels),
        "validation": _score_rows(model, validation_rows, labels),
        "train_rows": len(train_rows),
        "validation_rows": len(validation_rows),
        "embargo_rows": embargo_rows,
        "interpretation": (
            "Validation numbers come from a chronologically later window with an embargo gap. They are "
            "still selection-contaminated if you refit repeatedly on the same window; the holdout split "
            "is the only untouched judge."
        ),
    }
    baseline = _baseline_comparison(train_rows, validation_rows, labels, model.metrics.get("validation", {}))
    report.update(
        {
            "trained": True,
            "artefact_hash": model.artefact_hash,
            "training_cutoff": training_cutoff,
            "coefficients": model.coefficient_table(),
            "metrics": model.metrics,
            "baseline_comparison": baseline,
            "training_window": {
                "start": model.train_start,
                "end": model.train_end,
                "cutoff": training_cutoff,
                "embargo_rows": embargo_rows,
                "train_rows": len(train_rows),
                "validation_rows": len(validation_rows),
            },
        }
    )
    return model, report


def _baseline_comparison(
    train_rows: Sequence[FeatureRow],
    validation_rows: Sequence[FeatureRow],
    labels: Sequence[float | None],
    validation_metrics: dict[str, Any],
) -> dict[str, Any]:
    """Compare the model against the cheapest honest alternative: the training-window drift sign.

    A model that cannot beat "always predict the direction that dominated the training window" has
    not learned anything worth running, so the comparison is reported next to the model's own score
    instead of being left to interpretation.
    """
    train_labels = [float(labels[row.index]) for row in train_rows if labels[row.index] is not None]
    validation_labels = [float(labels[row.index]) for row in validation_rows if labels[row.index] is not None]
    if not train_labels or not validation_labels:
        return {"available": False, "reason": "no labelled rows in one of the windows"}
    drift = sum(train_labels) / len(train_labels)
    sign = 1.0 if drift >= 0 else -1.0
    hits = sum(1 for value in validation_labels if (value > 0 and sign > 0) or (value < 0 and sign < 0))
    baseline_accuracy = hits / len(validation_labels)
    model_accuracy = validation_metrics.get("directional_accuracy")
    beats = isinstance(model_accuracy, (int, float)) and float(model_accuracy) > baseline_accuracy
    return {
        "available": True,
        "baseline": "training-window drift sign, held constant over the validation window",
        "baseline_direction": "up" if sign > 0 else "down",
        "baseline_directional_accuracy": baseline_accuracy,
        "model_directional_accuracy": model_accuracy,
        "beats_baseline": beats,
        "note": (
            "Directional accuracy on one validation window is a weak signal; a strategy built on this "
            "model still needs an independent evaluation before it means anything."
        ),
    }


def _fit_ridge(x: list[list[float]], y: list[float], *, alpha: float) -> tuple[list[float], float] | None:
    width = len(x[0])
    gram = [[0.0] * width for _ in range(width)]
    rhs = [0.0] * width
    mean_y = sum(y) / len(y)
    for row_index, row in enumerate(x):
        target = y[row_index] - mean_y
        for i in range(width):
            rhs[i] += row[i] * target
            for j in range(width):
                gram[i][j] += row[i] * row[j]
    for i in range(width):
        gram[i][i] += alpha
    solution = _solve(gram, rhs)
    if solution is None:
        return None
    return solution, mean_y


def _fit_logistic(
    x: list[list[float]],
    y: list[float],
    *,
    alpha: float,
    epochs: int,
    learning_rate: float,
    seed: int,
) -> tuple[list[float], float] | None:
    width = len(x[0])
    rng = random.Random(seed)
    coefficients = [rng.uniform(-0.01, 0.01) for _ in range(width)]
    intercept = 0.0
    count = len(x)
    for _ in range(max(1, epochs)):
        gradient = [0.0] * width
        gradient_intercept = 0.0
        for row_index, row in enumerate(x):
            total = intercept + sum(coefficients[i] * row[i] for i in range(width))
            prediction = 1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, total))))
            error = prediction - y[row_index]
            gradient_intercept += error
            for i in range(width):
                gradient[i] += error * row[i]
        intercept -= learning_rate * gradient_intercept / count
        for i in range(width):
            coefficients[i] -= learning_rate * ((gradient[i] / count) + alpha * coefficients[i] / count)
    return coefficients, intercept


def _score_rows(model: TrainedModel, rows: Sequence[FeatureRow], labels: Sequence[float | None]) -> dict[str, Any]:
    predictions: list[float] = []
    actuals: list[float] = []
    for row in rows:
        label = labels[row.index]
        if label is None:
            continue
        predictions.append(model.score(row.values))
        actuals.append(float(label))
    if not predictions:
        return {"rows": 0}
    hits = sum(
        1
        for index in range(len(predictions))
        if (predictions[index] > 0 and actuals[index] > 0) or (predictions[index] < 0 and actuals[index] < 0)
    )
    mean_actual = sum(actuals) / len(actuals)
    ss_total = sum((value - mean_actual) ** 2 for value in actuals)
    if model.kind == "ridge":
        residual = sum((actuals[i] - predictions[i]) ** 2 for i in range(len(actuals)))
        r_squared = None if ss_total <= 1e-18 else 1.0 - (residual / ss_total)
    else:
        r_squared = None
    correlation = _pearson(predictions, actuals)
    return {
        "rows": len(predictions),
        "directional_accuracy": hits / len(predictions),
        "information_coefficient": correlation,
        "r_squared": r_squared,
        "mean_prediction": sum(predictions) / len(predictions),
    }


def _pearson(left: Sequence[float], right: Sequence[float]) -> float | None:
    length = min(len(left), len(right))
    if length < 3:
        return None
    mean_left = sum(left[:length]) / length
    mean_right = sum(right[:length]) / length
    numerator = sum((left[i] - mean_left) * (right[i] - mean_right) for i in range(length))
    left_var = sum((left[i] - mean_left) ** 2 for i in range(length))
    right_var = sum((right[i] - mean_right) ** 2 for i in range(length))
    if left_var <= 1e-18 or right_var <= 1e-18:
        return None
    return numerator / math.sqrt(left_var * right_var)


def assert_training_cutoff(model: TrainedModel, evaluation_start: str) -> None:
    """Refuse an evaluation window that overlaps the training window."""
    if model.training_cutoff and evaluation_start <= model.training_cutoff:
        raise TrainingCutoffViolation(
            f"model {model.model_id} v{model.version} was trained up to {model.training_cutoff}; "
            f"evaluating from {evaluation_start} would score it on its own training data"
        )


def realised_volatility_summary(closes: Sequence[float], window: int = 20) -> dict[str, Any]:
    value = realized_volatility(list(closes), window)
    return {"window": window, "per_observation": value, "note": "not annualised; annualisation needs a calendar"}


__all__ = [
    "FEATURE_NAMES",
    "FeatureRow",
    "Scaler",
    "TrainedModel",
    "TrainingCutoffViolation",
    "assert_training_cutoff",
    "build_features",
    "forward_returns",
    "realised_volatility_summary",
    "train_model",
]

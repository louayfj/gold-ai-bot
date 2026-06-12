"""ML confidence gate: pure-Python inference over trees trained offline.

train_model.py (run locally, needs scikit-learn) replays the engine over
~2 years of history, trains a small forest on signal features vs TP/SL
outcomes, and exports it to goldeye/model.json. This module only *reads*
that file — no ML dependencies ship to the server. No model file means
no gating (fails open).
"""

import json
import os

from goldeye.models import Direction, Signal

MODEL_JSON = os.path.join(os.path.dirname(__file__), "model.json")

FEATURE_NAMES = [
    "vote_trend", "vote_momentum", "vote_macd", "vote_volatility",
    "vote_sr", "vote_session", "vote_candles",
    "score", "direction", "hour_utc", "weekday",
    "atr_regime", "rsi", "macd_norm", "trend_strength", "sl_dist",
]


def features(votes, sig: Signal, ctx) -> list[float]:
    """Feature vector for one signal. Order must match FEATURE_NAMES."""
    x = []
    for v in votes:
        x.append(float(int(v.buy) - int(v.sell)))  # both/neither -> 0
    x += [
        float(sig.score),
        1.0 if sig.direction == Direction.BUY else -1.0,
        float(ctx.now_utc.hour),
        float(ctx.now_utc.weekday()),
        ctx.atr15 / ctx.atr15_median if ctx.atr15_median else 1.0,
        ctx.rsi15,
        ctx.macd_hist / ctx.atr15 if ctx.atr15 else 0.0,
        (ctx.ema50_1h - ctx.ema200_1h) / ctx.atr15 if ctx.atr15 else 0.0,
        abs(sig.entry - sig.sl),
    ]
    return x


def _predict_tree(node: dict, x: list[float]) -> float:
    while "p" not in node:
        node = node["l"] if x[node["f"]] <= node["t"] else node["r"]
    return node["p"]


def predict(model: dict, x: list[float]) -> float:
    trees = model["trees"]
    return sum(_predict_tree(t, x) for t in trees) / len(trees)


def load_model(path: str = MODEL_JSON) -> dict | None:
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def confidence(model: dict, votes, sig: Signal, ctx) -> float:
    return predict(model, features(votes, sig, ctx))

"""Train the ML confidence gate on ~2 years of replayed engine signals.

Run locally (needs scikit-learn; NOT in requirements.txt — the server only
reads the exported goldeye/model.json via the pure-Python goldeye/ml.py).

Honesty rules baked in:
- time-ordered split: train on the oldest 75% of signals, test on the newest
  25% the model has never seen;
- the model ships only if gated trades beat the baseline win rate by
  >= MIN_EDGE points on the test set with >= MIN_APPROVED trades;
- exported trees are verified to reproduce sklearn's probabilities.
"""

import json
import os
import sys
import time
from bisect import bisect_right
from datetime import datetime, timedelta, timezone

import requests

from goldeye import config, engine, ml, tracker
from goldeye.factors import ALL_FACTORS, FactorContext
from goldeye.models import Candle, Status

CACHE = "history_cache.json"
DAYS = 730
WARMUP_15, WARMUP_1H = 250, 210
TEST_FRACTION = 0.25
MIN_EDGE = 5.0       # percentage points over baseline required to ship
MIN_APPROVED = 15    # gated trades needed in the test set to trust the edge
_TD_URL = "https://api.twelvedata.com/time_series"


# --- data ---------------------------------------------------------------

def _page(interval: str, end_date: str | None) -> list[Candle]:
    params = {
        "symbol": "XAU/USD", "interval": interval, "outputsize": 5000,
        "timezone": "UTC", "apikey": os.environ["TWELVEDATA_API_KEY"],
    }
    if end_date:
        params["end_date"] = end_date
    resp = requests.get(_TD_URL, params=params, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("status") != "ok":
        raise RuntimeError(payload.get("message", "bad response"))
    out = []
    for row in reversed(payload["values"]):
        ts = int(datetime.strptime(row["datetime"], "%Y-%m-%d %H:%M:%S")
                 .replace(tzinfo=timezone.utc).timestamp())
        out.append(Candle(ts, float(row["open"]), float(row["high"]),
                          float(row["low"]), float(row["close"])))
    return out


def fetch_history(interval: str) -> list[Candle]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=DAYS)
    candles: list[Candle] = []
    end: str | None = None
    while True:
        page = _page(interval, end)
        if not page:
            break
        candles = page + [c for c in candles if c.ts > page[-1].ts]
        oldest = datetime.fromtimestamp(page[0].ts, timezone.utc)
        print(f"  {interval}: {len(candles):6d} candles, back to {oldest:%Y-%m-%d}")
        if oldest <= cutoff or len(page) < 4900:
            break
        end = f"{oldest:%Y-%m-%d %H:%M:%S}"
        time.sleep(8)  # free tier: 8 requests/min
    return [c for c in candles if c.ts >= int(cutoff.timestamp())]


def load_history() -> tuple[list[Candle], list[Candle]]:
    if os.path.exists(CACHE):
        with open(CACHE) as f:
            raw = json.load(f)
        return ([Candle(*row) for row in raw["15min"]],
                [Candle(*row) for row in raw["1h"]])
    config.load_secrets()
    print("Fetching ~2 years of history (cached after first run)...")
    c15 = fetch_history("15min")
    time.sleep(8)
    c1h = fetch_history("1h")
    with open(CACHE, "w") as f:
        json.dump({"15min": [list(c.__dict__.values()) for c in c15],
                   "1h": [list(c.__dict__.values()) for c in c1h]}, f)
    return c15, c1h


# --- dataset: replay the production engine ------------------------------

def build_dataset(c15, c1h):
    ts_1h = [c.ts for c in c1h]
    rows = []   # (created_ts, features, label 1=TP 0=SL)
    open_until_idx = 0
    n_expired = 0
    for i in range(WARMUP_15, len(c15) - 1):
        if i < open_until_idx:
            continue
        close_time = c15[i].ts + 900
        n_1h = bisect_right(ts_1h, close_time - 3600)
        if n_1h < WARMUP_1H:
            continue
        window_15 = c15[max(0, i - 400): i + 1]
        window_1h = c1h[max(0, n_1h - 250): n_1h]
        try:
            ctx = FactorContext.build(
                window_15, window_1h,
                datetime.fromtimestamp(close_time, timezone.utc))
        except ValueError:
            continue
        sig = engine.evaluate(ctx)
        if sig is None:
            continue
        ttl_ts = sig.created_ts + config.SIGNAL_TTL_H * 3600
        future = [c for c in c15[i + 1:] if c.ts <= ttl_ts]
        closed = tracker.resolve(sig, future, ttl_ts + 1, 100.0)
        if closed is None:
            break
        if closed.closed_ts:
            while open_until_idx < len(c15) and c15[open_until_idx].ts <= closed.closed_ts:
                open_until_idx += 1
        if closed.status == Status.EXPIRED:
            n_expired += 1
            continue
        votes = [f(ctx) for f in ALL_FACTORS]
        rows.append((sig.created_ts, ml.features(votes, sig, ctx),
                     1 if closed.status == Status.TP else 0))
    print(f"dataset: {len(rows)} closed signals ({n_expired} expired dropped)")
    return rows


# --- training ------------------------------------------------------------

def export_tree(t, node=0):
    if t.children_left[node] == -1:
        counts = t.value[node][0]
        return {"p": round(float(counts[1] / counts.sum()), 6)}
    return {"f": int(t.feature[node]), "t": float(t.threshold[node]),
            "l": export_tree(t, t.children_left[node]),
            "r": export_tree(t, t.children_right[node])}


def _gate_stats(conf, y, threshold):
    """(win rate %, n approved) for signals at/above the confidence threshold."""
    appr = [yy for c, yy in zip(conf, y) if c >= threshold]
    if not appr:
        return 0.0, 0
    return 100 * sum(appr) / len(appr), len(appr)


def main(force: bool = False) -> int:
    from sklearn.ensemble import RandomForestClassifier

    c15, c1h = load_history()
    rows = build_dataset(c15, c1h)
    if len(rows) < 120:
        print("Not enough signals to train honestly; aborting.")
        return 1
    rows.sort(key=lambda r: r[0])
    # 60/20/20 time-ordered: tune on val, judge ONCE on the untouched test
    s1, s2 = int(len(rows) * 0.6), int(len(rows) * 0.8)
    x_tr = [r[1] for r in rows[:s1]]
    y_tr = [r[2] for r in rows[:s1]]
    x_va = [r[1] for r in rows[s1:s2]]
    y_va = [r[2] for r in rows[s1:s2]]
    x_te = [r[1] for r in rows[s2:]]
    y_te = [r[2] for r in rows[s2:]]

    base_va = 100 * sum(y_va) / len(y_va)
    best, best_edge = None, -1.0
    for depth in (3, 4, 5, 6):
        for leaf in (10, 20, 40):
            cand = RandomForestClassifier(
                n_estimators=120, max_depth=depth, min_samples_leaf=leaf,
                class_weight="balanced", random_state=7)
            cand.fit(x_tr, y_tr)
            conf_va = cand.predict_proba(x_va)[:, 1]
            wr, n = _gate_stats(conf_va, y_va, config.ML_MIN_CONFIDENCE)
            edge = wr - base_va
            if n >= MIN_APPROVED and edge > best_edge:
                best, best_edge = (depth, leaf), edge
            print(f"  depth={depth} leaf={leaf:2d}: val gate WR {wr:.1f}% "
                  f"({n} approved, baseline {base_va:.1f}%)")
    if best is None:
        print("no configuration approved enough validation signals; aborting")
        return 1
    depth, leaf = best
    print(f"\nchosen on validation: depth={depth} leaf={leaf} "
          f"(edge {best_edge:+.1f}pts) — retraining on train+val")
    clf = RandomForestClassifier(
        n_estimators=120, max_depth=depth, min_samples_leaf=leaf,
        class_weight="balanced", random_state=7)
    clf.fit(x_tr + x_va, y_tr + y_va)

    model = {"feature_names": ml.FEATURE_NAMES,
             "trained": f"{datetime.now(timezone.utc):%Y-%m-%d}",
             "train_n": len(x_tr), "test_n": len(x_te),
             "trees": [export_tree(est.tree_) for est in clf.estimators_]}

    # exported trees must reproduce sklearn exactly
    for x, p_sk in zip(x_te[:50], clf.predict_proba(x_te[:50])[:, 1]):
        assert abs(ml.predict(model, list(x)) - p_sk) < 1e-4, "export mismatch"

    base_wr = 100 * sum(y_te) / len(y_te)
    conf = [ml.predict(model, list(x)) for x in x_te]
    approved = [(c, y) for c, y in zip(conf, y_te) if c >= config.ML_MIN_CONFIDENCE]
    print(f"\n{'='*58}\nTEST SET (newest {len(y_te)} signals, never seen in training)")
    print(f"  baseline win rate:        {base_wr:.1f}%")
    if approved:
        appr_wr = 100 * sum(y for _, y in approved) / len(approved)
        print(f"  model-approved win rate:  {appr_wr:.1f}%  "
              f"({len(approved)}/{len(y_te)} signals pass the gate)")
        rej = [(c, y) for c, y in zip(conf, y_te) if c < config.ML_MIN_CONFIDENCE]
        if rej:
            rej_wr = 100 * sum(y for _, y in rej) / len(rej)
            print(f"  model-rejected win rate:  {rej_wr:.1f}%  ({len(rej)} signals)")
    else:
        appr_wr = 0.0
        print("  model approved nothing — gate unusable")

    importances = sorted(zip(ml.FEATURE_NAMES, clf.feature_importances_),
                         key=lambda p: -p[1])
    print("\ntop features:")
    for name, imp in importances[:6]:
        print(f"  {name:16s} {imp:.3f}")

    ship = appr_wr >= base_wr + MIN_EDGE and len(approved) >= MIN_APPROVED
    print(f"\nship bar: approved WR >= baseline+{MIN_EDGE:.0f}pts "
          f"and >= {MIN_APPROVED} approved -> {'PASS' if ship else 'FAIL'}")
    if ship or force:
        with open(ml.MODEL_JSON, "w") as f:
            json.dump(model, f)
        print(f"model written to {ml.MODEL_JSON}"
              + (" (FORCED despite failing bar)" if force and not ship else ""))
        return 0
    print("model NOT shipped — the gate would not have helped on unseen data.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(force="--force" in sys.argv))

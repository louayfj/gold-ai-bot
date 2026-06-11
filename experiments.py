"""One-off experiment harness: caches candles, replays engine variants.
Not part of production. Variants are applied by monkeypatching goldeye modules."""

import json
import os
import sys
from bisect import bisect_right
from datetime import datetime, timezone

from goldeye import config, data, engine, tracker
from goldeye.factors import FactorContext
from goldeye.models import Candle, Status, Tier

CACHE = "candles_cache.json"
WARMUP_15, WARMUP_1H = 250, 210


def load_candles():
    if os.path.exists(CACHE):
        with open(CACHE) as f:
            raw = json.load(f)
        return ([Candle(**c) for c in raw["c15"]], [Candle(**c) for c in raw["c1h"]])
    config.load_secrets()
    c15 = data.fetch_candles("15min", 5000)
    c1h = data.fetch_candles("1h", 5000)
    with open(CACHE, "w") as f:
        json.dump({"c15": [c.__dict__ for c in c15],
                   "c1h": [c.__dict__ for c in c1h]}, f)
    return c15, c1h


def replay(c15, c1h, evaluate):
    ts_1h = [c.ts for c in c1h]
    balance = config.START_BALANCE
    trades = []
    open_until_idx = 0
    for i in range(WARMUP_15, len(c15) - 1):
        if i < open_until_idx:
            continue
        close_time = c15[i].ts + 900
        n_1h = bisect_right(ts_1h, close_time - 3600)
        if n_1h < WARMUP_1H:
            continue
        try:
            ctx = FactorContext.build(
                c15[max(0, i - 400): i + 1], c1h[max(0, n_1h - 250): n_1h],
                datetime.fromtimestamp(close_time, timezone.utc))
        except ValueError:
            continue
        sig = evaluate(ctx)
        if sig is None:
            continue
        ttl_ts = sig.created_ts + config.SIGNAL_TTL_H * 3600
        future = [c for c in c15[i + 1:] if c.ts <= ttl_ts]
        closed = tracker.resolve(sig, future, ttl_ts + 1, balance)
        if closed is None:
            break
        balance = closed.balance_after
        trades.append(closed)
        if closed.closed_ts:
            while open_until_idx < len(c15) and c15[open_until_idx].ts <= closed.closed_ts:
                open_until_idx += 1
    return trades, balance


def summarize(name, trades, balance):
    print(f"\n--- {name} ---")
    for tier in (Tier.GOLD, Tier.SILVER):
        closed = [t for t in trades if t.tier == tier and t.status in (Status.TP, Status.SL)]
        if not closed:
            print(f"{tier.value}: 0 closed")
            continue
        wins = sum(1 for t in closed if t.status == Status.TP)
        gw = sum(t.pnl_usd for t in closed if t.pnl_usd > 0)
        gl = -sum(t.pnl_usd for t in closed if t.pnl_usd < 0)
        pnl = sum(t.pnl_usd for t in closed)
        print(f"{tier.value}: {len(closed)} closed | WR {100*wins/len(closed):.1f}% | "
              f"PF {gw/gl if gl else 99:.2f} | net ${pnl:+.2f}")
    eq, peak, dd = config.START_BALANCE, config.START_BALANCE, 0.0
    for t in trades:
        eq += t.pnl_usd or 0
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    days = (trades[-1].created_ts - trades[0].created_ts) / 86400 if trades else 0
    print(f"end ${balance:.2f} | maxDD ${dd:.2f} | {len(trades)} signals over {days:.0f} days")


def main():
    c15, c1h = load_candles()
    print(f"cached: {len(c15)} x15m, {len(c1h)} x1h")

    summarize("BASELINE (current engine)", *replay(c15, c1h, engine.evaluate))

    # Variant helpers -----------------------------------------------------
    from goldeye.factors import (factor_candles, factor_macd, factor_momentum,
                                 factor_session, factor_sr, factor_trend,
                                 factor_volatility)
    directional = (factor_trend, factor_momentum, factor_macd, factor_sr,
                   factor_candles)

    def gated_eval(gold_min, silver, max_risk_mult=None, require_trend=False):
        def ev(ctx):
            if not factor_session(ctx).buy or not factor_volatility(ctx).buy:
                return None
            votes = [f(ctx) for f in directional]
            buy = sum(1 for v in votes if v.buy)
            sell = sum(1 for v in votes if v.sell)
            if buy == sell:
                return None
            from goldeye.models import Direction
            direction = Direction.BUY if buy > sell else Direction.SELL
            score = max(buy, sell)
            if require_trend:
                tv = factor_trend(ctx)
                if not (tv.buy if direction == Direction.BUY else tv.sell):
                    return None
            if score >= gold_min:
                tier = Tier.GOLD
            elif score == silver:
                tier = Tier.SILVER
            else:
                return None
            is_buy = direction == Direction.BUY
            reasons = [v.label for v in votes if (v.buy if is_buy else v.sell)]
            missing = [v.label for v in votes if not (v.buy if is_buy else v.sell)]
            sig = engine.build_signal(direction, tier, score, reasons, missing, ctx)
            if max_risk_mult is not None:
                plan = config.RISK_GOLD if tier == Tier.GOLD else config.RISK_SILVER
                if sig.risk_usd > plan * max_risk_mult:
                    return None
            return sig
        return ev

    summarize("V1: gates, GOLD>=4/5, SILVER=3/5",
              *replay(c15, c1h, gated_eval(4, 3)))
    summarize("V2: V1 + trend required",
              *replay(c15, c1h, gated_eval(4, 3, require_trend=True)))
    summarize("V3: V2 + risk cap 1.6x plan",
              *replay(c15, c1h, gated_eval(4, 3, max_risk_mult=1.6, require_trend=True)))
    summarize("V4: gates, GOLD=5/5, SILVER=4/5, trend, cap 1.6x",
              *replay(c15, c1h, gated_eval(5, 4, max_risk_mult=1.6, require_trend=True)))

    def baseline_capped(max_risk_mult, silver=True, gold_min=None):
        def ev(ctx):
            sig = engine.evaluate(ctx)
            if sig is None:
                return None
            if gold_min and sig.tier == Tier.GOLD and sig.score < gold_min:
                return None
            if not silver and sig.tier == Tier.SILVER:
                return None
            plan = config.RISK_GOLD if sig.tier == Tier.GOLD else config.RISK_SILVER
            if sig.risk_usd > plan * max_risk_mult:
                return None
            return sig
        return ev

    summarize("V5: baseline GOLD only, cap 1.6x",
              *replay(c15, c1h, baseline_capped(1.6, silver=False)))
    summarize("V6: baseline both tiers, cap 1.6x",
              *replay(c15, c1h, baseline_capped(1.6)))
    summarize("V7: baseline GOLD only, cap 2.5x",
              *replay(c15, c1h, baseline_capped(2.5, silver=False)))
    summarize("V8: baseline GOLD only 6/7+, cap 2.5x",
              *replay(c15, c1h, baseline_capped(2.5, silver=False, gold_min=6)))

    def shipping(ctx):
        """Final config: baseline thresholds; silver kept as slot-occupying
        info signals (lot 0, no money); GOLD skipped if risk > 2x plan."""
        sig = engine.evaluate(ctx)
        if sig is None:
            return None
        if sig.tier == Tier.SILVER:
            sig.lot = 0.0
            sig.risk_usd = 0.0
            return sig
        if sig.risk_usd > config.RISK_GOLD * 2.0:
            return None
        return sig

    summarize("SHIPPING: silver info-only, GOLD cap $10",
              *replay(c15, c1h, shipping))


if __name__ == "__main__":
    sys.exit(main())

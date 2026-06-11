"""Scoring + signal construction."""

import math
import uuid

from goldeye.config import (
    GOLD_MIN_SCORE,
    LOT_STEP,
    MAX_RISK_MULT,
    MIN_LOT,
    OZ_PER_LOT,
    RISK_GOLD,
    RISK_SILVER,
    RR,
    SILVER_INFO_ONLY,
    SILVER_SCORE,
    SL_ATR_MULT,
)
from goldeye.factors import ALL_FACTORS, FactorContext
from goldeye.models import Direction, Signal, Tier

SWING_BUFFER_ATR = 0.1  # extra distance past a swing point when snapping the SL


def evaluate(ctx: FactorContext) -> Signal | None:
    votes = [f(ctx) for f in ALL_FACTORS]
    buy_score = sum(1 for v in votes if v.buy)
    sell_score = sum(1 for v in votes if v.sell)

    if buy_score == sell_score:
        return None
    direction = Direction.BUY if buy_score > sell_score else Direction.SELL
    score = max(buy_score, sell_score)
    if score >= GOLD_MIN_SCORE:
        tier = Tier.GOLD
    elif score == SILVER_SCORE:
        tier = Tier.SILVER
    else:
        return None

    is_buy = direction == Direction.BUY
    reasons = [v.label for v in votes if (v.buy if is_buy else v.sell)]
    missing = [v.label for v in votes if not (v.buy if is_buy else v.sell)]
    sig = build_signal(direction, tier, score, reasons, missing, ctx)

    if tier == Tier.SILVER and SILVER_INFO_ONLY:
        sig.lot = 0.0
        sig.risk_usd = 0.0
        sig.min_lot_flag = False
    elif tier == Tier.GOLD and sig.risk_usd > RISK_GOLD * MAX_RISK_MULT:
        return None  # stop too wide for the account even at the minimum lot
    return sig


def build_signal(
    direction: Direction,
    tier: Tier,
    score: int,
    reasons: list[str],
    missing: list[str],
    ctx: FactorContext,
) -> Signal:
    entry = ctx.c15[-1].close
    sl_dist = SL_ATR_MULT * ctx.atr15
    buffer = SWING_BUFFER_ATR * ctx.atr15

    if direction == Direction.BUY:
        sl = entry - sl_dist
        # snap past the nearest swing low sitting inside the ATR stop
        inside = [p for p in ctx.swing_lows if sl <= p < entry]
        if inside:
            sl = min(inside) - buffer
        sl_dist = entry - sl
        tp = entry + RR * sl_dist
    else:
        sl = entry + sl_dist
        inside = [p for p in ctx.swing_highs if entry < p <= sl]
        if inside:
            sl = max(inside) + buffer
        sl_dist = sl - entry
        tp = entry - RR * sl_dist

    risk = RISK_GOLD if tier == Tier.GOLD else RISK_SILVER
    exact_lot = risk / (OZ_PER_LOT * sl_dist)
    lot = math.floor(exact_lot / LOT_STEP) * LOT_STEP
    min_lot_flag = False
    if lot < MIN_LOT:
        lot = MIN_LOT
        min_lot_flag = True
    lot = round(lot, 2)
    risk_usd = round(OZ_PER_LOT * lot * sl_dist, 2)

    return Signal(
        id=uuid.uuid4().hex[:10],
        created_ts=ctx.c15[-1].ts,
        tier=tier,
        direction=direction,
        entry=round(entry, 2),
        sl=round(sl, 2),
        tp=round(tp, 2),
        lot=lot,
        risk_usd=risk_usd,
        score=score,
        reasons=reasons,
        missing=missing,
        min_lot_flag=min_lot_flag,
    )

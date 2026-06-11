"""Resolve open signals against 5m candles. Conservative same-candle rule:
if one candle spans both TP and SL we cannot know which hit first -> count SL."""

from goldeye.config import OZ_PER_LOT, SIGNAL_TTL_H
from goldeye.models import Candle, Direction, Signal, Status


def resolve(
    sig: Signal, candles_5m: list[Candle], now_ts: int, balance: float
) -> Signal | None:
    """Return the closed signal (TP/SL/EXPIRED) or None if still open."""
    is_buy = sig.direction == Direction.BUY
    for candle in candles_5m:
        if candle.ts <= sig.created_ts:
            continue
        if is_buy:
            hit_sl = candle.low <= sig.sl
            hit_tp = candle.high >= sig.tp
        else:
            hit_sl = candle.high >= sig.sl
            hit_tp = candle.low <= sig.tp
        if hit_sl:  # checked first: same-candle ambiguity counts as SL
            return _close(sig, Status.SL, candle.ts, balance)
        if hit_tp:
            return _close(sig, Status.TP, candle.ts, balance)
    if now_ts - sig.created_ts >= SIGNAL_TTL_H * 3600:
        return _close(sig, Status.EXPIRED, now_ts, balance)
    return None


def _close(sig: Signal, status: Status, ts: int, balance: float) -> Signal:
    if status == Status.TP:
        move = abs(sig.tp - sig.entry)
        pnl = OZ_PER_LOT * sig.lot * move
    elif status == Status.SL:
        move = abs(sig.entry - sig.sl)
        pnl = -OZ_PER_LOT * sig.lot * move
    else:
        pnl = 0.0
    sig.status = status
    sig.closed_ts = ts
    sig.pnl_usd = round(pnl, 2)
    sig.balance_after = round(balance + pnl, 2)
    return sig

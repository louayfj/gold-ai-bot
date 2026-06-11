"""The 7 confluence factors. Each returns a Vote; both flags False = abstain."""

import statistics
from collections import namedtuple
from dataclasses import dataclass
from datetime import datetime

from goldeye.config import SESSION_UTC
from goldeye.indicators import atr, ema, macd, rsi, swing_points
from goldeye.models import Candle

Vote = namedtuple("Vote", "buy sell label")

SR_ATR_FRACTION = 0.3      # "near" a level = within this fraction of ATR
ATR_BAND = (0.5, 2.5)      # tradable ATR regime vs recent median


@dataclass
class FactorContext:
    c15: list[Candle]
    c1h: list[Candle]
    now_utc: datetime
    ema50_1h: float
    ema200_1h: float
    close_1h: float
    rsi15: float
    macd_hist: float
    macd_hist_prev: float
    atr15: float
    atr15_median: float
    swing_highs: list[float]   # prices of recent 15m swing highs
    swing_lows: list[float]

    @classmethod
    def build(cls, c15: list[Candle], c1h: list[Candle], now_utc: datetime):
        closes_1h = [c.close for c in c1h]
        closes_15 = [c.close for c in c15]
        ema50 = ema(closes_1h, 50)[-1]
        ema200 = ema(closes_1h, 200)[-1]
        rsi_series = rsi(closes_15, 14)
        _, _, hist = macd(closes_15)
        atr_series = atr(c15, 14)
        atr_defined = [v for v in atr_series if v is not None][-100:]
        highs, lows = swing_points(c15, left=3, right=3)
        if ema50 is None or ema200 is None or rsi_series[-1] is None or \
                hist[-1] is None or hist[-2] is None or not atr_defined:
            raise ValueError("not enough candles to compute indicators")
        return cls(
            c15=c15,
            c1h=c1h,
            now_utc=now_utc,
            ema50_1h=ema50,
            ema200_1h=ema200,
            close_1h=closes_1h[-1],
            rsi15=rsi_series[-1],
            macd_hist=hist[-1],
            macd_hist_prev=hist[-2],
            atr15=atr_series[-1],
            atr15_median=statistics.median(atr_defined),
            swing_highs=[p for _, p in highs[-5:]],
            swing_lows=[p for _, p in lows[-5:]],
        )

    def trend_up(self) -> bool:
        return self.ema50_1h > self.ema200_1h and self.close_1h > self.ema50_1h

    def trend_down(self) -> bool:
        return self.ema50_1h < self.ema200_1h and self.close_1h < self.ema50_1h


def factor_trend(ctx: FactorContext) -> Vote:
    if ctx.trend_up():
        return Vote(True, False, "1h uptrend (EMA50>EMA200)")
    if ctx.trend_down():
        return Vote(False, True, "1h downtrend (EMA50<EMA200)")
    return Vote(False, False, "trend")


def factor_momentum(ctx: FactorContext) -> Vote:
    r = ctx.rsi15
    if ctx.trend_up() and 40 <= r <= 55:
        return Vote(True, False, f"RSI pullback {r:.0f}")
    if ctx.trend_down() and 45 <= r <= 60:
        return Vote(False, True, f"RSI rally {r:.0f}")
    return Vote(False, False, "momentum")


def factor_macd(ctx: FactorContext) -> Vote:
    if ctx.macd_hist > 0:
        return Vote(True, False, "MACD bullish")
    if ctx.macd_hist < 0:
        return Vote(False, True, "MACD bearish")
    return Vote(False, False, "macd")


def factor_volatility(ctx: FactorContext) -> Vote:
    lo, hi = ATR_BAND[0] * ctx.atr15_median, ATR_BAND[1] * ctx.atr15_median
    if lo <= ctx.atr15 <= hi:
        return Vote(True, True, "ATR normal")
    return Vote(False, False, "volatility regime")


def factor_sr(ctx: FactorContext) -> Vote:
    close = ctx.c15[-1].close
    near = SR_ATR_FRACTION * ctx.atr15
    near_support = any(abs(close - p) <= near for p in ctx.swing_lows)
    near_resistance = any(abs(close - p) <= near for p in ctx.swing_highs)
    if near_support and not near_resistance:
        return Vote(True, False, "at support")
    if near_resistance and not near_support:
        return Vote(False, True, "at resistance")
    return Vote(False, False, "support/resistance")


def factor_session(ctx: FactorContext) -> Vote:
    if SESSION_UTC[0] <= ctx.now_utc.hour < SESSION_UTC[1]:
        return Vote(True, True, "London/NY session")
    return Vote(False, False, "session")


def factor_candles(ctx: FactorContext) -> Vote:
    prev, curr = ctx.c15[-2], ctx.c15[-1]
    body = abs(curr.close - curr.open)
    rng = curr.high - curr.low
    prev_body_hi = max(prev.open, prev.close)
    prev_body_lo = min(prev.open, prev.close)

    bullish_engulfing = (
        prev.close < prev.open
        and curr.close > curr.open
        and curr.open <= prev_body_lo
        and curr.close >= prev_body_hi
    )
    bearish_engulfing = (
        prev.close > prev.open
        and curr.close < curr.open
        and curr.open >= prev_body_hi
        and curr.close <= prev_body_lo
    )
    lower_wick = min(curr.open, curr.close) - curr.low
    upper_wick = curr.high - max(curr.open, curr.close)
    bullish_pin = (
        rng > 0 and body > 0 and lower_wick >= 2 * body
        and min(curr.open, curr.close) >= curr.low + rng * 2 / 3
    )
    bearish_pin = (
        rng > 0 and body > 0 and upper_wick >= 2 * body
        and max(curr.open, curr.close) <= curr.high - rng * 2 / 3
    )
    if bullish_engulfing:
        return Vote(True, False, "bullish engulfing")
    if bearish_engulfing:
        return Vote(False, True, "bearish engulfing")
    if bullish_pin:
        return Vote(True, False, "bullish pin bar")
    if bearish_pin:
        return Vote(False, True, "bearish pin bar")
    return Vote(False, False, "candle pattern")


ALL_FACTORS = (
    factor_trend,
    factor_momentum,
    factor_macd,
    factor_volatility,
    factor_sr,
    factor_session,
    factor_candles,
)

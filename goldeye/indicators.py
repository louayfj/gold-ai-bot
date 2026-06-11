"""Indicator math. All series functions take values oldest->newest and return a
list of the same length, padded with None where the indicator is undefined."""

from goldeye.models import Candle


def ema(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) < period:
        return out
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    k = 2 / (period + 1)
    prev = seed
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def rsi(closes: list[float], period: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(closes)
    if len(closes) <= period:
        return out
    gains, losses = 0.0, 0.0
    for i in range(1, period + 1):
        change = closes[i] - closes[i - 1]
        if change >= 0:
            gains += change
        else:
            losses -= change
    avg_gain = gains / period
    avg_loss = losses / period

    def _rsi(g: float, l: float) -> float:
        if l == 0:
            return 100.0
        return 100.0 - 100.0 / (1.0 + g / l)

    out[period] = _rsi(avg_gain, avg_loss)
    for i in range(period + 1, len(closes)):
        change = closes[i] - closes[i - 1]
        gain = max(change, 0.0)
        loss = max(-change, 0.0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        out[i] = _rsi(avg_gain, avg_loss)
    return out


def macd(
    closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)
    macd_line: list[float | None] = [
        (f - s) if f is not None and s is not None else None
        for f, s in zip(ema_fast, ema_slow)
    ]
    defined = [v for v in macd_line if v is not None]
    offset = len(macd_line) - len(defined)
    sig_defined = ema(defined, signal)
    signal_line: list[float | None] = [None] * offset + sig_defined
    hist: list[float | None] = [
        (m - s) if m is not None and s is not None else None
        for m, s in zip(macd_line, signal_line)
    ]
    return macd_line, signal_line, hist


def atr(candles: list[Candle], period: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(candles)
    if len(candles) <= period:
        return out
    trs = [candles[0].high - candles[0].low]
    for i in range(1, len(candles)):
        c, prev_close = candles[i], candles[i - 1].close
        trs.append(
            max(c.high - c.low, abs(c.high - prev_close), abs(c.low - prev_close))
        )
    prev = sum(trs[1 : period + 1]) / period
    out[period] = prev
    for i in range(period + 1, len(candles)):
        prev = (prev * (period - 1) + trs[i]) / period
        out[i] = prev
    return out


def swing_points(
    candles: list[Candle], left: int = 3, right: int = 3
) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    """Local extremes: a swing high's high exceeds the highs of `left` candles
    before and `right` candles after (mirrored for swing lows)."""
    highs: list[tuple[int, float]] = []
    lows: list[tuple[int, float]] = []
    for i in range(left, len(candles) - right):
        window = candles[i - left : i + right + 1]
        if candles[i].high == max(c.high for c in window) and all(
            candles[i].high > c.high for c in window if c is not candles[i]
        ):
            highs.append((i, candles[i].high))
        if candles[i].low == min(c.low for c in window) and all(
            candles[i].low < c.low for c in window if c is not candles[i]
        ):
            lows.append((i, candles[i].low))
    return highs, lows

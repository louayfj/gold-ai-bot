import pytest

from goldeye.indicators import atr, ema, macd, rsi, swing_points
from goldeye.models import Candle


def test_ema_converges_to_constant():
    assert ema([5.0] * 50, 10)[-1] == pytest.approx(5.0)


def test_ema_leading_values_are_none():
    series = ema([float(i) for i in range(20)], 10)
    assert series[8] is None
    assert series[9] is not None
    assert len(series) == 20


def test_rsi_all_gains_is_100():
    closes = [float(i) for i in range(1, 40)]
    assert rsi(closes, 14)[-1] == pytest.approx(100.0)


def test_rsi_all_losses_is_0():
    closes = [float(i) for i in range(40, 1, -1)]
    assert rsi(closes, 14)[-1] == pytest.approx(0.0)


def test_rsi_alternating_is_near_50():
    closes = [100 + (1 if i % 2 else -1) for i in range(60)]
    assert 40 < rsi(closes, 14)[-1] < 60


def test_atr_constant_range():
    candles = [Candle(i, 10, 12, 9, 11) for i in range(40)]
    assert atr(candles, 14)[-1] == pytest.approx(3.0, abs=0.1)


def test_macd_positive_histogram_on_accelerating_series():
    closes = [float(i**1.5) for i in range(1, 80)]
    macd_line, signal_line, hist = macd(closes)
    assert hist[-1] > 0
    assert len(hist) == len(closes)


def test_swing_points_finds_local_extremes():
    highs = [1, 2, 3, 9, 3, 2, 1, 2, 3, 2, 1]
    lows = [h - 1 for h in highs]
    candles = [
        Candle(i, h - 0.5, h, lo, h - 0.5) for i, (h, lo) in enumerate(zip(highs, lows))
    ]
    sh, sl_ = swing_points(candles, left=2, right=2)
    assert 3 in [i for i, _ in sh]          # the 9-high is a swing high
    assert (3, 9) in sh
    assert any(price == 0 for _, price in sl_)  # the 0-low around index 6

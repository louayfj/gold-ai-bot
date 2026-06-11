import pytest

from goldeye.models import Candle, Direction, Status
from goldeye.tracker import resolve
from tests.test_storage import make_signal

ENTRY_TS = 1765400000
H = 300  # 5 minutes


def c(offset_min: int, low: float, high: float) -> Candle:
    mid = (low + high) / 2
    return Candle(ENTRY_TS + offset_min * 60, mid, high, low, mid)


# BUY: entry 3341.5, sl 3335.2, tp 3351.0
def test_buy_tp_hit():
    candles = [c(5, 3340, 3344), c(10, 3343, 3352)]  # second touches TP
    sig = resolve(make_signal(), candles, now_ts=ENTRY_TS + 900, balance=100.0)
    assert sig.status == Status.TP
    assert sig.pnl_usd == pytest.approx(100 * 0.01 * (3351.0 - 3341.5))  # +9.5
    assert sig.balance_after == pytest.approx(109.5)
    assert sig.closed_ts == candles[1].ts


def test_buy_sl_hit():
    candles = [c(5, 3340, 3344), c(10, 3334, 3342)]
    sig = resolve(make_signal(), candles, now_ts=ENTRY_TS + 900, balance=100.0)
    assert sig.status == Status.SL
    assert sig.pnl_usd == pytest.approx(-100 * 0.01 * (3341.5 - 3335.2))  # -6.3
    assert sig.balance_after == pytest.approx(93.7)


def test_sell_tp_hit():
    sell = make_signal(direction=Direction.SELL, entry=3341.5, sl=3347.8, tp=3332.0)
    candles = [c(5, 3338, 3343), c(10, 3331, 3339)]
    sig = resolve(sell, candles, now_ts=ENTRY_TS + 900, balance=100.0)
    assert sig.status == Status.TP
    assert sig.pnl_usd == pytest.approx(100 * 0.01 * (3341.5 - 3332.0))


def test_same_candle_counts_sl():
    candles = [c(5, 3334.0, 3352.0)]  # spans both SL and TP
    sig = resolve(make_signal(), candles, now_ts=ENTRY_TS + 900, balance=100.0)
    assert sig.status == Status.SL


def test_still_open_returns_none():
    candles = [c(5, 3340, 3344)]
    assert resolve(make_signal(), candles, now_ts=ENTRY_TS + 900, balance=100.0) is None


def test_candles_before_entry_are_ignored():
    candles = [c(-5, 3334.0, 3352.0), c(5, 3340, 3344)]  # spike happened pre-entry
    assert resolve(make_signal(), candles, now_ts=ENTRY_TS + 900, balance=100.0) is None


def test_expiry_after_24h():
    candles = [c(5, 3340, 3344)]
    sig = resolve(make_signal(), candles,
                  now_ts=ENTRY_TS + 25 * 3600, balance=100.0)
    assert sig.status == Status.EXPIRED
    assert sig.pnl_usd == 0.0
    assert sig.balance_after == 100.0

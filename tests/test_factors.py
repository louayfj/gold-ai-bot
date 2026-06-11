from datetime import datetime, timezone

from goldeye.factors import (
    FactorContext,
    factor_candles,
    factor_macd,
    factor_momentum,
    factor_session,
    factor_sr,
    factor_trend,
    factor_volatility,
)
from goldeye.models import Candle


def make_ctx(**overrides) -> FactorContext:
    defaults = dict(
        c15=[Candle(900 * i, 3340.0, 3342.0, 3338.0, 3341.0) for i in range(10)],
        c1h=[Candle(3600 * i, 3340.0, 3342.0, 3338.0, 3341.0) for i in range(10)],
        now_utc=datetime(2026, 6, 11, 13, 0, tzinfo=timezone.utc),  # London/NY overlap
        ema50_1h=3340.0,
        ema200_1h=3320.0,   # default: uptrend
        close_1h=3345.0,
        rsi15=50.0,
        macd_hist=0.5,
        macd_hist_prev=0.3,
        atr15=4.0,
        atr15_median=4.0,
        swing_highs=[3380.0],
        swing_lows=[3300.0],
    )
    defaults.update(overrides)
    return FactorContext(**defaults)


# --- trend -------------------------------------------------------------
def test_trend_votes_buy_when_ema50_above_ema200_and_price_above():
    vote = factor_trend(make_ctx())
    assert vote.buy and not vote.sell


def test_trend_votes_sell_in_downtrend():
    vote = factor_trend(make_ctx(ema50_1h=3320.0, ema200_1h=3340.0, close_1h=3310.0))
    assert vote.sell and not vote.buy


def test_trend_abstains_when_mixed():
    vote = factor_trend(make_ctx(close_1h=3330.0))  # uptrend EMAs, price below ema50
    assert not vote.buy and not vote.sell


# --- momentum ----------------------------------------------------------
def test_momentum_votes_buy_on_pullback_in_uptrend():
    vote = factor_momentum(make_ctx(rsi15=47.0))
    assert vote.buy and not vote.sell


def test_momentum_vetoes_buy_when_rsi_overbought():
    vote = factor_momentum(make_ctx(rsi15=75.0))
    assert not vote.buy


def test_momentum_votes_sell_on_rally_in_downtrend():
    vote = factor_momentum(
        make_ctx(ema50_1h=3320.0, ema200_1h=3340.0, close_1h=3310.0, rsi15=55.0)
    )
    assert vote.sell and not vote.buy


# --- macd --------------------------------------------------------------
def test_macd_votes_buy_on_positive_histogram():
    assert factor_macd(make_ctx(macd_hist=0.8)).buy


def test_macd_votes_sell_on_negative_histogram():
    vote = factor_macd(make_ctx(macd_hist=-0.8))
    assert vote.sell and not vote.buy


# --- volatility --------------------------------------------------------
def test_volatility_votes_both_in_normal_regime():
    vote = factor_volatility(make_ctx(atr15=4.0, atr15_median=4.0))
    assert vote.buy and vote.sell


def test_volatility_abstains_when_too_quiet():
    vote = factor_volatility(make_ctx(atr15=1.0, atr15_median=4.0))
    assert not vote.buy and not vote.sell


def test_volatility_abstains_when_hyper_volatile():
    vote = factor_volatility(make_ctx(atr15=12.0, atr15_median=4.0))
    assert not vote.buy and not vote.sell


# --- support/resistance ------------------------------------------------
def test_sr_votes_buy_near_support():
    # close 3341, swing low 3340 -> distance 1.0 <= 0.3*ATR(4)=1.2
    vote = factor_sr(make_ctx(swing_lows=[3340.0]))
    assert vote.buy and not vote.sell


def test_sr_votes_sell_near_resistance():
    vote = factor_sr(make_ctx(swing_highs=[3342.0]))
    assert vote.sell and not vote.buy


def test_sr_abstains_far_from_levels():
    vote = factor_sr(make_ctx())
    assert not vote.buy and not vote.sell


def test_sr_abstains_when_squeezed_between_levels():
    vote = factor_sr(make_ctx(swing_lows=[3340.0], swing_highs=[3342.0]))
    assert not vote.buy and not vote.sell


# --- session -----------------------------------------------------------
def test_session_votes_during_london_ny():
    vote = factor_session(make_ctx())
    assert vote.buy and vote.sell


def test_session_abstains_in_asia_hours():
    vote = factor_session(
        make_ctx(now_utc=datetime(2026, 6, 11, 3, 0, tzinfo=timezone.utc))
    )
    assert not vote.buy and not vote.sell


# --- candle patterns ---------------------------------------------------
def _with_last_two(prev: Candle, curr: Candle) -> FactorContext:
    base = [Candle(900 * i, 3340.0, 3341.0, 3339.0, 3340.0) for i in range(8)]
    return make_ctx(c15=base + [prev, curr])


def test_candles_detect_bullish_engulfing():
    prev = Candle(1, open=3342.0, high=3343.0, low=3339.5, close=3340.0)  # red
    curr = Candle(2, open=3339.5, high=3344.5, low=3339.0, close=3343.0)  # engulfs
    vote = factor_candles(_with_last_two(prev, curr))
    assert vote.buy and not vote.sell


def test_candles_detect_bullish_pin_bar():
    # long lower wick, small body near the top
    curr = Candle(2, open=3342.6, high=3343.0, low=3336.0, close=3342.9)
    vote = factor_candles(_with_last_two(Candle(1, 3342, 3343, 3341, 3342), curr))
    assert vote.buy


def test_candles_abstain_on_plain_candle():
    curr = Candle(2, open=3340.0, high=3342.0, low=3339.0, close=3341.0)
    vote = factor_candles(_with_last_two(Candle(1, 3340, 3342, 3339, 3341), curr))
    assert not vote.buy and not vote.sell

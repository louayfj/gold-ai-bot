from goldeye.models import Status, Tier
from goldeye.telegram import format_outcome, format_signal
from tests.test_storage import make_signal


def test_format_gold_signal():
    text = format_signal(make_signal())
    assert "🥇 GOLD SIGNAL — BUY XAU/USD" in text
    assert "(score 6/7)" in text
    assert "Entry: 3,341.50" in text
    assert "SL:    3,335.20" in text and "−$6.30/oz" in text
    assert "TP:    3,351.00" in text and "+$9.50/oz" in text and "R:R 1:1.5" in text
    assert "Lot:   0.01" in text and "risk ≈ $5.00" in text
    assert "Why: 1h uptrend · RSI pullback 47" in text
    assert "Missing: candle pattern" in text


def test_format_silver_signal_is_info_only():
    sig = make_signal(tier=Tier.SILVER, score=4, lot=0.0, risk_usd=0.0)
    text = format_signal(sig)
    assert "🥈 SILVER SIGNAL" in text
    assert "info only" in text


def test_format_gold_min_lot_warning():
    sig = make_signal(min_lot_flag=True, risk_usd=6.3)
    text = format_signal(sig)
    assert "⚠️" in text and "minimum lot" in text


def test_format_outcome_info_signal_has_no_money():
    sig = make_signal(tier=Tier.SILVER, lot=0.0, risk_usd=0.0,
                      status=Status.TP, pnl_usd=0.0, balance_after=100.0)
    text = format_outcome(sig)
    assert "Info signal" in text and "no $ attached" in text
    assert "Balance" not in text


def test_format_outcome_tp_and_sl():
    tp = make_signal(status=Status.TP, pnl_usd=9.5, balance_after=109.5)
    assert "🎯 TP hit: +$9.50" in format_outcome(tp)
    assert "Balance: $109.50" in format_outcome(tp)
    sl = make_signal(status=Status.SL, pnl_usd=-6.3, balance_after=93.7)
    assert "🛑 SL hit: −$6.30" in format_outcome(sl)
    expired = make_signal(status=Status.EXPIRED, pnl_usd=0.0, balance_after=100.0)
    assert "⌛" in format_outcome(expired)

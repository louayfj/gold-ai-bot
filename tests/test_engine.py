import pytest

from goldeye import engine
from goldeye.factors import Vote
from goldeye.models import Direction, Tier
from tests.test_factors import make_ctx


def fake_factors(buy_votes: int, sell_votes: int, abstains: int = 0):
    factors = []
    for i in range(buy_votes):
        factors.append(lambda ctx, i=i: Vote(True, False, f"buy-{i}"))
    for i in range(sell_votes):
        factors.append(lambda ctx, i=i: Vote(False, True, f"sell-{i}"))
    for i in range(abstains):
        factors.append(lambda ctx, i=i: Vote(False, False, f"abstain-{i}"))
    return factors


def test_no_signal_below_silver_threshold(monkeypatch):
    monkeypatch.setattr(engine, "ALL_FACTORS", fake_factors(3, 0, 4))
    assert engine.evaluate(make_ctx()) is None


def test_silver_at_4_gold_at_5(monkeypatch):
    monkeypatch.setattr(engine, "ALL_FACTORS", fake_factors(4, 0, 3))
    sig = engine.evaluate(make_ctx())
    assert sig.tier == Tier.SILVER and sig.score == 4

    monkeypatch.setattr(engine, "ALL_FACTORS", fake_factors(5, 0, 2))
    sig = engine.evaluate(make_ctx())
    assert sig.tier == Tier.GOLD and sig.score == 5
    assert sig.direction == Direction.BUY
    assert len(sig.reasons) == 5 and len(sig.missing) == 2


def test_sell_direction_wins_with_more_votes(monkeypatch):
    monkeypatch.setattr(engine, "ALL_FACTORS", fake_factors(1, 5, 1))
    sig = engine.evaluate(make_ctx())
    assert sig.direction == Direction.SELL


def test_sl_is_atr_based_and_tp_is_rr15(monkeypatch):
    monkeypatch.setattr(engine, "ALL_FACTORS", fake_factors(5, 0, 2))
    ctx = make_ctx(atr15=4.0, swing_lows=[3300.0])  # swing far away: pure ATR stop
    sig = engine.evaluate(ctx)
    entry = ctx.c15[-1].close
    assert sig.entry == entry
    assert sig.sl == pytest.approx(entry - 6.0)        # 1.5 * ATR
    assert sig.tp == pytest.approx(entry + 9.0)        # 1.5 * sl_dist
    assert (sig.tp - entry) == pytest.approx(1.5 * (entry - sig.sl))


def test_sl_snaps_beyond_swing(monkeypatch):
    monkeypatch.setattr(engine, "ALL_FACTORS", fake_factors(5, 0, 2))
    # swing low 3338 sits inside the ATR stop (entry 3341 - 6 = 3335)
    ctx = make_ctx(atr15=4.0, swing_lows=[3338.0])
    sig = engine.evaluate(ctx)
    assert sig.sl < 3338.0                              # beyond the swing
    assert sig.sl > 3341.0 - 6.0 - 1.0                  # but not absurdly far


def test_lot_sizing_rounds_down_to_step(monkeypatch):
    monkeypatch.setattr(engine, "ALL_FACTORS", fake_factors(5, 0, 2))
    # sl_dist = 1.5 * 2.0 = $3.00 -> exact lot = 5/(100*3) = 0.0166 -> 0.01
    ctx = make_ctx(atr15=2.0, swing_lows=[3300.0])
    sig = engine.evaluate(ctx)
    assert sig.lot == 0.01
    assert sig.min_lot_flag is False
    assert sig.risk_usd == pytest.approx(3.0)           # 100 * 0.01 * 3.0


def test_min_lot_flag_when_risk_exceeds_plan(monkeypatch):
    monkeypatch.setattr(engine, "ALL_FACTORS", fake_factors(5, 0, 2))
    # sl_dist = 1.5 * 4.2 = $6.30 -> exact lot 0.0079 -> below MIN_LOT
    ctx = make_ctx(atr15=4.2, swing_lows=[3300.0])
    sig = engine.evaluate(ctx)
    assert sig.lot == 0.01
    assert sig.min_lot_flag is True
    assert sig.risk_usd == pytest.approx(6.3)


def test_silver_is_info_only(monkeypatch):
    monkeypatch.setattr(engine, "ALL_FACTORS", fake_factors(4, 0, 3))
    ctx = make_ctx(atr15=1.0, swing_lows=[3300.0])
    sig = engine.evaluate(ctx)
    assert sig.tier == Tier.SILVER
    assert sig.lot == 0.0
    assert sig.risk_usd == 0.0


def test_gold_skipped_when_risk_exceeds_cap(monkeypatch):
    monkeypatch.setattr(engine, "ALL_FACTORS", fake_factors(5, 0, 2))
    # sl_dist = 1.5 * 7.0 = $10.50 -> min-lot risk $10.50 > 2x plan ($10) -> skip
    ctx = make_ctx(atr15=7.0, swing_lows=[3300.0])
    assert engine.evaluate(ctx) is None


def test_gold_min_lot_allowed_within_cap(monkeypatch):
    monkeypatch.setattr(engine, "ALL_FACTORS", fake_factors(5, 0, 2))
    # sl_dist = $6.30 -> min-lot risk $6.30, within the $10 cap -> flagged but sent
    ctx = make_ctx(atr15=4.2, swing_lows=[3300.0])
    sig = engine.evaluate(ctx)
    assert sig is not None and sig.min_lot_flag is True

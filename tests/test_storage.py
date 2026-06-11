from goldeye import storage
from goldeye.models import Direction, Signal, Status, Tier


def make_signal(**overrides) -> Signal:
    sig = Signal(
        id="abc123", created_ts=1765400000, tier=Tier.GOLD, direction=Direction.BUY,
        entry=3341.5, sl=3335.2, tp=3351.0, lot=0.01, risk_usd=5.0, score=6,
        reasons=["1h uptrend", "RSI pullback 47"], missing=["candle pattern"],
    )
    for k, v in overrides.items():
        setattr(sig, k, v)
    return sig


def test_state_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "STATE_JSON", str(tmp_path / "state.json"))
    state = storage.load_state()
    assert state["balance"] == 100.0          # fresh state seeds the $100 ledger
    assert state["open_signal"] is None

    state["open_signal"] = storage.signal_to_dict(make_signal())
    state["balance"] = 95.0
    state["errors"] = [f"e{i}" for i in range(30)]
    storage.save_state(state)

    loaded = storage.load_state()
    assert loaded["balance"] == 95.0
    assert loaded["open_signal"]["id"] == "abc123"
    assert len(loaded["errors"]) == 20        # capped


def test_signal_dict_round_trip():
    sig = make_signal(status=Status.TP, pnl_usd=7.5, balance_after=107.5)
    again = storage.signal_from_dict(storage.signal_to_dict(sig))
    assert again == sig


def test_append_then_update_signal(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "SIGNALS_CSV", str(tmp_path / "signals.csv"))
    sig = make_signal()
    storage.append_signal(sig)
    storage.append_signal(make_signal(id="zzz999"))

    sig.status = Status.TP
    sig.pnl_usd = 7.5
    sig.balance_after = 107.5
    sig.closed_ts = 1765410000
    storage.update_signal(sig)

    rows = storage.read_signals()
    assert len(rows) == 2
    assert rows[0]["status"] == "tp"
    assert float(rows[0]["pnl_usd"]) == 7.5
    assert rows[1]["status"] == "open"

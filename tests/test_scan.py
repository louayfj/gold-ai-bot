from goldeye import storage
from goldeye.models import Candle, Status
from tests.test_storage import make_signal

import scan


class StubCtx:
    @classmethod
    def build(cls, c15, c1h, now_utc):
        return cls()


def setup_scan(tmp_path, monkeypatch, *, open_signal=None, new_signal=None,
               news=None):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "c")
    monkeypatch.setenv("TWELVEDATA_API_KEY", "k")
    monkeypatch.setattr(storage, "STATE_JSON", str(tmp_path / "state.json"))
    monkeypatch.setattr(storage, "SIGNALS_CSV", str(tmp_path / "signals.csv"))

    sent = []
    monkeypatch.setattr(scan.telegram, "send", lambda text: sent.append(text) or True)
    monkeypatch.setattr(scan.data, "fetch_candles",
                        lambda interval, n: [Candle(2_000_000_000, 3340, 3360, 3330, 3341)])
    monkeypatch.setattr(scan, "FactorContext", StubCtx)
    monkeypatch.setattr(scan.engine, "evaluate", lambda ctx: new_signal)
    monkeypatch.setattr(scan.news, "fetch_calendar", lambda: ([], None))
    monkeypatch.setattr(scan.news, "news_block", lambda now, events: news)
    monkeypatch.setattr(scan, "ALL_FACTORS", [lambda ctx: scan.Vote(False, False, "stub")])

    if open_signal:
        state = storage.load_state()
        state["open_signal"] = storage.signal_to_dict(open_signal)
        storage.save_state(state)
        storage.append_signal(open_signal)
    return sent


def test_open_signal_resolves_and_notifies(tmp_path, monkeypatch):
    # candle low 3330 <= sl 3335.2 -> SL hit
    sent = setup_scan(tmp_path, monkeypatch, open_signal=make_signal())
    scan.run()
    state = storage.load_state()
    assert state["open_signal"] is None
    assert state["balance"] == 93.7
    assert storage.read_signals()[0]["status"] == "sl"
    assert any("SL hit" in m for m in sent)


def test_new_signal_sent_and_recorded(tmp_path, monkeypatch):
    sig = make_signal(id="new001")
    sent = setup_scan(tmp_path, monkeypatch, new_signal=sig)
    scan.run()
    state = storage.load_state()
    assert state["open_signal"]["id"] == "new001"
    assert storage.read_signals()[0]["id"] == "new001"
    assert any("GOLD SIGNAL" in m for m in sent)


def test_news_block_suppresses_signal(tmp_path, monkeypatch):
    sent = setup_scan(tmp_path, monkeypatch, new_signal=make_signal(), news="FOMC")
    scan.run()
    state = storage.load_state()
    assert state["open_signal"] is None
    assert storage.read_signals() == []
    assert sent == []
    assert "FOMC" in state["last_no_signal"]


def test_no_setup_records_reason(tmp_path, monkeypatch):
    votes_called = []
    setup_scan(tmp_path, monkeypatch, new_signal=None)
    monkeypatch.setattr(scan, "ALL_FACTORS",
                        [lambda ctx: scan.Vote(True, False, "1h uptrend"),
                         lambda ctx: scan.Vote(False, False, "momentum")])
    scan.run()
    state = storage.load_state()
    assert "1h uptrend" in state["last_no_signal"]
    assert state["last_scan_ts"] > 0

from goldeye import storage
from goldeye.models import Candle, Status
from tests.test_storage import make_signal

import scan


class StubCtx:
    @classmethod
    def build(cls, c15, c1h, now_utc):
        return cls()


def setup_scan(tmp_path, monkeypatch, *, open_signal=None, new_signal=None,
               news=None, senti=None, ml_model=None, ml_conf=0.0):
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
    monkeypatch.setattr(scan.sentiment, "fetch_headlines", lambda: ([], None))
    monkeypatch.setattr(scan.sentiment, "analyze",
                        lambda headlines: senti or scan.sentiment.Sentiment(0, "neutral", 0))
    monkeypatch.setattr(scan.ml, "load_model", lambda path=None: ml_model)
    monkeypatch.setattr(scan.ml, "confidence",
                        lambda model, votes, sig, ctx: ml_conf)
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


def test_sentiment_block_suppresses_signal(tmp_path, monkeypatch):
    # BUY signal vs strongly bearish headlines -> skipped, logged, not sent
    bearish = scan.sentiment.Sentiment(-4, "bearish", 6)
    sent = setup_scan(tmp_path, monkeypatch, new_signal=make_signal(), senti=bearish)
    scan.run()
    state = storage.load_state()
    assert state["open_signal"] is None
    assert storage.read_signals() == []
    assert sent == []
    assert "bearish" in state["last_no_signal"]


def test_sentiment_agreement_noted_in_reasons(tmp_path, monkeypatch):
    bullish = scan.sentiment.Sentiment(4, "bullish", 7)
    sent = setup_scan(tmp_path, monkeypatch, new_signal=make_signal(id="sent01"),
                      senti=bullish)
    scan.run()
    assert storage.load_state()["open_signal"]["id"] == "sent01"
    assert any("news sentiment bullish" in m for m in sent)


def test_ml_low_confidence_suppresses_signal(tmp_path, monkeypatch):
    sent = setup_scan(tmp_path, monkeypatch, new_signal=make_signal(),
                      ml_model={"trees": []}, ml_conf=0.30)
    scan.run()
    state = storage.load_state()
    assert state["open_signal"] is None
    assert sent == []
    assert "ML confidence" in state["last_no_signal"]


def test_ml_high_confidence_passes_and_noted(tmp_path, monkeypatch):
    sent = setup_scan(tmp_path, monkeypatch, new_signal=make_signal(id="ml001"),
                      ml_model={"trees": []}, ml_conf=0.72)
    scan.run()
    assert storage.load_state()["open_signal"]["id"] == "ml001"
    assert any("ML confidence 72%" in m for m in sent)


def test_no_model_means_no_gating(tmp_path, monkeypatch):
    sent = setup_scan(tmp_path, monkeypatch, new_signal=make_signal(id="ml002"),
                      ml_model=None, ml_conf=0.0)
    scan.run()
    assert storage.load_state()["open_signal"]["id"] == "ml002"
    assert any("GOLD SIGNAL" in m for m in sent)


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


def test_factor_votes_stored_in_state(tmp_path, monkeypatch):
    setup_scan(tmp_path, monkeypatch, new_signal=None)
    scan.run()
    state = storage.load_state()
    assert "last_factor_votes" in state
    votes = state["last_factor_votes"]
    assert isinstance(votes, list) and len(votes) > 0
    assert "name" in votes[0] and "buy" in votes[0] and "sell" in votes[0]


def test_activity_log_appended_after_scan(tmp_path, monkeypatch):
    setup_scan(tmp_path, monkeypatch, new_signal=None)
    scan.run()
    state = storage.load_state()
    assert "activity_log" in state
    assert len(state["activity_log"]) >= 1
    entry = state["activity_log"][-1]
    assert "event" in entry and "time" in entry and "ts" in entry

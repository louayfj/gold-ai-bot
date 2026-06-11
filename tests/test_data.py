import pytest

from goldeye import data
from goldeye.data import DataError, fetch_candles

TD_FIXTURE = {
    "status": "ok",
    "values": [
        # Twelve Data returns newest first
        {"datetime": "2026-06-11 10:15:00", "open": "3341.0", "high": "3344.0",
         "low": "3340.0", "close": "3343.5"},
        {"datetime": "2026-06-11 10:00:00", "open": "3338.0", "high": "3342.0",
         "low": "3337.0", "close": "3341.0"},
    ],
}


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise data.requests.HTTPError(str(self.status_code))


def test_twelvedata_parses_oldest_first(monkeypatch):
    monkeypatch.setenv("TWELVEDATA_API_KEY", "k")
    monkeypatch.setattr(data.requests, "get", lambda *a, **kw: FakeResponse(TD_FIXTURE))
    candles = fetch_candles("15min", 2)
    assert len(candles) == 2
    assert candles[0].close == 3341.0      # oldest first
    assert candles[1].high == 3344.0
    assert candles[1].ts > candles[0].ts


def test_falls_back_to_yahoo_on_error(monkeypatch):
    monkeypatch.setenv("TWELVEDATA_API_KEY", "k")
    monkeypatch.setattr(
        data.requests, "get",
        lambda *a, **kw: FakeResponse({"status": "error", "message": "limit"}),
    )
    sentinel = [data.Candle(1, 1, 2, 0.5, 1.5)]
    monkeypatch.setattr(data, "_fetch_yahoo", lambda interval, n: sentinel)
    monkeypatch.setattr(data.time, "sleep", lambda s: None)
    assert fetch_candles("15min", 10) is sentinel


def test_raises_dataerror_when_all_sources_fail(monkeypatch):
    monkeypatch.setenv("TWELVEDATA_API_KEY", "k")

    def boom(*a, **kw):
        raise data.requests.ConnectionError("down")

    monkeypatch.setattr(data.requests, "get", boom)
    monkeypatch.setattr(data, "_fetch_yahoo",
                        lambda *a: (_ for _ in ()).throw(RuntimeError("also down")))
    monkeypatch.setattr(data.time, "sleep", lambda s: None)
    with pytest.raises(DataError):
        fetch_candles("15min", 10)

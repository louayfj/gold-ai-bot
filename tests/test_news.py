from datetime import datetime, timezone

from goldeye import news
from goldeye.news import fetch_calendar, news_block

EVENTS = [
    {"title": "Non-Farm Employment Change", "country": "USD",
     "date": "2026-06-12T08:30:00-04:00", "impact": "High"},
    {"title": "German Factory Orders", "country": "EUR",
     "date": "2026-06-12T08:30:00-04:00", "impact": "High"},
    {"title": "Crude Oil Inventories", "country": "USD",
     "date": "2026-06-12T08:30:00-04:00", "impact": "Low"},
]


def test_blocks_high_impact_usd_within_window():
    now = datetime(2026, 6, 12, 12, 0, tzinfo=timezone.utc)  # 30 min before 12:30 UTC
    assert "Non-Farm" in news_block(now, EVENTS)


def test_no_block_outside_window():
    now = datetime(2026, 6, 12, 10, 0, tzinfo=timezone.utc)
    assert news_block(now, EVENTS) is None


def test_low_impact_and_foreign_events_ignored():
    now = datetime(2026, 6, 12, 12, 30, tzinfo=timezone.utc)
    only_noise = [e for e in EVENTS if "Non-Farm" not in e["title"]]
    assert news_block(now, only_noise) is None


def test_fetch_failure_fails_open(monkeypatch):
    def boom(*a, **kw):
        raise news.requests.ConnectionError("down")

    monkeypatch.setattr(news.requests, "get", boom)
    monkeypatch.setattr(news.time, "sleep", lambda s: None)
    events, warning = fetch_calendar()
    assert events == []
    assert "calendar" in warning.lower()

"""Tests for the web dashboard API endpoints."""

import json
import pytest


@pytest.fixture
def app(tmp_path, monkeypatch):
    from goldeye import storage, web
    monkeypatch.setattr(storage, "STATE_JSON", str(tmp_path / "state.json"))
    monkeypatch.setattr(storage, "SIGNALS_CSV", str(tmp_path / "signals.csv"))

    web.app.config["TESTING"] = True
    with web.app.test_client() as client:
        yield client


@pytest.fixture
def app_with_signals(tmp_path, monkeypatch):
    from goldeye import storage, web
    monkeypatch.setattr(storage, "STATE_JSON", str(tmp_path / "state.json"))
    monkeypatch.setattr(storage, "SIGNALS_CSV", str(tmp_path / "signals.csv"))

    state = {
        "balance": 112.50,
        "open_signal": None,
        "last_scan_ts": 1749700000,
        "last_no_signal": "buy 3/7 — below threshold",
        "last_sentiment": "neutral (+0 from 5 headlines)",
        "errors": [],
        "news_skips": [],
    }
    (tmp_path / "state.json").write_text(json.dumps(state))

    csv_rows = (
        "id,timestamp,tier,direction,entry,sl,tp,lot,risk_usd,score,"
        "votes,news_flag,status,closed_at,pnl_usd,balance_after\n"
        "abc1,1749600000,GOLD,BUY,2340.0,2330.0,2355.0,0.01,5.0,5,"
        "trend|momentum,0,tp,1749606000,7.50,107.50\n"
        "abc2,1749610000,GOLD,SELL,2350.0,2360.0,2335.0,0.01,5.0,6,"
        "trend|macd|momentum,0,sl,1749616000,-5.0,102.50\n"
        "abc3,1749620000,GOLD,BUY,2345.0,2335.0,2360.0,0.01,5.0,5,"
        "trend|session,0,open,,,"
    )
    (tmp_path / "signals.csv").write_text(csv_rows)

    web.app.config["TESTING"] = True
    with web.app.test_client() as client:
        yield client


def test_dashboard_returns_html(app):
    resp = app.get("/")
    assert resp.status_code == 200
    assert b"GoldEye" in resp.data
    assert b"<html" in resp.data.lower()


def test_dashboard_contains_chart_js(app):
    resp = app.get("/")
    assert b"chart" in resp.data.lower()


def test_api_state_returns_json(app):
    resp = app.get("/api/state")
    assert resp.status_code == 200
    assert resp.content_type.startswith("application/json")


def test_api_state_has_required_keys(app):
    resp = app.get("/api/state")
    data = json.loads(resp.data)
    assert "balance" in data
    assert "open_signal" in data
    assert "last_scan_ts" in data


def test_api_state_shows_balance(app_with_signals):
    resp = app_with_signals.get("/api/state")
    data = json.loads(resp.data)
    assert data["balance"] == 112.50


def test_api_state_includes_human_readable_scan_time(app_with_signals):
    resp = app_with_signals.get("/api/state")
    data = json.loads(resp.data)
    assert "last_scan_human" in data
    assert "UTC" in data["last_scan_human"]


def test_api_signals_returns_json_array(app):
    resp = app.get("/api/signals")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert isinstance(data, list)


def test_api_signals_empty_when_no_csv(app):
    resp = app.get("/api/signals")
    data = json.loads(resp.data)
    assert data == []


def test_api_signals_returns_all_rows(app_with_signals):
    resp = app_with_signals.get("/api/signals")
    data = json.loads(resp.data)
    assert len(data) == 3


def test_api_signals_row_has_expected_fields(app_with_signals):
    resp = app_with_signals.get("/api/signals")
    rows = json.loads(resp.data)
    row = rows[0]
    assert row["tier"] == "GOLD"
    assert row["direction"] == "BUY"
    assert row["status"] == "tp"
    assert row["pnl_usd"] == "7.50"


def test_api_stats_returns_summary(app_with_signals):
    resp = app_with_signals.get("/api/stats")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert "win_rate" in data
    assert "total_closed" in data
    assert "total_pnl" in data
    assert "balance" in data


def test_api_stats_win_rate_calculation(app_with_signals):
    resp = app_with_signals.get("/api/stats")
    data = json.loads(resp.data)
    assert data["total_closed"] == 2
    assert data["wins"] == 1
    assert abs(data["win_rate"] - 50.0) < 0.1


def test_api_stats_pnl_sum(app_with_signals):
    resp = app_with_signals.get("/api/stats")
    data = json.loads(resp.data)
    assert abs(data["total_pnl"] - 2.50) < 0.01


def test_api_stats_balance_chart_points(app_with_signals):
    resp = app_with_signals.get("/api/stats")
    data = json.loads(resp.data)
    assert "balance_chart" in data
    points = data["balance_chart"]
    assert len(points) == 2  # only closed signals
    assert points[0]["balance"] == 107.50
    assert points[1]["balance"] == 102.50


# --- New stats tests --------------------------------------------------------

def test_api_stats_has_profit_factor(app_with_signals):
    resp = app_with_signals.get("/api/stats")
    data = json.loads(resp.data)
    assert "profit_factor" in data


def test_api_stats_profit_factor_calculation(app_with_signals):
    # win pnl = 7.50, loss pnl = 5.00  →  PF = 1.5
    resp = app_with_signals.get("/api/stats")
    data = json.loads(resp.data)
    assert abs(data["profit_factor"] - 1.5) < 0.01


def test_api_stats_max_drawdown(app_with_signals):
    # balance: 100 → 107.50 → 102.50
    # peak=107.50, dd=(107.50-102.50)/107.50*100 ≈ 4.65%
    resp = app_with_signals.get("/api/stats")
    data = json.loads(resp.data)
    assert "max_drawdown_pct" in data
    assert abs(data["max_drawdown_pct"] - 4.65) < 0.1


def test_api_stats_streak_is_loss(app_with_signals):
    # last closed signal (abc2) is sl → streak = 1 loss
    resp = app_with_signals.get("/api/stats")
    data = json.loads(resp.data)
    assert data["streak"] == 1
    assert data["streak_type"] == "loss"


def test_api_stats_avg_duration(app_with_signals):
    # both trades: 6000s each → 1.666...h  → rounded 1.7
    resp = app_with_signals.get("/api/stats")
    data = json.loads(resp.data)
    assert "avg_duration_h" in data
    assert abs(data["avg_duration_h"] - 1.7) < 0.1


def test_api_stats_score_breakdown(app_with_signals):
    resp = app_with_signals.get("/api/stats")
    data = json.loads(resp.data)
    assert "score_breakdown" in data
    by_score = {row["score"]: row for row in data["score_breakdown"]}
    assert "5" in by_score and "6" in by_score
    assert by_score["5"]["wins"] == 1
    assert by_score["6"]["wins"] == 0


def test_api_stats_session_breakdown(app_with_signals):
    resp = app_with_signals.get("/api/stats")
    data = json.loads(resp.data)
    assert "session_breakdown" in data
    assert len(data["session_breakdown"]) > 0
    for row in data["session_breakdown"]:
        assert "session" in row and "total" in row and "win_rate" in row

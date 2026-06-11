from datetime import datetime, timezone

from goldeye.reports import daily_report, weekly_report

NOW = datetime(2026, 6, 12, 1, 0, tzinfo=timezone.utc)  # 08:00 Bangkok
NOW_TS = int(NOW.timestamp())


def row(**overrides) -> dict:
    base = {
        "id": "x", "timestamp": str(NOW_TS - 3600), "tier": "GOLD",
        "direction": "BUY", "entry": "3341.5", "sl": "3335.2", "tp": "3351.0",
        "lot": "0.01", "risk_usd": "5.0", "score": "6",
        "votes": "1h uptrend|London/NY session", "news_flag": "0",
        "status": "tp", "closed_at": str(NOW_TS - 1800), "pnl_usd": "9.5",
        "balance_after": "109.5",
    }
    base.update(overrides)
    return base


def state(**overrides) -> dict:
    base = {"balance": 109.5, "open_signal": None,
            "last_scan_ts": NOW_TS - 600, "errors": [],
            "last_no_signal": "trend up but RSI overbought", "news_skips": []}
    base.update(overrides)
    return base


def test_daily_report_heartbeat_and_stats():
    signals = [row(), row(id="y", tier="SILVER", status="sl",
                        pnl_usd="-2.5", balance_after="107.0")]
    text = daily_report(signals, state(), NOW)
    assert "✅ GoldEye alive" in text
    assert "last scan 10 min ago" in text
    assert "errors in last 24h: none" in text
    assert "GOLD: 1" in text and "SILVER: 1" in text
    assert "Wins: 1 · Losses: 1" in text
    assert "P/L today: +$7.00" in text
    assert "Balance: $109.50" in text and "+9.5% since start" in text
    assert "win rate" in text.lower()


def test_daily_report_shows_errors_and_no_signal_reason():
    text = daily_report([], state(errors=["boom"], balance=100.0), NOW)
    assert "boom" in text
    assert "No signals in the last 24h" in text
    assert "RSI overbought" in text


def test_weekly_report_needs_enough_data():
    assert "not enough" in weekly_report([row()]).lower()


def test_weekly_report_stats():
    signals = [row(id=str(i), pnl_usd="9.5" if i % 2 else "-5.0",
                   status="tp" if i % 2 else "sl") for i in range(8)]
    text = weekly_report(signals)
    assert "GOLD" in text
    assert "win rate" in text.lower()
    assert "1h uptrend" in text          # factor effectiveness section

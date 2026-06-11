"""Daily and weekly Telegram reports built from the signals.csv history."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from goldeye.config import START_BALANCE, TZ

MIN_TRADES_FOR_STATS = 5
_CLOSED = ("tp", "sl")


def _closed(signals: list[dict]) -> list[dict]:
    return [s for s in signals if s["status"] in _CLOSED]


def _win_rate(closed: list[dict]) -> float | None:
    if not closed:
        return None
    wins = sum(1 for s in closed if s["status"] == "tp")
    return 100.0 * wins / len(closed)


def daily_report(signals: list[dict], state: dict, now_utc: datetime) -> str:
    local = now_utc.astimezone(ZoneInfo(TZ))
    lines = [f"☀️ GoldEye daily report — {local:%a %d %b %Y, %H:%M} ({TZ})", ""]

    # Heartbeat
    mins = int((now_utc.timestamp() - state.get("last_scan_ts", 0)) / 60)
    scan_note = f"last scan {mins} min ago" if mins < 90 else \
        f"⚠️ last scan {mins} min ago — check the Actions tab!"
    errors = state.get("errors", [])
    err_note = "none" if not errors else f"{len(errors)} → " + "; ".join(errors[-3:])
    lines.append(f"✅ GoldEye alive — {scan_note}, errors in last 24h: {err_note}")
    lines.append("")

    # Last 24h activity
    cutoff = (now_utc - timedelta(hours=24)).timestamp()
    recent = [s for s in signals if float(s["timestamp"]) >= cutoff]
    if recent:
        gold = sum(1 for s in recent if s["tier"] == "GOLD")
        silver = sum(1 for s in recent if s["tier"] == "SILVER")
        closed_recent = _closed(recent)
        wins = sum(1 for s in closed_recent if s["status"] == "tp")
        losses = len(closed_recent) - wins
        pnl = sum(float(s["pnl_usd"] or 0) for s in closed_recent)
        lines.append(f"Signals (24h) — GOLD: {gold} · SILVER: {silver}")
        lines.append(f"Wins: {wins} · Losses: {losses}")
        lines.append(f"P/L today: {'+' if pnl >= 0 else '−'}${abs(pnl):,.2f}")
    else:
        lines.append("No signals in the last 24h.")
        reason = state.get("last_no_signal", "")
        if reason:
            lines.append(f"Last scan verdict: {reason}")
    skips = state.get("news_skips", [])
    if skips:
        lines.append("Stayed silent for news: " + "; ".join(skips[-3:]))
    lines.append("")

    # All-time
    closed_all = _closed(signals)
    rate = _win_rate(closed_all)
    balance = state.get("balance", START_BALANCE)
    growth = 100.0 * (balance - START_BALANCE) / START_BALANCE
    if rate is not None:
        lines.append(f"Running win rate: {rate:.0f}% ({len(closed_all)} closed)")
    lines.append(
        f"Balance: ${balance:,.2f} ({'+' if growth >= 0 else ''}{growth:.1f}% since start)"
    )
    return "\n".join(lines)


def weekly_report(signals: list[dict]) -> str:
    lines = ["📊 GoldEye weekly self-check", ""]
    closed = _closed(signals)
    if len(closed) < MIN_TRADES_FOR_STATS:
        lines.append(
            f"Not enough closed trades yet ({len(closed)}/{MIN_TRADES_FOR_STATS}) "
            "for meaningful statistics — keep collecting."
        )
        return "\n".join(lines)

    # Per tier
    for tier in ("GOLD", "SILVER"):
        tier_closed = [s for s in closed if s["tier"] == tier]
        rate = _win_rate(tier_closed)
        pnl = sum(float(s["pnl_usd"] or 0) for s in tier_closed)
        if rate is None:
            lines.append(f"{tier}: no closed trades")
        else:
            lines.append(
                f"{tier}: {len(tier_closed)} trades · win rate {rate:.0f}% · "
                f"P/L {'+' if pnl >= 0 else '−'}${abs(pnl):,.2f}"
            )
    lines.append("")

    # Per session (entry hour, Bangkok time)
    buckets = {"London (14-19 ICT)": (7, 12), "Overlap (19-23 ICT)": (12, 16),
               "New York (23-04 ICT)": (16, 21)}
    lines.append("By session:")
    for label, (lo, hi) in buckets.items():
        in_bucket = [
            s for s in closed
            if lo <= datetime.fromtimestamp(float(s["timestamp"]), timezone.utc).hour < hi
        ]
        rate = _win_rate(in_bucket)
        lines.append(f"  {label}: " +
                     (f"{len(in_bucket)} trades · {rate:.0f}% wins" if rate is not None
                      else "no trades"))
    lines.append("")

    # Factor effectiveness: win rate of closed trades whose vote list included it
    lines.append("Factor effectiveness (win rate when factor voted):")
    stats: dict[str, list[int]] = {}
    for s in closed:
        for label in s["votes"].split("|"):
            if label:
                stats.setdefault(label, []).append(1 if s["status"] == "tp" else 0)
    ranked = sorted(stats.items(), key=lambda kv: -sum(kv[1]) / len(kv[1]))
    for label, results in ranked:
        lines.append(
            f"  {label}: {100 * sum(results) / len(results):.0f}% ({len(results)} trades)"
        )
    return "\n".join(lines)

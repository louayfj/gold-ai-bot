"""Telegram formatting + delivery. Plain text (no parse_mode) to avoid
escaping surprises with market data."""

import os
import time

import requests

from goldeye.models import Direction, Signal, Status, Tier


def format_signal(sig: Signal) -> str:
    medal = "🥇 GOLD" if sig.tier == Tier.GOLD else "🥈 SILVER"
    sl_dist = abs(sig.entry - sig.sl)
    tp_dist = abs(sig.tp - sig.entry)
    rr = tp_dist / sl_dist if sl_dist else 0
    risk_pct = "5%" if sig.tier == Tier.GOLD else "2.5%"
    lines = [
        f"{medal} SIGNAL — {sig.direction.value} XAU/USD   (score {sig.score}/7)",
        f"Entry: {sig.entry:,.2f}",
        f"SL:    {sig.sl:,.2f}  (−${sl_dist:,.2f}/oz)",
        f"TP:    {sig.tp:,.2f}  (+${tp_dist:,.2f}/oz, R:R 1:{rr:.1f})",
        f"Lot:   {sig.lot:.2f}  → risk ≈ ${sig.risk_usd:,.2f}"
        + ("" if sig.min_lot_flag else f" ({risk_pct})"),
    ]
    if sig.min_lot_flag:
        lines.append("⚠️ Risk exceeds plan at the minimum lot (0.01) — "
                     "skip this one if that's too much.")
    lines.append("")
    lines.append("Why: " + " · ".join(sig.reasons))
    if sig.missing:
        lines.append("Missing: " + " · ".join(sig.missing))
    return "\n".join(lines)


def format_outcome(sig: Signal) -> str:
    direction = f"{sig.direction.value} from {sig.entry:,.2f}"
    if sig.status == Status.TP:
        head = f"🎯 TP hit: +${sig.pnl_usd:,.2f}  ({direction})"
    elif sig.status == Status.SL:
        head = f"🛑 SL hit: −${abs(sig.pnl_usd):,.2f}  ({direction})"
    else:
        head = f"⌛ Signal expired after 24h without TP/SL  ({direction})"
    return f"{head}\nBalance: ${sig.balance_after:,.2f}"


def send(text: str) -> bool:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for attempt in range(3):
        try:
            resp = requests.post(
                url, json={"chat_id": chat_id, "text": text}, timeout=15
            )
            resp.raise_for_status()
            return True
        except Exception:  # noqa: BLE001
            time.sleep(2**attempt)
    return False


def send_error(summary: str) -> bool:
    return send(f"⚠️ GoldEye error: {summary}")

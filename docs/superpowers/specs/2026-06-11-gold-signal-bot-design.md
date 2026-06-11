# GoldEye — XAU/USD Signal Bot Design

**Date:** 2026-06-11
**Status:** Approved by user (pending spec review)

## Purpose

A fully automated XAU/USD (gold) signal bot for a $100 trading account. It scans the
market continuously, sends entry signals to the user's Telegram, logs every signal,
tracks whether each one hit take-profit or stop-loss, and reports performance honestly.
The user trades the signals manually at their broker; the bot never places orders.

Win-rate expectation is managed by design, not promised: the bot trades only stacked
confluence setups, measures its real win rate from the log, and is tuned from evidence
via a weekly self-check.

## User decisions (locked)

| Decision | Choice |
|---|---|
| Instrument | XAU/USD only |
| Style | Intraday swing — 15m entries, 1h trend filter |
| Hosting | GitHub Actions scheduled workflows (free) |
| Risk per trade | 5% of account ($5) for GOLD tier; $2.50 for SILVER tier |
| Engine | 7-factor confluence voting (Option A + candle patterns) |
| Tiers | GOLD = 5–7/7 factors, full risk; SILVER = 4/7, half risk, labelled & tracked separately |
| Extras | Morning heartbeat, daily performance report, news filter, weekly self-check |
| Not included | Trade-management follow-up alerts (breakeven/partial); ML models |

## Architecture

Python 3.12 project in a private GitHub repository on the user's account. No always-on
server. Three GitHub Actions workflows:

1. **`scan.yml`** — cron `*/15 * * * *`:
   - Fetch XAU/USD 15m + 1h candles (Twelve Data primary, Yahoo Finance `GC=F` fallback).
   - First: check open signal against 5m candles since entry → mark TP/SL/expired,
     update ledger, send outcome message ("🎯 TP hit: +$7.50" / "🛑 SL hit: −$5.00").
   - Then: if no open signal, evaluate the 7 factors. Score ≥5 → GOLD signal;
     score =4 → SILVER signal; otherwise record the failing factors for reporting.
   - Apply news filter before sending.
   - Commit updated `data/signals.csv` and `data/state.json` back to the repo.
2. **`daily.yml`** — cron, morning (time + timezone configurable in `config.py`,
   default 08:00 UTC until user provides timezone):
   - Heartbeat: "✅ Bot alive — last scan N min ago, errors in last 24h: none/list".
   - Performance report: signals sent (per tier), wins/losses, $ P/L, running win
     rate, account balance vs the $100 start, and "why no signal" explanations for
     quiet periods.
3. **`weekly.yml`** — cron, Sunday:
   - Self-check from the log: win rate per tier, per setup type, per session/hour,
     factor effectiveness ranking, and tuning suggestions.

Absence of the morning heartbeat is the user's "bot is down" alarm; a dead scheduler
cannot announce itself.

## Data sources

- **Prices:** Twelve Data free API (`XAU/USD`, free API key, 800 credits/day; usage
  ≈ 200/day). Fallback: `yfinance` gold futures `GC=F`. If both fail, retry then
  send a Telegram error alert and skip the run.
- **News:** ForexFactory weekly calendar JSON
  (`https://nfs.faireconomy.media/ff_calendar_thisweek.json`). No signals within
  ±45 minutes of high-impact USD events. Skipped-for-news periods are mentioned in
  the daily report.

## The 7 confluence factors

Each factor votes for BUY, SELL, or abstains. A direction's score = its votes.

1. **Trend (1h):** EMA50 vs EMA200 + price position relative to both.
2. **Momentum (15m):** RSI(14) — favors pullback entries in trend direction,
   vetoes overbought buys / oversold sells.
3. **MACD (15m):** signal-line cross / histogram direction agreement.
4. **Volatility regime:** ATR(14) within tradable band — abstains when dead-quiet
   (no follow-through) or hyper-volatile (untradable spikes).
5. **Support/resistance:** proximity to recent swing highs/lows; buys near support,
   sells near resistance, vetoes entries straight into a level.
6. **Session timing:** votes only during London and New York sessions.
7. **Candle patterns (15m):** engulfing, pin bar/hammer, star patterns in the
   signal direction.

## Trade construction

- **SL:** 1.5 × ATR(14, 15m) beyond entry, snapped past nearest swing point.
- **TP:** ≥1.5 × SL distance (risk:reward ≥ 1:1.5).
- **Lot size:** `risk_usd / sl_distance_usd_per_001lot`, rounded down to broker
  micro-lot steps (0.01). 0.01 lot XAU/USD = 1 oz = $1 P/L per $1.00 price move.
  If required lot < 0.01, the signal is sent flagged "risk exceeds plan at minimum
  lot" with the actual $ risk at 0.01.
- One open signal at a time (across both tiers). Open signals expire after 24h.

## Telegram message format (signal)

```
🥇 GOLD SIGNAL — BUY XAU/USD   (score 6/7)
Entry: 3,341.50
SL:    3,335.20  (−$6.30/oz)
TP:    3,351.00  (+$9.50/oz, R:R 1:1.5)
Lot:   0.01  → risk ≈ $5.00 (5%)

Why: 1h uptrend (EMA50>200) · RSI pullback 41 · MACD bull cross ·
ATR normal · bounced off support 3,338 · London session
Missing: no candle pattern
```

SILVER uses 🥈, half risk, same format.

## Logging & outcome tracking

- `data/signals.csv` — one row per signal: id, timestamp (UTC), tier, direction,
  entry, sl, tp, lot, risk_usd, score, factor votes, news-window flag, status
  (open/tp/sl/expired), closed_at, pnl_usd, balance_after.
- `data/state.json` — open signal, ledger balance (starts $100.00), last-scan
  timestamp, error ring buffer for the heartbeat.
- Outcome resolution replays 5m candles since entry; if TP and SL fall inside the
  same 5m candle, SL is counted (conservative).
- Files are committed by the workflow itself, so the repo history is an audit trail.

## Error handling

- Data fetch: 3 retries with backoff → fallback source → alert + skip run.
- Telegram send: retries; a send failure is logged into the error buffer.
- Any unhandled exception sends a "⚠️ Bot error" Telegram message with the summary.
- All state writes are atomic (write temp, rename) to survive interrupted runs.

## Testing

- Unit tests (pytest): every indicator against known-value fixtures, factor voting,
  lot sizing, TP/SL resolution incl. the same-candle case, news-window logic.
- **Backtest script** (`backtest.py`, run locally): replays the exact production
  engine over recent months of 15m/1h gold data; prints per-tier win rate, profit
  factor, max drawdown, and trade list. Gate before going live: results reviewed
  with the user.

## Secrets & setup (user-provided)

- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TWELVEDATA_API_KEY` as GitHub Actions
  secrets. GitHub repo on the user's account. User's timezone for the morning report.

## Post-backtest amendments (2026-06-11)

A 49-day backtest (Apr 22–Jun 11 2026, 5000 15m candles) of the exact production
engine forced two changes before going live:

1. **SILVER is info-only by default** (`config.SILVER_INFO_ONLY = True`). Silver
   (4/7) setups lost money in every tested variant (win rate 33–41%, profit factor
   ≤ 1.08). Silver signals are still sent and their TP/SL outcomes logged — as
   evidence for the weekly self-check — but with no lot size and no effect on the
   ledger, until forward data earns them real money.
2. **GOLD risk cap** (`config.MAX_RISK_MULT = 2.0`): a GOLD setup whose
   minimum-lot (0.01) risk exceeds 2× the $5 plan is skipped and the reason
   recorded. Without the cap the backtest's max drawdown was $246 on a $100
   account — i.e. a blown account — because gold's ATR frequently makes the
   minimum lot risk $10–20.

Backtest reference numbers (one regime, small sample — not a promise):
GOLD tier 46 closed trades, 45.7% win rate, profit factor 1.70; results across
filter variants ranged from +$115 to −$91, so the live log is the real test.

## Out of scope

Auto-execution at a broker, ML prediction, multiple instruments, trade-management
follow-ups (may be added later), paid data feeds, guarantees of any specific win rate.

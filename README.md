# GoldEye — XAU/USD Telegram Signal Bot

Scans gold (XAU/USD) every 15 minutes, sends trade signals to Telegram, logs every
signal, tracks whether it hit take-profit or stop-loss, and reports performance
honestly. Runs free 24/7 on GitHub Actions — no server.

> ⚠️ Not financial advice. Signals are produced by a rule-based technical engine;
> past performance (including the backtest) does not guarantee anything.

## How it works

- **Every 15 min** (`scan.yml` → `scan.py`): checks the open signal against 5-minute
  candles (TP/SL/expired → Telegram follow-up + log update), then evaluates a
  7-factor confluence for a new signal.
- **Daily 08:00 Bangkok** (`daily.yml` → `daily.py`): heartbeat ("✅ alive") +
  performance report. **No morning message = something is wrong** → check the
  Actions tab.
- **Sunday 19:00 Bangkok** (`weekly.yml` → `weekly.py`): self-check — win rate per
  tier/session, factor effectiveness.

## Signal tiers

| Tier | Threshold | Money |
|---|---|---|
| 🥇 GOLD | 5–7 of 7 factors | real lot size, $5 risk plan, capped at $10 per trade |
| 🥈 SILVER | 4 of 7 | **info-only** (no lot) — the 49-day backtest showed silver setups lose money, so they're tracked as evidence until proven |

The 7 factors: 1h EMA50/200 trend, 15m RSI pullback, MACD, ATR regime,
support/resistance, London/NY session, candlestick patterns.

On top of the factor vote, a news-sentiment layer (`goldeye/sentiment.py`)
scores the last 12h of headlines from free RSS feeds (FXStreet,
Investing.com commodities, MarketWatch) as gold-bullish or gold-bearish.
A signal that fires *against* strongly one-sided news is skipped and the
skip is logged; agreeing sentiment is added to the signal's reasons.
Headline fetch failures fail open (neutral, no effect).

Last gate: an ML confidence filter (`goldeye/ml.py` + `goldeye/model.json`).
The model is a random forest trained by `train_model.py` on ~2 years of
replayed engine signals (4,363 closed trades). Signals it rates below
`ML_MIN_CONFIDENCE` are skipped. On its held-out test set (newest 873
signals, never seen in training) approved trades won 56.1% vs a 41.4%
baseline. Inference is pure Python — scikit-learn is only needed locally
to retrain. Delete `goldeye/model.json` to disable the gate entirely.
Retrain every 1–2 months as live data accumulates: `python train_model.py`
(only overwrites the model if it beats the baseline by ≥5pts out-of-sample).

## The log

- `data/signals.csv` — every signal with entry/SL/TP, lot, score, votes, outcome
  (tp/sl/expired), $ P/L and running balance (ledger starts at $100).
- `data/state.json` — open signal, balance, last scan, error buffer.
- Both are committed back by the workflows, so git history is the audit trail.

## Tuning knobs (`goldeye/config.py`)

- `RISK_GOLD` / `MAX_RISK_MULT` — risk plan and the per-trade cap.
- `SILVER_INFO_ONLY` — set `False` to give silver signals real lot sizes.
- `GOLD_MIN_SCORE`, `RR`, `SL_ATR_MULT`, `NEWS_BUFFER_MIN`, `SESSION_UTC`, `TZ`.
- `SENTIMENT_BLOCK_SCORE` — how one-sided the news must be to veto a signal;
  `SENTIMENT_MAX_AGE_H` — headline lookback window.
- `ML_MIN_CONFIDENCE` — minimum model confidence to let a signal through.

## Setup

1. Create a Telegram bot via @BotFather; get your chat id.
2. Free API key at twelvedata.com.
3. Repo secrets (Settings → Secrets → Actions): `TELEGRAM_BOT_TOKEN`,
   `TELEGRAM_CHAT_ID`, `TWELVEDATA_API_KEY`.
4. Enable Actions. Locally: copy `.env.example` to `.env` for `python scan.py`,
   `python backtest.py`, `pytest`.

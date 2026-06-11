# GoldEye XAU/USD Signal Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the GoldEye XAU/USD Telegram signal bot per the approved spec (`docs/superpowers/specs/2026-06-11-gold-signal-bot-design.md`): 7-factor confluence engine, two signal tiers, TP/SL outcome tracking with a $100 ledger, news filter, daily/weekly reports, free 24/7 operation on GitHub Actions.

**Architecture:** A pure-Python package (`goldeye/`) with three thin entry points (`scan.py`, `daily.py`, `weekly.py`) invoked by three GitHub Actions cron workflows. State lives in the repo (`data/signals.csv`, `data/state.json`) and is committed back by the workflow. All market math is in dependency-free modules tested with pytest; network edges (Twelve Data, Yahoo, ForexFactory, Telegram) are isolated in `data.py`, `news.py`, `telegram.py`.

**Tech Stack:** Python 3.12, `requests`, `yfinance` (fallback only), `pytest`. No pandas/numpy — indicator math is small and explicit.

**User config (locked):** Risk $5 GOLD / $2.50 SILVER on a $100 ledger; timezone `Asia/Bangkok` (UTC+7); morning job 01:00 UTC = 08:00 ICT; weekly job Sunday 12:00 UTC = 19:00 ICT. Secrets: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TWELVEDATA_API_KEY` — GitHub Actions secrets in prod, `.env` (gitignored) locally.

---

## File Structure

```
goldeye/
  __init__.py
  config.py        # constants + env loading (no I/O beyond os.environ/.env)
  models.py        # Candle, Signal dataclasses, enums
  indicators.py    # ema, rsi, macd, atr, swing_points
  data.py          # fetch_candles(): Twelve Data primary, yfinance fallback
  factors.py       # the 7 voting factors
  engine.py        # score aggregation + build_signal (entry/SL/TP/lot/tier)
  news.py          # ForexFactory calendar fetch + in_news_window()
  storage.py       # atomic state.json + signals.csv read/append/update
  tracker.py       # resolve open signal via 5m replay; ledger update
  telegram.py      # message formatting + send; error alerts
  reports.py       # daily heartbeat/performance, weekly self-check
scan.py            # entry point: track outcomes, then evaluate new signal
daily.py           # entry point: heartbeat + daily report
weekly.py          # entry point: weekly self-check
backtest.py        # replays engine over historical candles, prints stats
tests/             # one test file per module
.github/workflows/ # scan.yml, daily.yml, weekly.yml
data/              # signals.csv, state.json (committed by CI)
requirements.txt, .env.example, .gitignore, README.md
```

---

### Task 1: Scaffold

**Files:** Create `requirements.txt`, `.gitignore`, `.env.example`, `goldeye/__init__.py`, `tests/__init__.py`, `pytest.ini`, `data/.gitkeep`.

- [ ] **Step 1:** Write files:
  - `requirements.txt`: `requests`, `yfinance`, `pytest`, `python-dotenv`
  - `.gitignore`: `.env`, `__pycache__/`, `*.pyc`, `.pytest_cache/`
  - `.env.example`: the three secret names with placeholder values
- [ ] **Step 2:** Create venv, `pip install -r requirements.txt`, verify `pytest` runs (0 tests).
- [ ] **Step 3:** Commit `chore: scaffold project`.

### Task 2: Models + config

**Files:** Create `goldeye/models.py`, `goldeye/config.py`, `tests/test_config.py`.

- [ ] **Step 1:** `models.py`:

```python
from dataclasses import dataclass, field
from enum import Enum

class Direction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

class Tier(str, Enum):
    GOLD = "GOLD"
    SILVER = "SILVER"

class Status(str, Enum):
    OPEN = "open"
    TP = "tp"
    SL = "sl"
    EXPIRED = "expired"

@dataclass
class Candle:
    ts: int        # unix seconds, candle open time, UTC
    open: float
    high: float
    low: float
    close: float

@dataclass
class Signal:
    id: str
    created_ts: int
    tier: Tier
    direction: Direction
    entry: float
    sl: float
    tp: float
    lot: float
    risk_usd: float
    score: int
    reasons: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    min_lot_flag: bool = False
    status: Status = Status.OPEN
    closed_ts: int | None = None
    pnl_usd: float | None = None
    balance_after: float | None = None
```

- [ ] **Step 2:** `config.py` constants: `RISK_GOLD=5.0`, `RISK_SILVER=2.5`, `START_BALANCE=100.0`, `GOLD_MIN_SCORE=5`, `SILVER_SCORE=4`, `RR=1.5`, `SL_ATR_MULT=1.5`, `MIN_LOT=0.01`, `LOT_STEP=0.01`, `OZ_PER_LOT=100`, `SIGNAL_TTL_H=24`, `NEWS_BUFFER_MIN=45`, `SESSION_UTC=(7, 21)`, `TZ="Asia/Bangkok"`, plus `load_secrets()` reading env (with optional `.env` via dotenv).
- [ ] **Step 3:** Test: `load_secrets` raises a clear error when a var is missing; constants sanity. Run, pass, commit `feat: models and config`.

### Task 3: Indicators (TDD)

**Files:** Create `goldeye/indicators.py`, `tests/test_indicators.py`.

All functions take `list[float]` (or candles) oldest→newest and return full series (same length, leading `None`s) so factors can look at "previous" values.

- [ ] **Step 1:** Write failing tests with hand-checkable fixtures:

```python
def test_ema_converges_to_constant():
    assert ema([5.0] * 50, 10)[-1] == pytest.approx(5.0)

def test_rsi_all_gains_is_100():
    closes = [float(i) for i in range(1, 40)]
    assert rsi(closes, 14)[-1] == pytest.approx(100.0)

def test_rsi_alternating_is_near_50():
    closes = [100 + (1 if i % 2 else -1) for i in range(60)]
    assert 40 < rsi(closes, 14)[-1] < 60

def test_atr_constant_range():
    candles = [Candle(i, 10, 12, 9, 11) for i in range(40)]
    assert atr(candles, 14)[-1] == pytest.approx(3.0, abs=0.1)

def test_macd_signs():  # rising series → positive histogram
    closes = [float(i) for i in range(1, 80)]
    macd_line, signal_line, hist = macd(closes)
    assert hist[-1] > 0

def test_swing_points_finds_local_extremes():
    highs = [1,2,3,9,3,2,1,2,3,2,1]; lows = [x - 1 for x in highs]
    candles = [Candle(i, h-0.5, h, l, h-0.5) for i, (h, l) in enumerate(zip(highs, lows))]
    sh, sl_ = swing_points(candles, left=2, right=2)
    assert 3 in [i for i, _ in sh]
```

- [ ] **Step 2:** Run, verify FAIL (functions undefined).
- [ ] **Step 3:** Implement: `ema(values, period)` (seed = SMA of first `period`), `rsi(closes, period)` (Wilder smoothing), `macd(closes, fast=12, slow=26, signal=9) -> (macd, signal, hist)`, `atr(candles, period)` (Wilder, true range), `swing_points(candles, left, right) -> (swing_highs, swing_lows)` as `(index, price)` lists.
- [ ] **Step 4:** Run, pass. Commit `feat: indicators`.

### Task 4: Data fetching

**Files:** Create `goldeye/data.py`, `tests/test_data.py`.

- [ ] **Step 1:** Failing tests using `monkeypatch` on `requests.get`: Twelve Data JSON fixture parses to oldest-first `Candle`s; HTTP error → falls back to `_fetch_yahoo` (monkeypatched); both fail → raises `DataError`.
- [ ] **Step 2:** Implement `fetch_candles(interval: str, outputsize: int) -> list[Candle]`:
  - Twelve Data `GET https://api.twelvedata.com/time_series?symbol=XAU/USD&interval={interval}&outputsize={n}&timezone=UTC&apikey=...`, 3 retries with backoff, values come newest-first → reverse.
  - Fallback `_fetch_yahoo` via `yfinance.Ticker("GC=F").history(...)` mapping intervals (`15min→15m`, `1h→1h`, `5min→5m`).
  - `class DataError(Exception)`.
- [ ] **Step 3:** Run, pass. Commit `feat: data fetching with fallback`.

### Task 5: The 7 factors (TDD)

**Files:** Create `goldeye/factors.py`, `tests/test_factors.py`.

Each factor: `def factor_x(ctx) -> Vote` where `Vote = namedtuple("Vote", "buy sell label")` (`buy`/`sell` are bools; both False = abstain) and `ctx` is a `FactorContext` dataclass holding `c15: list[Candle]`, `c1h: list[Candle]`, precomputed indicator series, and `now_utc: datetime`.

- [ ] **Step 1:** Failing tests, one per factor, with synthetic candle series, e.g.:

```python
def test_trend_votes_buy_when_ema50_above_ema200_and_price_above():
def test_momentum_vetoes_buy_when_rsi_overbought():        # rsi > 70 → no buy vote
def test_momentum_votes_buy_on_pullback_in_uptrend():      # 40 <= rsi <= 55
def test_macd_votes_with_histogram_direction():
def test_volatility_abstains_when_atr_out_of_band():       # band: median*0.5..median*2.5
def test_sr_votes_buy_near_support():                      # within 0.3*ATR of swing low
def test_session_votes_only_in_window():                   # 07:00–21:00 UTC both-direction vote
def test_candles_detect_bullish_engulfing_and_pin_bar():
```

- [ ] **Step 2:** Run, FAIL. Implement the factors:
  1. `factor_trend`: 1h EMA50 vs EMA200 and last close vs EMA50.
  2. `factor_momentum`: 15m RSI(14); buy vote when 40–55 in uptrend context, sell when 45–60 in downtrend; hard abstain >70 (buy) / <30 (sell).
  3. `factor_macd`: 15m histogram sign + rising/falling.
  4. `factor_volatility`: ATR(14) within `[0.5, 2.5] ×` median ATR of the last 100 bars → votes both directions (regime gate), else abstain.
  5. `factor_sr`: distance from last swing low/high (left=right=3) vs `0.3×ATR`; near support → buy, near resistance → sell; *within* `0.3×ATR` of opposing level → abstain.
  6. `factor_session`: both-direction vote inside 07:00–21:00 UTC.
  7. `factor_candles`: bullish/bearish engulfing, pin bar (wick ≥ 2× body, body in top/bottom third) on the last closed 15m candle.
- [ ] **Step 3:** Run, pass. Commit `feat: confluence factors`.

### Task 6: Engine — scoring + signal construction (TDD)

**Files:** Create `goldeye/engine.py`, `tests/test_engine.py`.

- [ ] **Step 1:** Failing tests:

```python
def test_score_counts_directional_votes():
def test_no_signal_below_silver_threshold():               # score 3 → None
def test_silver_at_4_gold_at_5():
def test_sl_is_atr_based_and_tp_is_rr15():                 # tp_dist == 1.5 * sl_dist
def test_lot_sizing_rounds_down_to_step():                 # risk 5, sl $4.00 → lot 0.01
def test_min_lot_flag_when_risk_exceeds_plan():            # sl $6.30 → lot 0.01, flag True, risk_usd 6.30
def test_sl_snaps_beyond_swing():                          # sl placed past nearest swing low for BUY
```

Lot math (locked): P/L per lot = `OZ_PER_LOT * price_move` → `lot = risk / (100 * sl_dist)`, floored to `LOT_STEP`; if `< MIN_LOT`, use `MIN_LOT`, set `min_lot_flag=True`, and report actual `risk_usd = 100 * MIN_LOT * sl_dist`.

- [ ] **Step 2:** Implement `evaluate(ctx) -> Signal | None` and helper `build_signal(direction, score, reasons, missing, ctx)`. Entry = last 15m close. SL = `entry ∓ SL_ATR_MULT*ATR`, then extended past nearest swing point if that swing is within the ATR stop. TP = `entry ± RR * sl_dist`.
- [ ] **Step 3:** Run, pass. Commit `feat: signal engine`.

### Task 7: News filter

**Files:** Create `goldeye/news.py`, `tests/test_news.py`.

- [ ] **Step 1:** Failing tests with a fixture of the ForexFactory JSON (`[{"title":"Non-Farm...","country":"USD","date":"2026-06-12T12:30:00-04:00","impact":"High"}, ...]`): high-impact USD event within ±45 min → blocked (returns event title); low impact or non-USD → not blocked; fetch failure → fail-open (no block) but returns a warning string for the error buffer.
- [ ] **Step 2:** Implement `fetch_calendar()` (requests, 2 retries) and `news_block(now_utc, events) -> str | None`.
- [ ] **Step 3:** Run, pass. Commit `feat: news filter`.

### Task 8: Storage

**Files:** Create `goldeye/storage.py`, `tests/test_storage.py`.

- [ ] **Step 1:** Failing tests (tmp_path): round-trip `state.json` (open signal, balance, last_scan_ts, errors list capped at 20); `append_signal` then `update_signal` by id in `signals.csv`; atomic write leaves no partial file.
- [ ] **Step 2:** Implement `load_state/save_state` (json, temp-file + `os.replace`), `append_signal(sig)`, `update_signal(sig)` (rewrite CSV row by id), `read_signals() -> list[dict]`. CSV columns exactly per spec: `id,timestamp,tier,direction,entry,sl,tp,lot,risk_usd,score,votes,news_flag,status,closed_at,pnl_usd,balance_after`.
- [ ] **Step 3:** Run, pass. Commit `feat: storage`.

### Task 9: Outcome tracker (TDD — the money math)

**Files:** Create `goldeye/tracker.py`, `tests/test_tracker.py`.

- [ ] **Step 1:** Failing tests:

```python
def test_buy_tp_hit():            # 5m candle high >= tp before any low <= sl → TP, pnl = +100*lot*tp_dist
def test_buy_sl_hit():
def test_sell_tp_hit():           # mirrored
def test_same_candle_counts_sl(): # candle spans both tp and sl → SL (conservative)
def test_expiry_after_24h():      # no hit, created_ts older than TTL → EXPIRED, pnl 0
def test_ledger_updates_balance():
```

- [ ] **Step 2:** Implement `resolve(signal, candles_5m, now_ts, balance) -> Signal | None` (returns updated signal when closed, else None) and `pnl(signal, outcome) -> float`. Walk 5m candles with `ts > created_ts` in order; first candle touching TP or SL decides; both touched in one candle → SL.
- [ ] **Step 3:** Run, pass. Commit `feat: outcome tracker`.

### Task 10: Telegram formatting + sending

**Files:** Create `goldeye/telegram.py`, `tests/test_telegram.py`.

- [ ] **Step 1:** Failing tests for pure formatters (no network): `format_signal(sig)` matches the spec layout (🥇/🥈 header, score, entry/SL/TP with $/oz distances, lot + risk line incl. min-lot warning, Why/Missing lines); `format_outcome(sig)` ("🎯 TP hit: +$7.50 ..." / "🛑 SL hit: −$5.00 ..."); thousands separators on prices.
- [ ] **Step 2:** Implement formatters plus `send(text)` → `POST https://api.telegram.org/bot{token}/sendMessage` (chat_id, text, no parse_mode to avoid escaping bugs), 3 retries; `send_error(summary)` prefixes "⚠️ GoldEye error:". Failures append to the state error buffer rather than raising.
- [ ] **Step 3:** Run, pass. Commit `feat: telegram`.

### Task 11: Reports

**Files:** Create `goldeye/reports.py`, `tests/test_reports.py`.

- [ ] **Step 1:** Failing tests with a synthetic `signals.csv` history: `daily_report(signals, state, now)` includes heartbeat line (minutes since last scan, error list or "none"), counts per tier for the last 24h ICT day, W/L, P/L $, running win rate, balance vs $100, and the most recent "why no signal" summary stored in state; `weekly_report(signals)` includes per-tier win rate, per-session stats, factor effectiveness (win rate of closed signals that included each factor label), and skips sections gracefully with <5 closed trades ("not enough data yet").
- [ ] **Step 2:** Implement. All timestamps rendered in `Asia/Bangkok` (`zoneinfo`).
- [ ] **Step 3:** Run, pass. Commit `feat: reports`.

### Task 12: Entry points

**Files:** Create `scan.py`, `daily.py`, `weekly.py`, `tests/test_scan.py`.

- [ ] **Step 1:** Failing integration test for `scan.run()` with all edges monkeypatched: (a) open signal that resolves → outcome message sent + CSV updated + state cleared; (b) no open signal + engine returns GOLD signal + no news block → signal message sent, state has open signal; (c) news block → no signal, block reason recorded in state; (d) engine returns None → failing-factor summary recorded in state for the daily report.
- [ ] **Step 2:** Implement `scan.run()` orchestration exactly in that order; wrap in try/except → `telegram.send_error` + append to error buffer + non-zero exit only on data errors (so CI shows red). `daily.py`/`weekly.py` are thin: load, build report, send. Update `state.last_scan_ts` every successful scan.
- [ ] **Step 3:** Run all tests, pass. Commit `feat: entry points`.

### Task 13: Backtest

**Files:** Create `backtest.py`.

- [ ] **Step 1:** Implement: fetch max available 15m/1h/5m history (Twelve Data allows 5000 bars; ~2 months of 15m), slide over time evaluating the *production* `engine.evaluate` at each closed 15m bar (with session/news factor as-is, news filter off — no historical calendar), resolve outcomes with the same `tracker.resolve`, print: per-tier trades, win rate, profit factor, max drawdown, ending balance from $100, and the trade list.
- [ ] **Step 2:** Run it for real, review numbers with the user before going live. Commit `feat: backtest`.

### Task 14: Workflows + README + deploy

**Files:** Create `.github/workflows/scan.yml`, `daily.yml`, `weekly.yml`, `README.md`.

- [ ] **Step 1:** `scan.yml`: `schedule: cron "*/15 * * * *"` + `workflow_dispatch`; checkout, setup-python 3.12, pip cache, `pip install -r requirements.txt`, `python scan.py` with the three secrets as env, then commit `data/` if changed (`git add data && git diff --cached --quiet || git commit -m "log: scan $(date -u +%FT%TZ)" && git push`). `concurrency: group: goldeye` to prevent overlapping runs. `daily.yml`: cron `0 1 * * *`. `weekly.yml`: cron `0 12 * * 0`.
- [ ] **Step 2:** README: what it is, signal format, how the log works, how to change risk/thresholds, secrets setup, "no heartbeat = check Actions tab".
- [ ] **Step 3:** Create private GitHub repo (gh CLI), push, set the three secrets via `gh secret set`, trigger `workflow_dispatch` of scan.yml once, verify green run and that the user received the startup/heartbeat test message. Commit `ci: workflows and docs`.

---

## Self-review notes

- Spec coverage: every spec section maps to a task (architecture→12/14, data→4, factors→5, trade construction→6, message format→10, logging→8/9, news→7, errors→12, testing→3–13, secrets→14). Two-tier system covered in 6/10/11.
- Type consistency: `Signal`/`Candle`/`Vote`/`FactorContext` defined once (Tasks 2, 5) and reused by name everywhere.
- No placeholder steps; lot math, same-candle rule, thresholds, crons, and CSV columns are pinned.

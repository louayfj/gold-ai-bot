"""Backtest: replays the production engine over historical Twelve Data candles.

Differences from live trading (both make results *more* conservative):
- outcomes are resolved on 15m candles (live uses 5m), so the same-candle
  SL-first rule triggers more often;
- the news filter is off (no historical calendar), so it includes trades the
  live bot would have skipped around red news.
"""

from bisect import bisect_right
from datetime import datetime, timezone

from goldeye import config, data, engine, tracker
from goldeye.factors import FactorContext
from goldeye.models import Status, Tier

WARMUP_15 = 250   # candles needed for indicators on 15m
WARMUP_1H = 210   # candles needed for EMA200 on 1h


def run_backtest() -> None:
    config.load_secrets()
    print("Fetching history from Twelve Data...")
    c15 = data.fetch_candles("15min", 5000)
    c1h = data.fetch_candles("1h", 5000)
    ts_1h = [c.ts for c in c1h]
    start = datetime.fromtimestamp(c15[WARMUP_15].ts, timezone.utc)
    end = datetime.fromtimestamp(c15[-1].ts, timezone.utc)
    print(f"15m candles: {len(c15)}  ({start:%Y-%m-%d} .. {end:%Y-%m-%d})")

    balance = config.START_BALANCE
    trades = []
    open_until_idx = 0

    for i in range(WARMUP_15, len(c15) - 1):
        if i < open_until_idx:
            continue
        candle = c15[i]
        # 1h candles fully closed by this 15m candle's close
        close_time = candle.ts + 900
        n_1h = bisect_right(ts_1h, close_time - 3600)
        if n_1h < WARMUP_1H:
            continue
        window_15 = c15[max(0, i - 400) : i + 1]
        window_1h = c1h[max(0, n_1h - 250) : n_1h]
        try:
            ctx = FactorContext.build(
                window_15, window_1h,
                datetime.fromtimestamp(close_time, timezone.utc),
            )
        except ValueError:
            continue
        sig = engine.evaluate(ctx)
        if sig is None:
            continue

        ttl_ts = sig.created_ts + config.SIGNAL_TTL_H * 3600
        future = [c for c in c15[i + 1 :] if c.ts <= ttl_ts]
        closed = tracker.resolve(sig, future, ttl_ts + 1, balance)
        if closed is None:
            break  # ran out of data while the trade was open
        balance = closed.balance_after
        trades.append(closed)
        if closed.closed_ts:
            while open_until_idx < len(c15) and c15[open_until_idx].ts <= closed.closed_ts:
                open_until_idx += 1

    report(trades, balance)


def report(trades, balance) -> None:
    print(f"\n{'='*62}\nBACKTEST RESULTS (start balance ${config.START_BALANCE:.2f})\n{'='*62}")
    for tier in (Tier.GOLD, Tier.SILVER):
        rows = [t for t in trades if t.tier == tier]
        closed = [t for t in rows if t.status in (Status.TP, Status.SL)]
        wins = [t for t in closed if t.status == Status.TP]
        losses = [t for t in closed if t.status == Status.SL]
        expired = [t for t in rows if t.status == Status.EXPIRED]
        gross_win = sum(t.pnl_usd for t in wins)
        gross_loss = -sum(t.pnl_usd for t in losses)
        pf = (gross_win / gross_loss) if gross_loss else float("inf")
        wr = 100 * len(wins) / len(closed) if closed else 0.0
        print(f"\n{tier.value}: {len(rows)} signals "
              f"({len(closed)} closed, {len(expired)} expired)")
        if closed:
            print(f"  win rate:      {wr:.1f}%  ({len(wins)}W / {len(losses)}L)")
            print(f"  profit factor: {pf:.2f}")
            print(f"  net P/L:       ${sum(t.pnl_usd for t in closed):+,.2f}")

    # equity curve / drawdown
    eq = config.START_BALANCE
    peak, max_dd = eq, 0.0
    for t in trades:
        eq += t.pnl_usd or 0
        peak = max(peak, eq)
        max_dd = max(max_dd, peak - eq)
    print(f"\nEnding balance: ${balance:,.2f}")
    print(f"Max drawdown:   ${max_dd:,.2f}")

    print(f"\n{'-'*62}\nTrade list:")
    for t in trades:
        when = datetime.fromtimestamp(t.created_ts, timezone.utc)
        print(f"  {when:%m-%d %H:%M} {t.tier.value:6} {t.direction.value:4} "
              f"@{t.entry:9,.2f}  score {t.score}/7  {t.status.value.upper():7} "
              f"{('$%+.2f' % t.pnl_usd) if t.pnl_usd is not None else '':>9}")


if __name__ == "__main__":
    run_backtest()

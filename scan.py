"""GoldEye scanner: runs every 15 minutes via GitHub Actions.
Order matters: resolve the open signal first, then look for a new one."""

import sys
from datetime import datetime, timezone

from goldeye import config, data, engine, news, sentiment, storage, telegram, tracker
from goldeye.factors import ALL_FACTORS, FactorContext, Vote  # noqa: F401 (Vote: test seam)
from goldeye.models import Direction


def run() -> None:
    config.load_secrets()
    state = storage.load_state()
    now = datetime.now(timezone.utc)
    now_ts = int(now.timestamp())

    # 1. Track the open signal
    if state.get("open_signal"):
        sig = storage.signal_from_dict(state["open_signal"])
        candles_5m = data.fetch_candles("5min", 300)
        closed = tracker.resolve(sig, candles_5m, now_ts, state["balance"])
        if closed:
            state["balance"] = closed.balance_after
            state["open_signal"] = None
            storage.update_signal(closed)
            telegram.send(telegram.format_outcome(closed))

    # 2. Look for a new signal
    if state.get("open_signal") is None:
        c15 = data.fetch_candles("15min", 350)
        c1h = data.fetch_candles("1h", 350)
        ctx = FactorContext.build(c15, c1h, now)
        sig = engine.evaluate(ctx)
        if sig is not None:
            events, warning = news.fetch_calendar()
            if warning:
                state.setdefault("errors", []).append(warning)
            block = news.news_block(now, events)
            if block:
                sig.news_flag = True
                state["last_no_signal"] = f"setup found but blocked by news: {block}"
                skips = state.setdefault("news_skips", [])
                skips.append(f"{now:%d %b %H:%M} UTC — {block}")
                state["news_skips"] = skips[-5:]
            else:
                headlines, senti_warn = sentiment.fetch_headlines()
                if senti_warn:
                    state.setdefault("errors", []).append(senti_warn)
                senti = sentiment.analyze(headlines)
                state["last_sentiment"] = (
                    f"{senti.label} ({senti.score:+d} from {senti.n} headlines)"
                )
                senti_block = sentiment.opposes(sig.direction, senti)
                if senti_block:
                    state["last_no_signal"] = f"setup found but {senti_block}"
                    skips = state.setdefault("news_skips", [])
                    skips.append(f"{now:%d %b %H:%M} UTC — {senti_block}")
                    state["news_skips"] = skips[-5:]
                else:
                    agrees = (senti.score > 0) == (sig.direction == Direction.BUY)
                    if senti.label != "neutral" and agrees:
                        sig.reasons.append(
                            f"news sentiment {senti.label} ({senti.score:+d})"
                        )
                    storage.append_signal(sig)
                    state["open_signal"] = storage.signal_to_dict(sig)
                    telegram.send(telegram.format_signal(sig))
        else:
            votes = [f(ctx) for f in ALL_FACTORS]
            buy = [v.label for v in votes if v.buy]
            sell = [v.label for v in votes if v.sell]
            if max(len(buy), len(sell)) >= config.GOLD_MIN_SCORE:
                # threshold was met, so evaluate() skipped it for oversized risk
                state["last_no_signal"] = (
                    f"setup at {max(len(buy), len(sell))}/7 skipped — stop too "
                    "wide for the $100 account even at the minimum lot"
                )
            else:
                state["last_no_signal"] = (
                    f"buy {len(buy)}/7 ({', '.join(buy) or 'none'}) · "
                    f"sell {len(sell)}/7 ({', '.join(sell) or 'none'}) — below threshold"
                )

    state["last_scan_ts"] = now_ts
    storage.save_state(state)


def main() -> int:
    try:
        run()
        return 0
    except Exception as exc:  # noqa: BLE001 - last-resort alert
        summary = f"scan failed: {type(exc).__name__}: {exc}"
        try:
            state = storage.load_state()
            state.setdefault("errors", []).append(
                f"{datetime.now(timezone.utc):%d %b %H:%M} {summary}"
            )
            storage.save_state(state)
            telegram.send_error(summary)
        except Exception:  # noqa: BLE001
            pass
        print(summary, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

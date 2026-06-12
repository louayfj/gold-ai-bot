"""GoldEye scanner: runs every 15 minutes via GitHub Actions.
Order matters: resolve the open signal first, then look for a new one."""

import sys
from datetime import datetime, timezone

from goldeye import config, data, engine, ml, news, sentiment, storage, telegram, tracker
from goldeye.factors import ALL_FACTORS, FactorContext, Vote  # noqa: F401 (Vote: test seam)
from goldeye.models import Direction

_FACTOR_NAMES = ["Trend", "Momentum", "MACD", "Volatility", "S/R", "Session", "Candles"]


def _log_activity(state, now, event, *, direction=None, score=None, detail=""):
    log = state.setdefault("activity_log", [])
    log.append({
        "ts": int(now.timestamp()),
        "time": f"{now:%d %b %H:%M} UTC",
        "event": event,
        "direction": direction,
        "score": score,
        "detail": detail,
    })
    state["activity_log"] = log[-20:]


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
            _log_activity(state, now, f"closed_{closed.status.value}",
                          direction=sig.direction.value,
                          detail=f"P/L {closed.pnl_usd:+.2f}" if closed.pnl_usd is not None else "")

    # 2. Look for a new signal
    if state.get("open_signal") is None:
        c15 = data.fetch_candles("15min", 350)
        c1h = data.fetch_candles("1h", 350)
        ctx = FactorContext.build(c15, c1h, now)

        # Always compute votes so the dashboard can show factor gauges
        votes = [f(ctx) for f in ALL_FACTORS]
        state["last_factor_votes"] = [
            {
                "name": _FACTOR_NAMES[i] if i < len(_FACTOR_NAMES) else f"F{i + 1}",
                "buy": v.buy,
                "sell": v.sell,
                "label": v.label,
            }
            for i, v in enumerate(votes)
        ]

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
                _log_activity(state, now, "skipped_calendar",
                              direction=sig.direction.value, score=sig.score,
                              detail=f"news: {block}")
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
                    _log_activity(state, now, "skipped_sentiment",
                                  direction=sig.direction.value, score=sig.score,
                                  detail=senti_block)
                else:
                    agrees = (senti.score > 0) == (sig.direction == Direction.BUY)
                    if senti.label != "neutral" and agrees:
                        sig.reasons.append(
                            f"news sentiment {senti.label} ({senti.score:+d})"
                        )
                    model = ml.load_model()
                    if model is not None:
                        conf = ml.confidence(model, votes, sig, ctx)
                        if conf < config.ML_MIN_CONFIDENCE:
                            state["last_no_signal"] = (
                                f"setup found but ML confidence too low "
                                f"({conf:.0%} < {config.ML_MIN_CONFIDENCE:.0%})"
                            )
                            _log_activity(state, now, "skipped_ml",
                                          direction=sig.direction.value, score=sig.score,
                                          detail=f"ML {conf:.0%}")
                            state["last_scan_ts"] = now_ts
                            storage.save_state(state)
                            return
                        sig.reasons.append(f"ML confidence {conf:.0%}")
                    storage.append_signal(sig)
                    state["open_signal"] = storage.signal_to_dict(sig)
                    telegram.send(telegram.format_signal(sig))
                    _log_activity(state, now, "signal",
                                  direction=sig.direction.value, score=sig.score,
                                  detail=f"Entry {sig.entry:.2f} SL {sig.sl:.2f} TP {sig.tp:.2f}")
        else:
            buy_votes = [v for v in votes if v.buy]
            sell_votes = [v for v in votes if v.sell]
            n_buy, n_sell = len(buy_votes), len(sell_votes)
            if max(n_buy, n_sell) >= config.GOLD_MIN_SCORE:
                state["last_no_signal"] = (
                    f"setup at {max(n_buy, n_sell)}/7 skipped — stop too "
                    "wide for the $100 account even at the minimum lot"
                )
                _log_activity(state, now, "wide_stop",
                              detail=f"{'BUY' if n_buy > n_sell else 'SELL'} {max(n_buy, n_sell)}/7 but stop too wide")
            else:
                buy_labels = ", ".join(v.label for v in buy_votes) or "none"
                sell_labels = ", ".join(v.label for v in sell_votes) or "none"
                state["last_no_signal"] = (
                    f"buy {n_buy}/7 ({buy_labels}) · "
                    f"sell {n_sell}/7 ({sell_labels}) — below threshold"
                )
                _log_activity(state, now, "no_setup",
                              detail=f"buy {n_buy}/7 · sell {n_sell}/7")

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

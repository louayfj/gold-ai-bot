"""Repo-resident state: data/state.json + data/signals.csv, atomic writes."""

import csv
import json
import os
import tempfile

from goldeye.config import SIGNALS_CSV, START_BALANCE, STATE_JSON
from goldeye.models import Direction, Signal, Status, Tier

CSV_COLUMNS = [
    "id", "timestamp", "tier", "direction", "entry", "sl", "tp", "lot",
    "risk_usd", "score", "votes", "news_flag", "status", "closed_at",
    "pnl_usd", "balance_after",
]
ERROR_CAP = 20


def _atomic_write(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path))
    with os.fdopen(fd, "w") as f:
        f.write(content)
    os.replace(tmp, path)


def load_state() -> dict:
    if not os.path.exists(STATE_JSON):
        return {
            "balance": START_BALANCE,
            "open_signal": None,
            "last_scan_ts": 0,
            "errors": [],
            "last_no_signal": "",
            "news_skips": [],
        }
    with open(STATE_JSON) as f:
        return json.load(f)


def save_state(state: dict) -> None:
    state["errors"] = state.get("errors", [])[-ERROR_CAP:]
    _atomic_write(STATE_JSON, json.dumps(state, indent=2))


def signal_to_dict(sig: Signal) -> dict:
    d = dict(sig.__dict__)
    d["tier"] = sig.tier.value
    d["direction"] = sig.direction.value
    d["status"] = sig.status.value
    return d


def signal_from_dict(d: dict) -> Signal:
    d = dict(d)
    d["tier"] = Tier(d["tier"])
    d["direction"] = Direction(d["direction"])
    d["status"] = Status(d["status"])
    return Signal(**d)


def _signal_to_row(sig: Signal) -> dict:
    return {
        "id": sig.id,
        "timestamp": sig.created_ts,
        "tier": sig.tier.value,
        "direction": sig.direction.value,
        "entry": sig.entry,
        "sl": sig.sl,
        "tp": sig.tp,
        "lot": sig.lot,
        "risk_usd": sig.risk_usd,
        "score": sig.score,
        "votes": "|".join(sig.reasons),
        "news_flag": int(sig.news_flag),
        "status": sig.status.value,
        "closed_at": sig.closed_ts if sig.closed_ts is not None else "",
        "pnl_usd": sig.pnl_usd if sig.pnl_usd is not None else "",
        "balance_after": sig.balance_after if sig.balance_after is not None else "",
    }


def read_signals() -> list[dict]:
    if not os.path.exists(SIGNALS_CSV):
        return []
    with open(SIGNALS_CSV, newline="") as f:
        return list(csv.DictReader(f))


def _write_rows(rows: list[dict]) -> None:
    import io

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_COLUMNS)
    writer.writeheader()
    writer.writerows(rows)
    _atomic_write(SIGNALS_CSV, buf.getvalue())


def append_signal(sig: Signal) -> None:
    rows = read_signals()
    rows.append(_signal_to_row(sig))
    _write_rows(rows)


def update_signal(sig: Signal) -> None:
    rows = read_signals()
    for i, row in enumerate(rows):
        if row["id"] == sig.id:
            rows[i] = _signal_to_row(sig)
            break
    _write_rows(rows)

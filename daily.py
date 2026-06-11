"""GoldEye daily heartbeat + performance report (08:00 Bangkok)."""

import sys
from datetime import datetime, timezone

from goldeye import config, storage, telegram
from goldeye.reports import daily_report


def main() -> int:
    try:
        config.load_secrets()
        state = storage.load_state()
        signals = storage.read_signals()
        text = daily_report(signals, state, datetime.now(timezone.utc))
        state["errors"] = []  # reported -> reset for the next 24h window
        storage.save_state(state)
        return 0 if telegram.send(text) else 1
    except Exception as exc:  # noqa: BLE001
        telegram.send_error(f"daily report failed: {exc}")
        print(exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

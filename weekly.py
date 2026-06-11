"""GoldEye weekly self-check (Sunday 19:00 Bangkok)."""

import sys

from goldeye import config, storage, telegram
from goldeye.reports import weekly_report


def main() -> int:
    try:
        config.load_secrets()
        text = weekly_report(storage.read_signals())
        return 0 if telegram.send(text) else 1
    except Exception as exc:  # noqa: BLE001
        telegram.send_error(f"weekly report failed: {exc}")
        print(exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""GoldEye scheduler — runs 24/7 on Fly.io.

Replaces GitHub Actions cron:
  - scan every 15 minutes
  - daily report at 01:00 UTC (08:00 Bangkok)
  - weekly self-check at 12:00 UTC every Sunday (19:00 Bangkok)

Also starts the web dashboard on port 8080 in a background thread.
"""
import logging
import threading
import time

import schedule

import daily
import scan
import weekly
from goldeye import web

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


def _run(name: str, fn) -> None:
    log.info("%s starting", name)
    try:
        rc = fn()
        log.info("%s done rc=%s", name, rc)
    except Exception as exc:  # noqa: BLE001
        log.error("%s crashed: %s", name, exc)


schedule.every(15).minutes.do(_run, "scan", scan.main)
schedule.every().day.at("01:00").do(_run, "daily", daily.main)   # 08:00 Bangkok
schedule.every().sunday.at("12:00").do(_run, "weekly", weekly.main)  # 19:00 Bangkok


if __name__ == "__main__":
    log.info("GoldEye scheduler starting — scan/15min, daily@01:00UTC, weekly@Sun 12:00UTC")

    # Dashboard in background — dies with the main process
    t = threading.Thread(
        target=lambda: web.app.run(host="0.0.0.0", port=8080),
        daemon=True,
        name="dashboard",
    )
    t.start()
    log.info("Dashboard started on port 8080")

    _run("scan", scan.main)  # run immediately on startup, don't wait 15 min
    while True:
        schedule.run_pending()
        time.sleep(10)

"""High-impact USD news filter using the ForexFactory weekly calendar feed."""

import time
from datetime import datetime, timedelta

import requests

from goldeye.config import NEWS_BUFFER_MIN

CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"


def fetch_calendar() -> tuple[list[dict], str | None]:
    """Returns (events, warning). On failure fails open: ([], warning)."""
    for attempt in range(2):
        try:
            resp = requests.get(CALENDAR_URL, timeout=15,
                                headers={"User-Agent": "goldeye-bot"})
            resp.raise_for_status()
            return resp.json(), None
        except Exception as exc:  # noqa: BLE001 - news is best-effort
            last = exc
            time.sleep(2**attempt)
    return [], f"news calendar unavailable ({last}); trading without news filter"


def news_block(now_utc: datetime, events: list[dict]) -> str | None:
    """Return the blocking event title if a high-impact USD event is within
    +/- NEWS_BUFFER_MIN minutes of now, else None."""
    buffer = timedelta(minutes=NEWS_BUFFER_MIN)
    for event in events:
        if event.get("country") != "USD" or event.get("impact") != "High":
            continue
        try:
            when = datetime.fromisoformat(event["date"])
        except (KeyError, ValueError):
            continue
        if abs(when - now_utc) <= buffer:
            return event.get("title", "high-impact USD news")
    return None

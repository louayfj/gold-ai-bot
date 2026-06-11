"""Market data: Twelve Data primary, Yahoo Finance gold futures fallback."""

import os
import time
from datetime import datetime, timezone

import requests

from goldeye.models import Candle


class DataError(Exception):
    pass


_TD_URL = "https://api.twelvedata.com/time_series"
_YAHOO_INTERVAL = {"15min": "15m", "1h": "1h", "5min": "5m"}
_YAHOO_PERIOD = {"15min": "5d", "1h": "1mo", "5min": "2d"}


def fetch_candles(interval: str, outputsize: int) -> list[Candle]:
    """Return candles oldest-first. Tries Twelve Data (3 attempts), then Yahoo."""
    errors = []
    for attempt in range(3):
        try:
            return _fetch_twelvedata(interval, outputsize)
        except Exception as exc:  # noqa: BLE001 - we degrade to fallback
            errors.append(f"twelvedata attempt {attempt + 1}: {exc}")
            time.sleep(2**attempt)
    try:
        return _fetch_yahoo(interval, outputsize)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"yahoo: {exc}")
    raise DataError("; ".join(errors))


def _fetch_twelvedata(interval: str, outputsize: int) -> list[Candle]:
    resp = requests.get(
        _TD_URL,
        params={
            "symbol": "XAU/USD",
            "interval": interval,
            "outputsize": outputsize,
            "timezone": "UTC",
            "apikey": os.environ["TWELVEDATA_API_KEY"],
        },
        timeout=20,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("status") != "ok" or "values" not in payload:
        raise RuntimeError(payload.get("message", "unexpected response"))
    candles = []
    for row in reversed(payload["values"]):  # newest-first -> oldest-first
        ts = int(
            datetime.strptime(row["datetime"], "%Y-%m-%d %H:%M:%S")
            .replace(tzinfo=timezone.utc)
            .timestamp()
        )
        candles.append(
            Candle(ts, float(row["open"]), float(row["high"]),
                   float(row["low"]), float(row["close"]))
        )
    return candles


def _fetch_yahoo(interval: str, outputsize: int) -> list[Candle]:
    import yfinance  # imported lazily: slow, and only needed as fallback

    hist = yfinance.Ticker("GC=F").history(
        period=_YAHOO_PERIOD[interval], interval=_YAHOO_INTERVAL[interval]
    )
    if hist.empty:
        raise RuntimeError("yahoo returned no data")
    candles = [
        Candle(int(idx.timestamp()), float(row["Open"]), float(row["High"]),
               float(row["Low"]), float(row["Close"]))
        for idx, row in hist.iterrows()
    ]
    return candles[-outputsize:]

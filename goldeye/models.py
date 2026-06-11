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
    ts: int  # unix seconds, candle open time, UTC
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
    news_flag: bool = False
    status: Status = Status.OPEN
    closed_ts: int | None = None
    pnl_usd: float | None = None
    balance_after: float | None = None

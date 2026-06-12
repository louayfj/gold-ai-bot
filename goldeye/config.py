import os

# Risk plan (locked with user)
START_BALANCE = 100.0
RISK_GOLD = 5.0       # $ risked per GOLD signal (5%)
RISK_SILVER = 2.5     # $ risked per SILVER signal

# Engine thresholds
GOLD_MIN_SCORE = 5    # 5-7 of 7 factors
SILVER_SCORE = 4

# Post-backtest tuning (2026-06-11, 49 days of 15m data):
# - SILVER lost money in every tested variant -> info-only until forward data
#   proves otherwise (flip to False to give silver real lot sizes again).
# - GOLD trades whose minimum-lot risk exceeds MAX_RISK_MULT * plan are skipped;
#   uncapped, the backtest drawdown ($246) would have blown the $100 account.
SILVER_INFO_ONLY = True
MAX_RISK_MULT = 2.0
RR = 1.5              # take-profit = RR * stop distance
SL_ATR_MULT = 1.5

# Contract math: 1.0 lot XAU/USD = 100 oz -> $100 P/L per $1.00 move
OZ_PER_LOT = 100
MIN_LOT = 0.01
LOT_STEP = 0.01

SIGNAL_TTL_H = 24
NEWS_BUFFER_MIN = 45
SENTIMENT_BLOCK_SCORE = 3   # skip signal if headlines score this hard against it
SENTIMENT_MAX_AGE_H = 12    # only headlines from the last N hours count
SESSION_UTC = (7, 21)  # London open .. New York close, hours UTC
TZ = "Asia/Bangkok"

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
SIGNALS_CSV = os.path.join(DATA_DIR, "signals.csv")
STATE_JSON = os.path.join(DATA_DIR, "state.json")

_SECRET_NAMES = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "TWELVEDATA_API_KEY")


def load_secrets(use_dotenv: bool = True) -> dict:
    if use_dotenv:
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass
    secrets = {}
    missing = []
    for name in _SECRET_NAMES:
        value = os.environ.get(name, "").strip()
        if not value:
            missing.append(name)
        secrets[name] = value
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")
    return secrets

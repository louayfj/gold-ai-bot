"""Gold news sentiment: free RSS headlines scored bullish/bearish for XAU.

Direction words are attributed to the nearest subject so that
"gold climbs as dollar weakens" counts both halves as gold-bullish.
Everything fails open: no headlines -> neutral -> no effect on signals.
"""

import re
from collections import namedtuple
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests
from defusedxml import ElementTree

from goldeye.config import SENTIMENT_BLOCK_SCORE, SENTIMENT_MAX_AGE_H
from goldeye.models import Direction

Sentiment = namedtuple("Sentiment", "score label n")

FEEDS = (
    "https://www.fxstreet.com/rss/news",
    "https://www.investing.com/rss/news_11.rss",  # commodities
    "https://feeds.content.dowjones.io/public/rss/mw_topstories",
)
MAX_HEADLINES = 40
LABEL_SCORE = 2  # |total| at or above this -> bullish/bearish label

# subject polarity: +1 means "this thing up = gold up"
# "dollar" only counts when it isn't some other country's dollar
_SUBJECTS = ((re.compile(r"\bgold\b|\bbullion\b|\bxau\b", re.I), 1),
             (re.compile(r"(?<!canadian )(?<!australian )(?<!zealand )"
                         r"(?<!taiwan )(?<!singapore )\bdollar\b"
                         r"|\bgreenback\b|\bdxy\b", re.I), -1))

_UP = re.compile(
    r"\b(surg\w*|rall(?:y|ies|ied)|climb\w*|jump\w*|soar\w*|ris(?:e|es|ing)|"
    r"rose|gain\w*|strengthen\w*|record high|all-time high)\b", re.I)
_DOWN = re.compile(
    r"\b(fall\w*|fell|drop\w*|slid(?:e|es)?|slip\w*|tumbl\w*|sink\w*|sank|"
    r"slump\w*|plung\w*|retreat\w*|weaken\w*)\b", re.I)

# events with a known gold direction, regardless of sentence structure
_EVENTS = (
    (re.compile(r"rate cut|dovish", re.I), 1),
    (re.compile(r"rate hike|hawkish|tightening", re.I), -1),
    (re.compile(r"\bwar\b|conflict|escalat\w*|geopolitical|tension", re.I), 1),
    (re.compile(r"peace|ceasefire|de.escalat\w*|truce|eas\w+ \S*.?tensions", re.I), -1),
    (re.compile(r"safe.haven", re.I), 1),
    (re.compile(r"strong jobs|jobs beat", re.I), -1),
)


def score_headline(title: str) -> int:
    subjects = [(m.start(), pol) for rx, pol in _SUBJECTS for m in rx.finditer(title)]
    score = 0
    if subjects:
        for rx, word_dir in ((_UP, 1), (_DOWN, -1)):
            for m in rx.finditer(title):
                _, pol = min(subjects, key=lambda s: abs(s[0] - m.start()))
                score += pol * word_dir
    for rx, points in _EVENTS:
        if rx.search(title):
            score += points
    return score


def analyze(headlines: list[str]) -> Sentiment:
    total = sum(score_headline(h) for h in headlines)
    if total >= LABEL_SCORE:
        label = "bullish"
    elif total <= -LABEL_SCORE:
        label = "bearish"
    else:
        label = "neutral"
    return Sentiment(total, label, len(headlines))


def _parse_rss(xml_text: str, now_utc: datetime) -> list[str]:
    cutoff = now_utc - timedelta(hours=SENTIMENT_MAX_AGE_H)
    titles = []
    for item in ElementTree.fromstring(xml_text).iter("item"):
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        pub = item.findtext("pubDate")
        if pub:
            try:
                when = parsedate_to_datetime(pub)
                if when.tzinfo is None:
                    when = when.replace(tzinfo=timezone.utc)
                if when < cutoff:
                    continue
            except (TypeError, ValueError):
                pass  # unparseable date -> keep the headline
        titles.append(title)
    return titles


def fetch_headlines() -> tuple[list[str], str | None]:
    """Returns (headlines, warning). Fails open: ([], warning)."""
    now = datetime.now(timezone.utc)
    headlines: list[str] = []
    failures = []
    for url in FEEDS:
        try:
            resp = requests.get(url, timeout=15,
                                headers={"User-Agent": "goldeye-bot"})
            resp.raise_for_status()
            headlines.extend(_parse_rss(resp.text, now))
        except Exception as exc:  # noqa: BLE001 - sentiment is best-effort
            failures.append(f"{url}: {type(exc).__name__}")
    seen = set()
    unique = [t for t in headlines if not (t in seen or seen.add(t))]
    warning = None
    if not unique:
        warning = "news sentiment unavailable (" + "; ".join(failures or ["no items"]) + ")"
    return unique[:MAX_HEADLINES], warning


def opposes(direction: Direction, senti: Sentiment) -> str | None:
    """Return a block reason if news strongly contradicts the trade, else None."""
    against = -senti.score if direction == Direction.BUY else senti.score
    if against >= SENTIMENT_BLOCK_SCORE:
        return (f"news sentiment strongly {senti.label} "
                f"({senti.score:+d} across {senti.n} headlines)")
    return None

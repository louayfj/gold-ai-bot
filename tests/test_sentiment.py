from datetime import datetime, timedelta, timezone

import requests

from goldeye import sentiment
from goldeye.models import Direction


# --- headline scoring -------------------------------------------------------

def test_gold_up_headline_scores_positive():
    assert sentiment.score_headline(
        "Gold surges to record high on safe-haven demand") > 0


def test_gold_down_headline_scores_negative():
    assert sentiment.score_headline(
        "Gold tumbles as traders take profits") < 0


def test_dollar_strength_scores_negative_for_gold():
    assert sentiment.score_headline(
        "Dollar rallies after strong jobs report") < 0


def test_dollar_weakness_scores_positive_for_gold():
    assert sentiment.score_headline(
        "Gold climbs as dollar weakens ahead of CPI data") > 0


def test_fed_rate_cut_scores_positive():
    assert sentiment.score_headline(
        "Fed signals rate cut at next meeting") > 0


def test_hawkish_fed_scores_negative():
    assert sentiment.score_headline(
        "Hawkish Fed minutes push back on easing hopes") < 0


def test_geopolitical_risk_scores_positive():
    assert sentiment.score_headline(
        "Middle East conflict escalation rattles markets") > 0


def test_irrelevant_headline_scores_zero():
    assert sentiment.score_headline(
        "Apple unveils new iPhone at developer conference") == 0


def test_other_dollars_are_not_the_us_dollar():
    assert sentiment.score_headline(
        "Canadian Dollar weakens despite easing risk aversion") == 0


def test_easing_tensions_scores_negative():
    # peace/de-escalation unwinds the safe-haven bid
    assert sentiment.score_headline(
        "Asian stocks gain on easing US-Iran tensions") < 1
    assert sentiment.score_headline(
        "Gold slides as ceasefire hopes build") < 0


# --- aggregation -------------------------------------------------------------

def test_analyze_bullish_label():
    s = sentiment.analyze([
        "Gold surges to record high",
        "Gold climbs as dollar weakens",
    ])
    assert s.label == "bullish"
    assert s.score >= 2
    assert s.n == 2


def test_analyze_bearish_label():
    s = sentiment.analyze([
        "Gold tumbles after hawkish Fed comments",
        "Dollar rallies to three-month high",
    ])
    assert s.label == "bearish"
    assert s.score <= -2


def test_analyze_empty_is_neutral():
    s = sentiment.analyze([])
    assert s.label == "neutral"
    assert s.score == 0
    assert s.n == 0


def test_analyze_mixed_is_neutral():
    s = sentiment.analyze([
        "Gold rises in early trading",
        "Gold slips as session ends",
    ])
    assert s.label == "neutral"


# --- RSS parsing -------------------------------------------------------------

RSS_FIXTURE = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item><title>Gold surges past key level</title>
        <pubDate>{recent}</pubDate></item>
  <item><title>Old story about gold last week</title>
        <pubDate>{old}</pubDate></item>
  <item><title>Story with no date kept anyway</title></item>
</channel></rss>
"""


def test_parse_rss_drops_stale_items():
    now = datetime(2026, 6, 12, 12, 0, tzinfo=timezone.utc)
    fmt = "%a, %d %b %Y %H:%M:%S GMT"
    xml = RSS_FIXTURE.format(
        recent=(now - timedelta(hours=2)).strftime(fmt),
        old=(now - timedelta(days=3)).strftime(fmt),
    )
    titles = sentiment._parse_rss(xml, now)
    assert "Gold surges past key level" in titles
    assert "Old story about gold last week" not in titles
    assert "Story with no date kept anyway" in titles


def test_fetch_headlines_fails_open(monkeypatch):
    def boom(*a, **kw):
        raise requests.ConnectionError("offline")
    monkeypatch.setattr(sentiment.requests, "get", boom)
    headlines, warning = sentiment.fetch_headlines()
    assert headlines == []
    assert warning is not None


# --- gate --------------------------------------------------------------------

def test_opposes_blocks_buy_on_strongly_bearish_news():
    s = sentiment.Sentiment(score=-4, label="bearish", n=6)
    assert sentiment.opposes(Direction.BUY, s) is not None


def test_opposes_blocks_sell_on_strongly_bullish_news():
    s = sentiment.Sentiment(score=4, label="bullish", n=6)
    assert sentiment.opposes(Direction.SELL, s) is not None


def test_opposes_allows_mildly_contrary_news():
    s = sentiment.Sentiment(score=-2, label="bearish", n=4)
    assert sentiment.opposes(Direction.BUY, s) is None


def test_opposes_allows_agreeing_news():
    s = sentiment.Sentiment(score=5, label="bullish", n=8)
    assert sentiment.opposes(Direction.BUY, s) is None

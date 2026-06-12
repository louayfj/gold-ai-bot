from datetime import datetime, timezone

from goldeye import ml
from goldeye.factors import Vote
from goldeye.models import Direction
from tests.test_storage import make_signal


class StubCtx:
    now_utc = datetime(2026, 6, 12, 9, 30, tzinfo=timezone.utc)  # Friday
    ema50_1h = 3350.0
    ema200_1h = 3330.0
    close_1h = 3355.0
    rsi15 = 47.0
    macd_hist = 0.8
    macd_hist_prev = 0.5
    atr15 = 4.0
    atr15_median = 5.0


VOTES = [Vote(True, False, "trend"), Vote(True, False, "momentum"),
         Vote(False, False, "macd"), Vote(True, True, "volatility"),
         Vote(False, True, "sr"), Vote(True, True, "session"),
         Vote(False, False, "candles")]


def test_features_encodes_votes_and_context():
    sig = make_signal()  # BUY, entry 3341.5, sl 3335.2, score 6
    x = ml.features(VOTES, sig, StubCtx())
    assert len(x) == len(ml.FEATURE_NAMES)
    f = dict(zip(ml.FEATURE_NAMES, x))
    assert f["vote_trend"] == 1          # buy
    assert f["vote_macd"] == 0           # abstain
    assert f["vote_sr"] == -1            # sell
    assert f["vote_volatility"] == 0     # votes both ways -> no direction
    assert f["score"] == 6
    assert f["direction"] == 1           # BUY
    assert f["hour_utc"] == 9
    assert f["weekday"] == 4             # Friday
    assert f["atr_regime"] == 0.8        # 4.0 / 5.0
    assert f["rsi"] == 47.0
    assert f["trend_strength"] == 5.0    # (3350-3330)/4.0
    assert abs(f["sl_dist"] - 6.3) < 1e-9


def test_predict_single_tree():
    # one split on rsi (index of "rsi" feature): rsi < 50 -> 0.7, else 0.2
    i = ml.FEATURE_NAMES.index("rsi")
    model = {"trees": [{"f": i, "t": 50.0,
                        "l": {"p": 0.7}, "r": {"p": 0.2}}]}
    x = [0.0] * len(ml.FEATURE_NAMES)
    x[i] = 47.0
    assert ml.predict(model, x) == 0.7
    x[i] = 60.0
    assert ml.predict(model, x) == 0.2


def test_predict_averages_trees():
    model = {"trees": [{"p": 0.6}, {"p": 0.8}]}  # degenerate leaf-only trees
    assert abs(ml.predict(model, [0.0] * len(ml.FEATURE_NAMES)) - 0.7) < 1e-9


def test_load_model_returns_none_when_missing(tmp_path):
    assert ml.load_model(str(tmp_path / "nope.json")) is None


def test_confidence_end_to_end(tmp_path):
    import json
    i = ml.FEATURE_NAMES.index("score")
    model = {"trees": [{"f": i, "t": 5.5, "l": {"p": 0.4}, "r": {"p": 0.9}}]}
    path = tmp_path / "model.json"
    path.write_text(json.dumps(model))
    loaded = ml.load_model(str(path))
    sig = make_signal()  # score 6 -> right branch
    assert ml.confidence(loaded, VOTES, sig, StubCtx()) == 0.9

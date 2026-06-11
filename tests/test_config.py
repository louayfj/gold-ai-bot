import pytest

from goldeye import config


def test_load_secrets_raises_on_missing(monkeypatch):
    for name in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "TWELVEDATA_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(config, "load_secrets", config.load_secrets)
    monkeypatch.chdir("/tmp")  # avoid picking up a local .env
    with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN"):
        config.load_secrets()


def test_load_secrets_reads_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "c")
    monkeypatch.setenv("TWELVEDATA_API_KEY", "k")
    secrets = config.load_secrets()
    assert secrets["TELEGRAM_CHAT_ID"] == "c"


def test_risk_constants_match_plan():
    assert config.RISK_GOLD == 5.0
    assert config.RISK_SILVER == 2.5
    assert config.GOLD_MIN_SCORE == 5
    assert config.RR == 1.5

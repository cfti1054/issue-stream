from datetime import date, datetime

import pytest

from issue_stream.core.config import PaidApiDisabledError, Settings
from issue_stream.core.market_calendar import KST, is_market_open, is_trading_day


def test_paid_provider_blocked_by_default():
    s = Settings(_env_file=None, summarizer_provider="anthropic")
    with pytest.raises(PaidApiDisabledError):
        s.require_paid("SUMMARIZER_PROVIDER", s.summarizer_provider)


def test_paid_provider_allowed_when_opted_in():
    s = Settings(_env_file=None, summarizer_provider="anthropic", allow_paid_apis=True)
    s.require_paid("SUMMARIZER_PROVIDER", s.summarizer_provider)  # 예외 없음


def test_free_providers_never_blocked():
    s = Settings(_env_file=None)
    for comp, p in (("E", s.embedding_provider), ("S", s.summarizer_provider)):
        s.require_paid(comp, p)


def test_weekend_is_closed():
    assert not is_trading_day(date(2026, 10, 3))            # 토요일(개천절)
    assert not is_market_open(datetime(2026, 10, 3, 10, 0, tzinfo=KST))


def test_weekday_session_hours():
    d = datetime(2026, 9, 29, 10, 0, tzinfo=KST)            # 화요일
    assert is_market_open(d)
    assert not is_market_open(d.replace(hour=16))


def test_empty_cluster_threshold_in_env_uses_provider_default(monkeypatch):
    # .env.example 은 CLUSTER_SIM_THRESHOLD= (빈 값) 으로 배포된다
    monkeypatch.setenv("CLUSTER_SIM_THRESHOLD", "")
    s = Settings(_env_file=None)
    assert s.cluster_sim_threshold is None
    assert s.effective_cluster_threshold() == 0.35


def test_railway_postgres_url_uses_psycopg3():
    from issue_stream.core.config import Settings
    for raw in ("postgresql://u:p@h:5432/db", "postgres://u:p@h:5432/db"):
        assert Settings(database_url=raw).database_url == "postgresql+psycopg://u:p@h:5432/db"
    assert Settings(database_url="postgresql+psycopg://u:p@h/db").database_url == "postgresql+psycopg://u:p@h/db"

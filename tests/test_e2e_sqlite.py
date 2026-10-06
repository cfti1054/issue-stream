"""SQLite 로 전체 흐름 점검: 스키마 → 데모 데이터(수집·중복제거·클러스터링·요약) → API → 보존 작업.

Docker·Postgres·API 키 없이 무료 기본 구성이 끝까지 동작하는지 확인한다.
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    import os

    db = tmp_path_factory.mktemp("db") / "t.db"
    old = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = f"sqlite:///{db.as_posix()}"
    from issue_stream.core.config import get_settings
    from issue_stream.db.session import reset_engine
    get_settings.cache_clear()
    reset_engine()

    from issue_stream.cli import migrate
    from issue_stream import demo
    migrate()
    demo.seed()
    from issue_stream.api.main import app
    with TestClient(app) as c:
        yield c

    reset_engine()
    if old is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = old
    get_settings.cache_clear()


def test_dashboard_payload(client):
    d = client.get("/dashboard").json()
    assert d["demo"] is True
    assert len(d["indices"]) == 5 and all(len(i["spark"]) > 10 for i in d["indices"])
    assert d["brief"]["issue_count"] >= 6
    w = {x["code"]: x for x in d["watchlist"]}
    assert w["005930"]["sentiment"]["total"] >= 4           # 종목별 기사 검색 (ticker_keys LIKE)
    assert w["005930"]["top_issue"] is not None
    assert d["watchlist"][0]["holding"] is True              # 보유종목이 맨 위
    assert d["sectors"]["basis"] == "etf" and len(d["sectors"]["items"]) >= 10


def test_issues_clustered_and_tz_aware(client):
    issues = client.get("/issues?limit=40").json()
    top = issues[0]
    assert top["article_count"] >= 5 and top["has_disclosure"]          # 뉴스+공시가 한 이슈로
    assert sum(top["coverage"]) >= 1 and len(top["coverage"]) == 24
    assert any(a["cited"] for a in top["articles"])
    datetime.fromisoformat(top["last_seen"])                             # 시간대 포함 ISO
    assert client.get("/issues?ticker=005930").json()[0]["tickers"][0]["code"] == "005930"


def test_prices_and_health(client):
    p = client.get("/market/prices/USD/KRW?days=10").json()
    assert len(p["points"]) == 10
    h = client.get("/health").json()
    assert h["ok"] and h["providers"]["paid_allowed"] is False


def test_ingest_is_idempotent_and_retention_runs(client):
    from issue_stream.core.schemas import RawDoc
    from issue_stream.db.session import session_scope
    from issue_stream.jobs.tasks import job_retention
    from issue_stream.pipeline.run import cluster_pending, collect_and_ingest, enrich_issues
    now = datetime.now(timezone.utc)
    doc = RawDoc(source="test", external_id="x1", title="SK하이닉스 신규 공장 착공", url="https://e/x1",
                 publisher="테스트", published_at=now - timedelta(minutes=3))
    with session_scope() as db:
        assert collect_and_ingest(db, docs=[doc]) == 1
    with session_scope() as db:
        assert collect_and_ingest(db, docs=[doc]) == 0
    with session_scope() as db:
        assert cluster_pending(db) == 1
    with session_scope() as db:
        enrich_issues(db)
    job_retention()
    assert client.get("/health").json()["jobs"]["job_retention"]["status"] == "ok"


def test_all_news_sources_failing_is_reported(client, monkeypatch):
    import issue_stream.pipeline.run as run
    from issue_stream.collectors.base import Collector
    from issue_stream.jobs.tasks import job_news_pipeline

    class Broken(Collector):
        name = "broken"

        def fetch(self, since):
            raise RuntimeError("403 Forbidden")
    monkeypatch.setattr(run, "enabled_collectors", lambda: [Broken()])
    job_news_pipeline()
    st = client.get("/dashboard").json()["collection"]
    assert st["first_run"] is False
    assert any(p["job"] == "job_news_pipeline" and "모든 뉴스 소스" in p["message"] for p in st["problems"])

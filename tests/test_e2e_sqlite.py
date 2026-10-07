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


@pytest.fixture(scope="module")
def auth(client):
    """watchlist.yaml 종목으로 시작하는 계정 하나로 로그인한 헤더."""
    from issue_stream import accounts
    accounts.create_user("MeUser", "password123", "나")
    r = client.post("/auth/login", json={"username": "meuser", "password": "password123"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_dashboard_payload(client, auth):
    assert client.get("/dashboard").json()["watchlist"] == []           # 로그인 전에는 관심종목 없음
    d = client.get("/dashboard", headers=auth).json()
    assert d["user"]["username"] == "meuser"
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


def test_login_rejects_bad_credentials(client, auth):
    assert client.post("/auth/login", json={"username": "meuser", "password": "wrong-pass"}).status_code == 401
    assert client.post("/auth/login", json={"username": "nobody", "password": "password123"}).status_code == 401
    assert client.get("/auth/me").status_code == 401
    assert client.get("/me/watchlist", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get("/auth/me", headers=auth).json()["name"] == "나"


def test_watchlist_is_per_account(client, auth, monkeypatch):
    from sqlalchemy import select

    from issue_stream import accounts
    from issue_stream.db.models import Ticker
    from issue_stream.db.session import session_scope
    from issue_stream.jobs import tasks
    backfilled = []
    monkeypatch.setattr(tasks, "job_backfill_ticker", lambda code: backfilled.append(code))

    accounts.create_user("other_1", "password456", default_watchlist=False)
    tok = client.post("/auth/login", json={"username": "other_1", "password": "password456"}).json()["token"]
    other = {"Authorization": f"Bearer {tok}"}
    assert client.get("/me/watchlist", headers=other).json() == []

    # 검색 → ☆ 등록. yaml 에 없던 종목은 수집 대상이 되고 과거 시세를 채운다
    found = client.get("/tickers/search?q=NAV", headers=other).json()
    assert found[0]["code"] == "035420" and found[0]["watched"] is False
    assert client.put("/me/watchlist/035420", headers=other, json={"holding": True}).status_code == 200
    assert backfilled == ["035420"]
    assert client.put("/me/watchlist/999999", headers=other).status_code == 404
    mine = client.get("/me/watchlist", headers=other).json()
    assert [(w["code"], w["holding"]) for w in mine] == [("035420", True)]
    assert client.get("/tickers/search?q=035420", headers=other).json()[0]["watched"] is True
    client.put("/me/watchlist/035420", headers=other)                   # 본문 없이 다시 ☆ → 보유 유지
    assert client.get("/me/watchlist", headers=other).json()[0]["holding"] is True
    with session_scope() as db:
        assert db.scalar(select(Ticker.in_watchlist).where(Ticker.code == "035420")) is True

    # 다른 계정의 관심종목에는 영향 없음
    codes = {w["code"] for w in client.get("/me/watchlist", headers=auth).json()}
    assert "035420" not in codes and "005930" in codes

    # ★ 해제하면 아무도 보지 않는 종목은 수집 대상에서 빠진다. yaml 종목은 계속 수집
    assert client.delete("/me/watchlist/035420", headers=other).status_code == 204
    client.delete("/me/watchlist/005930", headers=auth)
    with session_scope() as db:
        assert db.scalar(select(Ticker.in_watchlist).where(Ticker.code == "035420")) is False
        assert db.scalar(select(Ticker.in_watchlist).where(Ticker.code == "005930")) is True
    client.put("/me/watchlist/005930", headers=auth, json={"holding": True})

    # 로그아웃하면 토큰은 더 이상 쓸 수 없다
    assert client.post("/auth/logout", headers=other).status_code == 204
    assert client.get("/auth/me", headers=other).status_code == 401


def test_entities_have_internal_id_and_display_no(client, auth):
    from sqlalchemy import func, select, text

    from issue_stream.db.models import Article, Issue, JobRun, User
    from issue_stream.db.session import session_scope
    with session_scope() as db:
        for m in (Article, Issue, JobRun, User):                       # 트리거가 no 를 빠짐없이 채운다
            assert db.scalar(select(func.count()).select_from(m).where(m.no.is_(None))) == 0
            assert db.scalar(select(func.count(m.no.distinct()))) == db.scalar(select(func.count()).select_from(m))
        db.execute(text("INSERT INTO job_runs (job, started_at, status, items) VALUES ('raw', '2026-01-01', 'ok', 0)"))
        raw = db.scalar(select(JobRun).where(JobRun.job == "raw"))
        assert raw.no == db.scalar(select(func.max(JobRun.no)))        # SQL 로 직접 넣어도 번호가 매겨진다
        db.add(u := JobRun(job="orm", started_at=raw.started_at, status="ok"))
        db.flush()
        assert u.no == raw.no + 1                                       # ORM INSERT 후에도 no 를 읽어 온다

    card = client.get("/issues?limit=1").json()[0]
    assert "id" not in card and "no" in card["articles"][0]             # 응답에는 화면용 번호만
    assert client.get(f"/issues/{card['no']}").json()["no"] == card["no"]
    assert client.get("/issues/999999").status_code == 404
    assert "no" in client.get("/auth/me", headers=auth).json()
    bullet = client.get("/dashboard").json()["brief"]["bullets"][0]
    assert "issue_no" in bullet


def test_signup_logs_in_and_respects_settings(client, monkeypatch):
    from issue_stream.core.config import get_settings
    st = get_settings()
    cfg = client.get("/auth/config").json()
    assert cfg["signup"] is True and cfg["invite_required"] is False

    r = client.post("/auth/signup", json={"username": "NewUser", "password": "password789", "name": "새 계정"})
    assert r.status_code == 201
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    assert client.get("/auth/me", headers=h).json()["username"] == "newuser"
    assert {w["code"] for w in client.get("/me/watchlist", headers=h).json()} >= {"005930"}   # yaml 로 시작

    assert client.post("/auth/signup", json={"username": "newuser", "password": "password789"}).status_code == 409
    assert client.post("/auth/signup", json={"username": "xuser", "password": "short"}).status_code == 400
    for bad in ("abc", "1user", "has space", "a" * 21, "me@example.com", "한글아이디"):   # 아이디 규칙
        assert client.post("/auth/signup", json={"username": bad, "password": "password789"}).status_code == 400, bad

    monkeypatch.setattr(st, "signup_invite_code", "abc123")
    assert client.get("/auth/config").json()["invite_required"] is True
    body = {"username": "invited", "password": "password789"}
    assert client.post("/auth/signup", json={**body, "invite_code": "wrong"}).status_code == 403
    assert client.post("/auth/signup", json={**body, "invite_code": "abc123"}).status_code == 201

    monkeypatch.setattr(st, "signup_enabled", False)
    assert client.post("/auth/signup", json={"username": "closed", "password": "password789",
                                             "invite_code": "abc123"}).status_code == 403

    # 관심종목 상한
    monkeypatch.setattr(st, "max_watchlist_per_user", len(client.get("/me/watchlist", headers=h).json()))
    r = client.put("/me/watchlist/035720", headers=h)
    assert r.status_code == 400 and "까지" in r.json()["detail"]
    assert client.put("/me/watchlist/005930", headers=h).status_code == 200   # 이미 있는 종목은 상한과 무관

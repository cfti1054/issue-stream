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
    issues = client.get("/issues?page_size=50").json()["items"]
    top = issues[0]
    assert top["article_count"] >= 5 and top["has_disclosure"]          # 뉴스+공시가 한 이슈로
    assert sum(top["coverage"]) >= 1 and len(top["coverage"]) == 24
    assert any(a["cited"] for a in top["articles"])
    datetime.fromisoformat(top["last_seen"])                             # 시간대 포함 ISO
    assert client.get("/issues?ticker=005930").json()["items"][0]["tickers"][0]["code"] == "005930"


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

    card = client.get("/issues?page_size=1").json()["items"][0]
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


def test_us_stocks_watchlist_sectors_and_tagging(client, auth, monkeypatch):
    from issue_stream.db.models import Ticker
    from issue_stream.db.ops import upsert
    from issue_stream.db.session import session_scope
    from issue_stream.jobs import tasks
    from issue_stream.pipeline.run import build_tagger
    monkeypatch.setattr(tasks, "job_backfill_ticker", lambda code: None)
    with session_scope() as db:
        upsert(db, Ticker, dict(code="NVDA", name="엔비디아", market="NASDAQ", quote_code="NVDA.O"), ["code"])
    with session_scope() as db:
        assert "NVDA" not in build_tagger(db).tag("엔비디아 신고가")          # 아무도 안 보는 미국 종목은 태깅 안 함

    hit = client.get("/tickers/search?q=엔비", headers=auth).json()[0]
    assert hit["code"] == "NVDA" and hit["market"] == "NASDAQ"
    assert client.put("/me/watchlist/NVDA", headers=auth).status_code == 200
    wl = {w["code"]: w for w in client.get("/me/watchlist", headers=auth).json()}
    assert wl["NVDA"]["region"] == "us" and wl["005930"]["region"] == "kr"
    assert tasks._watchlist_codes(region="us") == [("NVDA", "NASDAQ", "NVDA.O")]
    assert all(m != "NASDAQ" for _, m, _ in tasks._watchlist_codes(region="kr"))
    with session_scope() as db:
        assert build_tagger(db).tag("엔비디아·NVDA 신고가") == {"NVDA": 2}   # 관심종목이 되면 한글 이름·티커로 태깅

    d = client.get("/dashboard", headers=auth).json()
    assert d["sectors"]["basis"] == "etf" and all(i["market"] == "ETF" for i in d["sectors"]["items"])
    assert d["sectors_us"]["basis"] == "us_etf" and len(d["sectors_us"]["items"]) >= 10
    assert isinstance(d["us_market_open"], bool)
    assert client.get("/market/sectors?region=us").json()["items"][0]["market"] == "US"
    client.delete("/me/watchlist/NVDA", headers=auth)


def test_us_market_news_is_separated(client):
    d = client.get("/dashboard").json()
    assert d["brief"]["region"] == "kr" and d["brief_us"]["region"] == "us"
    assert d["brief_us"]["issue_count"] >= 2 and "S&P 500" in d["brief_us"]["headline"]
    us = d["issues_us"]
    assert us and all(i["region"] == "us" for i in us)
    assert all(i["region"] == "kr" for i in d["issues"])
    heads = " ".join(i["summary"]["headline"] for i in us)
    assert "나스닥" in heads or "Nasdaq" in heads
    assert all(i["region"] == "us" for i in client.get("/issues?region=us").json()["items"])
    assert all(i["region"] == "kr" for i in client.get("/issues?region=kr").json()["items"])
    assert client.get("/issues").json()["total"] >= len(us) + len(d["issues"])   # 생략하면 전부


def test_issue_list_sort_search_and_pages(client):
    imp = client.get("/issues?page_size=50").json()["items"]
    assert [i["importance"] for i in imp] == sorted((i["importance"] for i in imp), reverse=True)
    rec = client.get("/issues?page_size=50&sort=recent").json()["items"]
    assert [i["last_seen"] for i in rec] == sorted((i["last_seen"] for i in rec), reverse=True)

    p1 = client.get("/issues?page_size=3&page=1").json()
    p2 = client.get("/issues?page_size=3&page=2").json()
    assert p1["total"] >= 6 and p1["pages"] == -(-p1["total"] // 3) and len(p1["items"]) == 3
    assert {i["no"] for i in p1["items"]}.isdisjoint(i["no"] for i in p2["items"])
    assert client.get("/issues?page_size=3&page=999").json()["items"] == []

    by_name = client.get("/issues?q=삼성전자&qt=ticker").json()["items"]          # 종목명
    assert by_name and all(any(t["code"] == "005930" for t in i["tickers"]) for i in by_name)
    assert client.get("/issues?q=005930&qt=ticker").json()["total"] == len(by_name)   # 종목코드
    by_text = client.get("/issues?q=기준금리&qt=text").json()["items"]            # 기사 내용
    assert by_text and any("금리" in i["summary"]["headline"] for i in by_text)
    assert client.get("/issues?q=기준금리&qt=ticker").json()["total"] == 0
    assert client.get("/issues?q=100%25&qt=text").json()["total"] == 0              # % 는 글자 그대로
    assert client.get("/dashboard?sort=recent").json()["issues"][0]["last_seen"] >=         client.get("/dashboard").json()["issues"][-1]["last_seen"]


def test_retag_applies_current_dictionary(client):
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from issue_stream.db.models import Article
    from issue_stream.db.session import session_scope
    from issue_stream.pipeline.run import retag_articles
    with session_scope() as db:
        a = db.scalar(select(Article).where(Article.title.like("%카카오 공동체%")))
        a.tickers, a.ticker_keys = [], ""                                      # 예전 사전으로 놓친 상태
    with session_scope() as db:
        n_art, _ = retag_articles(db, datetime.now(timezone.utc) - timedelta(days=2))
    assert n_art >= 1
    with session_scope() as db:
        a = db.scalar(select(Article).where(Article.title.like("%카카오 공동체%")))
        assert a.tickers == ["035720"] and a.ticker_keys == ",035720,"
    with session_scope() as db:
        assert retag_articles(db, datetime.now(timezone.utc) - timedelta(days=2))[0] == 0   # 두 번째는 변화 없음


def test_signals(client, auth):
    d = client.get("/signals?region=kr&hours=72").json()
    rows = d["items"]
    assert rows and d["mine"] == []                                  # 로그인 전에는 내 관심 시그널 없음
    r = next(x for x in rows if x["main"]["code"] == "005930")
    assert r["category"] == "실적" and r["keywords"] and r["reason"]
    assert r["main"]["change_pct"] is not None and r["publisher_count"] >= 3
    assert any(x["main"]["is_index"] for x in rows)                 # 종목 없는 이슈(금리)는 코스피로
    m = client.get("/signals?region=kr&hours=72", headers=auth).json()
    assert any(x["main"]["code"] == "005930" for x in m["mine"])     # 관심종목 이슈는 mine 으로
    assert all(x["main"]["code"] != "005930" for x in m["items"])


def test_chart_fetches_prices_for_any_ticker(client, monkeypatch):
    """관심종목이 아닌 종목도 차트를 열면 그 자리에서 시세를 받아 보여 준다 (두 번째부터는 저장분)."""
    from datetime import date, timedelta

    from issue_stream.collectors import quotes
    calls = []

    def fake_chain(chain, n, *a, **k):
        calls.append((chain[0], n))
        days = [date.today() - timedelta(days=i) for i in range(n)][::-1]
        return [{"day": d, "open": None, "high": None, "low": None, "close": 100.0 + i, "volume": None}
                for i, d in enumerate(days)], chain[0], []
    monkeypatch.setattr(quotes, "fetch_chain", fake_chain)
    monkeypatch.setattr("issue_stream.api.main.is_market_open", lambda: False)
    monkeypatch.setattr("issue_stream.api.main.is_us_market_open", lambda: False)

    p = client.get("/market/prices/035720?days=120").json()            # 카카오: 수집 대상 아님
    assert len(p["points"]) == 120 and calls and calls[0][1] == 131    # 과거 130일을 한 번에
    n = len(calls)
    assert len(client.get("/market/prices/035720?days=120").json()["points"]) == 120
    assert len(calls) == n                                               # 저장분이 충분하면 다시 받지 않음


def test_single_issue(client):
    no = client.get("/issues?page_size=1").json()["items"][0]["no"]
    one = client.get(f"/issues/{no}").json()
    assert one["no"] == no and one["articles"]
    assert client.get("/issues/999999").status_code == 404


def test_fx_board_with_commodities(client):
    """환율·원자재: 원자재 카드와 국내 금 프리미엄 (국제 금 × 원/달러 ÷ 31.1g)."""
    from datetime import date

    from issue_stream.db.models import Price
    from issue_stream.db.ops import upsert
    from issue_stream.db.session import session_scope
    with session_scope() as db:
        for sym, close in (("CMDT:GOLD_KRX", 180_000.0), ("CMDT:GOLD", 4000.0), ("CMDT:WTI", 90.0)):
            upsert(db, Price, dict(symbol=sym, day=date.today(), close=close, source="test"), ["symbol", "day"])
    d = client.get("/market/fx").json()
    names = {c["symbol"]: c for c in d["commodities"]}
    assert names["CMDT:GOLD_KRX"]["unit_label"] == "원/g" and names["CMDT:WTI"]["unit_label"] == "$/배럴"
    g = d["gold"]
    assert abs(g["intl_krw_per_g"] - 4000 * g["usdkrw"] / 31.1034768) < 0.1
    assert (g["premium_pct"] > 0) == (180_000 > g["intl_krw_per_g"])


def test_prices_in_krw(client):
    """원화 토글: 달러 표시 항목은 그날 원/달러를 곱하고, 금은 원/g 으로. 원화 항목은 그대로."""
    from datetime import date, timedelta

    from issue_stream.db.models import Price
    from issue_stream.db.ops import upsert
    from issue_stream.db.session import session_scope
    d0 = date.today() - timedelta(days=1)
    with session_scope() as db:
        for day, close in ((d0, 100.0), (date.today(), 110.0)):
            upsert(db, Price, dict(symbol="CMDT:WTI", day=day, close=close, source="test"), ["symbol", "day"])
            upsert(db, Price, dict(symbol="CMDT:GOLD", day=day, close=3110.34768, source="test"), ["symbol", "day"])
            upsert(db, Price, dict(symbol="USD/KRW", day=day, close=1000.0 if day == d0 else 1100.0, source="test"),
                   ["symbol", "day"])
    usd = client.get("/market/prices/CMDT:WTI?days=2").json()
    assert usd["convertible"] and usd["currency"] == "USD" and usd["unit"] == "$/배럴"
    krw = client.get("/market/prices/CMDT:WTI?days=2&krw=true").json()
    assert krw["currency"] == "KRW" and krw["unit"] == "원/배럴"
    assert [p["close"] for p in krw["points"]] == [100_000.0, 121_000.0]     # 날짜별 환율 적용
    assert krw["points"][-1]["change_pct"] == 21.0                             # 원화 기준 등락률
    gold = client.get("/market/prices/CMDT:GOLD?days=1&krw=true").json()
    assert gold["unit"] == "원/g" and abs(gold["points"][-1]["close"] - 110_000) < 1   # 100온스 → g
    won = client.get("/market/prices/USD/KRW?days=2&krw=true").json()
    assert won["convertible"] is False and won["currency"] is None


def test_coins_board(client, monkeypatch):
    """코인: 시장 요약·김치 프리미엄·순위(거래대금 상위 100 안에서 상승·하락)·달러 보기."""
    from datetime import date, timedelta

    from issue_stream.collectors import crypto
    from issue_stream.db.models import Price
    from issue_stream.db.ops import upsert
    from issue_stream.db.session import session_scope
    crypto._cache.clear()
    names = {"KRW-BTC": "비트코인", "KRW-ETH": "이더리움", "KRW-XRP": "리플", "KRW-SOL": "솔라나",
             "KRW-DOGE": "도지코인", "KRW-ADA": "에이다", "KRW-TINY": "잡코인"}
    live = [{"market": m, "code": m[4:], "price": p, "change": 0.0, "change_pct": c, "volume_krw": v}
            for m, p, c, v in (("KRW-BTC", 110_000_000, -0.5, 1.3e11), ("KRW-ETH", 3_500_000, 1.0, 1.0e11),
                               ("KRW-XRP", 1900, -1.0, 2.1e11), ("KRW-SOL", 150_000, 2.0, 5e10),
                               ("KRW-DOGE", 120, -3.0, 4e10), ("KRW-ADA", 345, 0.5, 3e10), ("KRW-TINY", 5, 90.0, 1e6))]
    monkeypatch.setattr(crypto, "krw_markets", lambda: names)
    monkeypatch.setattr(crypto, "tickers", lambda markets: live)
    monkeypatch.setattr(crypto, "global_usd", lambda coins: {"BTC": 80_000.0, "ETH": 2500.0})
    monkeypatch.setattr(crypto, "market_overview", lambda: {"market_cap_usd": 2.8e12, "btc_dominance": 58.8,
                                                            "eth_dominance": 9.4, "market_cap_change_pct": 1.2})
    monkeypatch.setattr(crypto, "fear_greed", lambda: {"value": 64, "label": "탐욕", "prev": 71})
    d1 = date.today() - timedelta(days=1)
    with session_scope() as db:
        for day, btc, fx in ((d1, 100_000_000.0, 1000.0), (date.today(), 110_000_000.0, 1100.0)):
            upsert(db, Price, dict(symbol="COIN:BTC", day=day, close=btc, source="test"), ["symbol", "day"])
            upsert(db, Price, dict(symbol="USD/KRW", day=day, close=fx, source="test"), ["symbol", "day"])

    d = client.get("/market/coins").json()
    s = d["summary"]
    assert s["btc_dominance"] == 58.8 and s["fear_greed"]["value"] == 64 and s["markets"] == 7
    assert s["market_cap_krw"] == 2.8e12 * 1100
    assert s["kimchi"]["code"] == "BTC" and s["kimchi"]["premium_pct"] == 25.0      # 1.1억 vs 8만$×1100
    assert [c["code"] for c in d["coins"]][:2] == ["BTC", "ETH"] and d["coins"][0]["price"] == 110_000_000
    assert [p["code"] for p in d["premium"]] == ["BTC", "ETH"]                         # 해외 시세 있는 코인만
    assert d["ranking"]["value"][0]["name"] == "리플"
    assert d["ranking"]["up"][0]["code"] == "TINY"                                     # 7종목뿐이라 상위 100 안
    assert d["ranking"]["down"][0]["code"] == "DOGE"
    usd = client.get("/market/prices/COIN:BTC?days=2&usd=true").json()
    assert usd["currency"] == "USD" and usd["name"] == "비트코인"
    assert [p["close"] for p in usd["points"]] == [100_000.0, 100_000.0]               # 날짜별 환율로 나눔
    crypto._cache.clear()

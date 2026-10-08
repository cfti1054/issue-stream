"""대시보드용 REST API. 프론트는 계산하지 않고 여기서 받은 값을 그리기만 한다.

실행: issue-stream api   (또는 uvicorn issue_stream.api.main:app --reload)
문서: http://localhost:8000/docs

화면별 엔드포인트
  마켓 대시보드  GET /dashboard                  한 번에 필요한 값 전부
                 GET /market/prices/{symbol}      선택 종목 가격 차트
  이슈 브리핑    GET /issues                      이슈 카드 (근거 기사·보도량 추이 포함)
                 GET /issues/{no}                 이슈 상세 (확산 타임라인)
  로그인·가입    POST /auth/login, /auth/signup, /auth/logout, GET /auth/me, /auth/config   (api/auth.py)
  관심종목       GET /me/watchlist, PUT·DELETE /me/watchlist/{code}, GET /tickers/search
  번호           이슈·기사·계정은 화면용 번호 no 로 내보낸다. 내부 PK id 는 FK 전용 (db/sequences.py)
                 관심종목은 계정별. 로그인하지 않으면 /dashboard 의 watchlist 는 빈 목록이다.
"""
from __future__ import annotations

import os
from collections import Counter
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import delete, desc, func, or_, select
from sqlalchemy.orm import Session

from ..core.config import get_settings, load_yaml
from ..core.market_calendar import is_market_open, is_us_market, is_us_market_open
from ..db.models import (
    ApiUsage, Article, Issue, IssueArticle, IssueSummaryRow, IssueTicker, JobRun, MacroSeries, Price,
    SectorIndex, Ticker, User, UserWatchlist,
)
from ..pipeline.briefing import build_market_brief
from .auth import current_user, db, optional_user, user_json
from .auth import router as auth_router

@asynccontextmanager
async def lifespan(_app: FastAPI):
    """`issue-stream serve` 로 띄우면 수집 스케줄러를 같은 프로세스에서 함께 돌린다."""
    sch = None
    if os.environ.get("ISSUE_STREAM_SCHEDULER") == "1":
        from ..jobs.scheduler import start_background
        sch = start_background()
    yield
    if sch:
        sch.shutdown(wait=False)


app = FastAPI(title="issue-stream API", version="0.2.0", lifespan=lifespan)
# 브라우저에서 직접 호출할 경우 대비 (웹은 기본적으로 서버에서 호출하므로 필수는 아님)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"], allow_methods=["GET"],
                   allow_headers=["*"])
app.include_router(auth_router)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── 운영 ──────────────────────────────────────────────────────
@app.get("/health")
def health(s: Session = Depends(db)):
    """모니터링: DB 연결, 작업별 마지막 실행 결과, 오늘 API 사용량, 현재 provider 구성."""
    st = get_settings()
    last = {}
    for job, in s.execute(select(JobRun.job).distinct()).all():
        r = s.scalar(select(JobRun).where(JobRun.job == job).order_by(desc(JobRun.started_at)).limit(1))
        last[job] = {"status": r.status, "at": r.started_at, "items": r.items, "message": r.message}
    usage = {src: n for src, n in s.execute(
        select(ApiUsage.source, ApiUsage.calls).where(ApiUsage.day == date.today())).all()}
    return {
        "ok": True, "market_open": is_market_open(), "jobs": last, "api_usage_today": usage,
        "providers": {"embedding": st.embedding_provider, "summarizer": st.summarizer_provider,
                      "sentiment": st.sentiment_provider, "paid_allowed": st.allow_paid_apis},
    }


# ── 마켓 대시보드 ─────────────────────────────────────────────
def _series(s: Session, symbol: str, n: int) -> list[Price]:
    rows = s.scalars(select(Price).where(Price.symbol == symbol).order_by(desc(Price.day)).limit(n)).all()
    return list(reversed(rows))


def _change(rows: list[Price]) -> tuple[float | None, float | None]:
    """(전일 대비 절대값, 등락률)"""
    if not rows:
        return None, None
    last = rows[-1]
    prev = rows[-2].close if len(rows) >= 2 else None
    pct = last.change_pct
    if pct is None and prev:
        pct = round((last.close / prev - 1) * 100, 2)
    return (round(last.close - prev, 2) if prev else None), pct


def _indices(s: Session) -> list[dict]:
    out = []
    for item in load_yaml("sources.yaml").get("index_strip", []):
        sym, name = (item["symbol"], item["name"]) if isinstance(item, dict) else (item, item)
        rows = _series(s, sym, 30)
        if not rows:
            continue
        chg, pct = _change(rows)
        out.append({"symbol": sym, "name": name, "close": rows[-1].close, "change": chg, "change_pct": pct,
                    "day": rows[-1].day, "stale": (date.today() - rows[-1].day).days > STALE_DAYS,
                    "spark": [r.close for r in rows]})
    return out


def _sentiment_counts(s: Session, code: str, hours: int = 24) -> dict:
    rows = dict(s.execute(select(Article.sentiment, func.count()).where(
        Article.ticker_keys.like(f"%,{code},%"), Article.published_at >= _now() - timedelta(hours=hours),
    ).group_by(Article.sentiment)).all())
    c = {k: int(rows.get(k, 0)) for k in ("positive", "neutral", "negative")}
    c["total"] = sum(c.values())
    return c


def _watchlist(s: Session, user: User | None) -> list[dict]:
    """계정별 관심종목 (보유 → 이름순). 로그인하지 않았으면 빈 목록."""
    if user is None:
        return []
    out = []
    since = _now() - timedelta(hours=24)
    rows = s.execute(select(Ticker, UserWatchlist.holding)
                     .join(UserWatchlist, UserWatchlist.ticker == Ticker.code)
                     .where(UserWatchlist.user_id == user.id)
                     .order_by(desc(UserWatchlist.holding), Ticker.name)).all()
    for t, holding in rows:
        rows = _series(s, t.code, 60)
        chg, pct = _change(rows)
        top = s.execute(
            select(Issue.no, IssueSummaryRow.payload).join(IssueTicker, IssueTicker.issue_id == Issue.id)
            .join(IssueSummaryRow, (IssueSummaryRow.issue_id == Issue.id) & IssueSummaryRow.is_current.is_(True))
            .where(IssueTicker.ticker == t.code, Issue.last_seen >= since)
            .order_by(desc(Issue.importance)).limit(1)).first()
        out.append({
            "code": t.code, "name": t.name, "holding": holding, "market": t.market,
            "region": "us" if is_us_market(t.market) else "kr",
            "close": rows[-1].close if rows else None, "change": chg, "change_pct": pct,
            "day": rows[-1].day if rows else None, "spark": [r.close for r in rows],
            "stale": bool(rows) and (date.today() - rows[-1].day).days > STALE_DAYS,
            "sentiment": _sentiment_counts(s, t.code),
            "top_issue": {"no": top[0], "headline": top[1]["headline"]} if top else None,
        })
    return out


def _sectors(s: Session, market: str = "ETF") -> dict:
    """업종 히트맵. market="ETF" 국내 업종 ETF, "US" 미국 업종 ETF (각자 마지막 거래일 기준)."""
    basis = "us_etf" if market == "US" else "etf"
    last_day = s.scalar(select(func.max(SectorIndex.day)).where(SectorIndex.market == market))
    if not last_day:
        return {"day": None, "basis": basis, "items": []}
    rows = s.scalars(select(SectorIndex).where(SectorIndex.market == market, SectorIndex.day == last_day)
                     .order_by(desc(SectorIndex.change_pct))).all()
    return {"day": last_day, "basis": basis,
            "items": [{"name": r.name, "market": r.market, "change_pct": r.change_pct, "close": r.close,
                       "symbol": r.symbol} for r in rows]}


JOB_LABELS = {
    "job_news_pipeline": "뉴스 수집", "job_backfill_prices": "시세", "job_daily_close": "시세(마감)",
    "job_intraday_prices": "시세(장중)", "job_sync_tickers": "종목 목록", "job_macro": "거시 지표",
}
STALE_DAYS = 4


def _collection_status(s: Session) -> dict:
    """화면 배너용: 첫 실행 중인지, 최근 실패한 수집 작업이 있는지."""
    latest: dict[str, JobRun] = {}
    for r in s.scalars(select(JobRun).where(JobRun.started_at >= _now() - timedelta(days=3))
                       .order_by(JobRun.started_at)).all():
        latest[r.job] = r
    problems = [{"job": j, "label": JOB_LABELS.get(j, j), "at": r.started_at,
                 "message": (r.message or "").removeprefix("RuntimeError: ")[:240]}
                for j, r in latest.items() if r.status == "error" and j in JOB_LABELS]
    return {"first_run": "job_news_pipeline" not in latest, "problems": problems,
            "scheduler": os.environ.get("ISSUE_STREAM_SCHEDULER") == "1"}


SORTS = {"importance": (desc(Issue.importance), desc(Issue.last_seen)),   # 중요도순
         "recent": (desc(Issue.last_seen), desc(Issue.importance))}       # 최신순 (마지막 보도 시각)


def _top_issues(s: Session, region: str, sort: str = "importance", n: int = 6) -> list[Issue]:
    return list(s.scalars(select(Issue).where(Issue.last_seen >= _now() - timedelta(hours=24), Issue.region == region)
                          .order_by(*SORTS.get(sort, SORTS["importance"])).limit(n)).all())


def _like(q: str) -> str:
    """LIKE 패턴용 이스케이프 (%, _ 를 글자 그대로)."""
    return q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@app.get("/dashboard")
def dashboard(sort: str = "importance", s: Session = Depends(db), user: User | None = Depends(optional_user)):
    """마켓 대시보드 한 화면에 필요한 값 전부. 결론(요약)이 위, 근거(표·히트맵)가 아래.
    AI 요약·주요 뉴스·관심종목·히트맵은 국내(kr)와 미국(us)을 따로 내려준다."""
    demo = bool(s.scalar(select(Price.symbol).where(Price.source == "demo").limit(1)) or
                s.scalar(select(Article.id).where(Article.source.like("demo%")).limit(1)))
    return {
        "generated_at": _now(),
        "user": user_json(user) if user else None,
        "demo": demo,
        "collection": _collection_status(s),
        "market_open": is_market_open(),
        "us_market_open": is_us_market_open(),
        "indices": _indices(s),
        "brief": build_market_brief(s, region="kr"),
        "brief_us": build_market_brief(s, region="us"),
        "watchlist": _watchlist(s, user),
        "sectors": _sectors(s, "ETF"),
        "sectors_us": _sectors(s, "US"),
        "issues": [_issue_card(s, i, with_articles=False) for i in _top_issues(s, "kr", sort)],
        "issues_us": [_issue_card(s, i, with_articles=False) for i in _top_issues(s, "us", sort)],
    }


@app.get("/market/prices/{symbol:path}")
def prices(symbol: str, days: int = 120, s: Session = Depends(db)):
    t = s.get(Ticker, symbol)
    rows = _series(s, symbol, days)
    return {"symbol": symbol, "name": t.name if t else symbol, "market": t.market if t else None,
            "is_stock": t is not None,   # 지수·환율은 종목 마스터에 없다
            "points": [{"day": r.day, "close": r.close, "open": r.open, "high": r.high, "low": r.low,
                        "volume": r.volume, "change_pct": r.change_pct} for r in rows]}


@app.get("/me/watchlist")
def my_watchlist(s: Session = Depends(db), user: User = Depends(current_user)):
    return _watchlist(s, user)


class WatchIn(BaseModel):
    holding: bool = False


@app.put("/me/watchlist/{code}")
def add_watch(code: str, bg: BackgroundTasks, body: WatchIn | None = None, s: Session = Depends(db),
              user: User = Depends(current_user)):
    """관심종목 등록(☆) 또는 보유 표시 변경. 처음 수집하는 종목이면 과거 시세를 백그라운드로 채운다."""
    from ..jobs import tasks
    t = s.get(Ticker, code)
    if t is None:
        raise HTTPException(404, f"종목 {code} 을(를) 찾을 수 없습니다")
    row = s.get(UserWatchlist, (user.id, code))
    if row is None:
        limit = get_settings().max_watchlist_per_user
        n = s.scalar(select(func.count()).select_from(UserWatchlist).where(UserWatchlist.user_id == user.id))
        if n >= limit:
            raise HTTPException(400, f"관심종목은 계정당 {limit}개까지 등록할 수 있습니다")
        row = UserWatchlist(user_id=user.id, ticker=code, holding=False)
        s.add(row)
    if body is not None:   # 본문 없이 부르면 보유 표시는 그대로 둔다
        row.holding = body.holding
    holding = row.holding
    s.commit()
    new_target = not t.in_watchlist
    tasks.sync_watchlist()
    if new_target or not s.scalar(select(Price.day).where(Price.symbol == code).limit(1)):
        bg.add_task(tasks.job_backfill_ticker, code)
    return {"code": code, "name": t.name, "holding": holding}


@app.delete("/me/watchlist/{code}", status_code=204)
def remove_watch(code: str, s: Session = Depends(db), user: User = Depends(current_user)):
    from ..jobs import tasks
    s.execute(delete(UserWatchlist).where(UserWatchlist.user_id == user.id, UserWatchlist.ticker == code))
    s.commit()
    tasks.sync_watchlist()


@app.get("/market/indices")
def indices(s: Session = Depends(db)):
    return _indices(s)


@app.get("/market/sectors")
def sectors(region: str = "kr", s: Session = Depends(db)):
    return _sectors(s, "US" if region == "us" else "ETF")


@app.get("/tickers")
def tickers(s: Session = Depends(db), user: User | None = Depends(optional_user)):
    """이슈 브리핑 필터용: 내 관심종목 + 최근 이슈에 등장한 종목."""
    since = _now() - timedelta(hours=72)
    cond = Ticker.code.in_(select(IssueTicker.ticker).join(Issue).where(Issue.last_seen >= since))
    if user:
        cond = cond | Ticker.code.in_(select(UserWatchlist.ticker).where(UserWatchlist.user_id == user.id))
    rows = s.execute(select(Ticker.code, Ticker.name).where(cond).order_by(Ticker.name)).all()
    return [{"code": c, "name": n} for c, n in rows]


@app.get("/tickers/search")
def search_tickers(q: str, limit: int = 20, s: Session = Depends(db),
                   user: User | None = Depends(optional_user)):
    """관심종목 추가용 종목 검색 (종목명·코드). 이름이 검색어로 시작하는 종목을 먼저."""
    q = q.strip()
    if not q:
        return []
    like = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    rows = s.execute(select(Ticker.code, Ticker.name, Ticker.market).where(or_(
        Ticker.name.ilike(f"%{like}%", escape="\\"), Ticker.code.like(f"{like}%", escape="\\")))
        .order_by(Ticker.name.ilike(f"{like}%", escape="\\").desc(), func.length(Ticker.name), Ticker.name)
        .limit(min(limit, 50))).all()
    mine = set()
    if user:
        mine = set(s.scalars(select(UserWatchlist.ticker).where(UserWatchlist.user_id == user.id)).all())
    return [{"code": c, "name": n, "market": m, "watched": c in mine} for c, n, m in rows]


# ── 이슈 브리핑 ───────────────────────────────────────────────
@app.get("/issues")
def list_issues(hours: int = 24, ticker: str | None = None, sentiment: str | None = None,
                region: str | None = None, sort: str = "importance", q: str | None = None, qt: str = "all",
                page: int = 1, page_size: int = 20, s: Session = Depends(db)):
    """이슈 목록 (페이지 단위).

    region=kr|us 그 지역만 (생략하면 전부) · sort=importance(중요도순)|recent(최신순)
    q=검색어, qt=all(종목+기사)|ticker(종목명·코드)|text(기사 제목·요약문) · page 1부터, page_size 최대 50
    """
    page_size = max(1, min(page_size, 50))
    page = max(1, page)
    cond = [Issue.last_seen >= _now() - timedelta(hours=hours)]
    if region in ("kr", "us"):
        cond.append(Issue.region == region)
    if ticker:
        cond.append(Issue.id.in_(select(IssueTicker.issue_id).where(IssueTicker.ticker == ticker)))
    if sentiment:
        cond.append(Issue.sentiment == sentiment)
    if q and q.strip():
        pat = f"%{_like(q.strip())}%"
        by_ticker = select(IssueTicker.issue_id).join(Ticker, Ticker.code == IssueTicker.ticker).where(or_(
            Ticker.name.ilike(pat, escape="\\"), Ticker.name_en.ilike(pat, escape="\\"),
            Ticker.code == q.strip().upper()))
        by_text = select(IssueArticle.issue_id).join(Article, Article.id == IssueArticle.article_id).where(or_(
            Article.title.ilike(pat, escape="\\"), Article.snippet.ilike(pat, escape="\\")))
        if qt == "ticker":
            cond.append(Issue.id.in_(by_ticker))
        elif qt == "text":
            cond.append(Issue.id.in_(by_text))
        else:
            cond.append(or_(Issue.id.in_(by_ticker), Issue.id.in_(by_text)))
    total = s.scalar(select(func.count()).select_from(Issue).where(*cond)) or 0
    issues = s.scalars(select(Issue).where(*cond).order_by(*SORTS.get(sort, SORTS["importance"]))
                       .offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [_issue_card(s, i) for i in issues], "total": total, "page": page, "page_size": page_size,
            "pages": max(1, -(-total // page_size))}


@app.get("/issues/{issue_no}")
def get_issue(issue_no: int, s: Session = Depends(db)):
    i = s.scalar(select(Issue).where(Issue.no == issue_no))
    if not i:
        raise HTTPException(404)
    return _issue_card(s, i)


COVERAGE_HOURS = 24


def _issue_card(s: Session, i: Issue, with_articles: bool = True) -> dict:
    summ = s.scalar(select(IssueSummaryRow).where(IssueSummaryRow.issue_id == i.id,
                                                  IssueSummaryRow.is_current.is_(True)))
    tickers = s.execute(select(Ticker.code, Ticker.name).join(IssueTicker, IssueTicker.ticker == Ticker.code)
                        .where(IssueTicker.issue_id == i.id).order_by(desc(IssueTicker.mentions))).all()
    arts = s.scalars(select(Article).join(IssueArticle, IssueArticle.article_id == Article.id)
                     .where(IssueArticle.issue_id == i.id).order_by(Article.published_at)).all()
    now = _now()

    # 보도량 추이: 최근 24시간을 1시간 단위로 (오래된 → 최근)
    coverage = [0] * COVERAGE_HOURS
    for a in arts:
        h = int((now - a.published_at).total_seconds() // 3600)
        if 0 <= h < COVERAGE_HOURS:
            coverage[COVERAGE_HOURS - 1 - h] += 1

    # 출처: 매체별 첫 보도 시각 (먼저 보도한 순)
    first_by_pub: dict[str, datetime] = {}
    for a in arts:
        if a.publisher and a.publisher not in first_by_pub:
            first_by_pub[a.publisher] = a.published_at
    sources = [{"publisher": p, "at": t} for p, t in first_by_pub.items()]

    card = {
        "no": i.no, "region": i.region, "importance": i.importance, "sentiment": i.sentiment or "neutral",
        "article_count": i.article_count, "publisher_count": i.publisher_count,
        "has_disclosure": i.has_disclosure, "first_seen": i.first_seen, "last_seen": i.last_seen,
        "tickers": [{"code": c, "name": n} for c, n in tickers],
        "summary": summ.payload if summ else None,
        "sources": sources,
        "coverage": coverage,
        "last_hour": sum(1 for a in arts if a.published_at >= now - timedelta(hours=1)),
        "article_sentiment": dict(Counter(a.sentiment or "neutral" for a in arts)),
    }
    if with_articles:
        # 저작권: 제목·매체·시각·링크만 노출 (본문 없음). 요약에 쓰인 근거 기사를 먼저.
        used = set((summ.payload.get("source_article_ids") if summ else []) or [])
        card["articles"] = sorted(
            [{"no": a.no, "title": a.title, "publisher": a.publisher, "url": a.url,
              "published_at": a.published_at, "kind": a.kind, "sentiment": a.sentiment,
              "cited": str(a.id) in used} for a in arts],
            key=lambda x: (not x["cited"], x["published_at"]))
    return card


# ── 거시 ─────────────────────────────────────────────────────
@app.get("/macro/{series_id}")
def macro(series_id: str, s: Session = Depends(db)):
    rows = s.scalars(select(MacroSeries).where(MacroSeries.series_id == series_id)
                     .order_by(MacroSeries.day)).all()
    return [{"day": r.day, "value": r.value} for r in rows]

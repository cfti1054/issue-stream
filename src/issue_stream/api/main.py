"""대시보드용 REST API. 프론트는 계산하지 않고 여기서 받은 값을 그리기만 한다.

실행: issue-stream api   (또는 uvicorn issue_stream.api.main:app --reload)
문서: http://localhost:8000/docs

화면별 엔드포인트
  마켓 대시보드  GET /dashboard                  한 번에 필요한 값 전부
                 GET /market/prices/{symbol}      선택 종목 가격 차트
  이슈 브리핑    GET /issues                      이슈 카드 (근거 기사·보도량 추이 포함)
                 GET /issues/{no}                 이슈 상세 (확산 타임라인)
  시그널         GET /signals                     이슈 주제 → 대표 종목(이유·등락률) → 연관 종목
  코인           GET /market/coins                시장 요약·주요 코인·김치 프리미엄·업비트 순위
  환율·원자재    GET /market/fx                   원화 환율·달러 지표·금·은·원유·구리
  로그인·가입    POST /auth/login, /auth/signup, /auth/logout, GET /auth/me, /auth/config   (api/auth.py)
  관심종목       GET /me/watchlist, PUT·DELETE /me/watchlist/{code}, GET /tickers/search
  번호           이슈·기사·계정은 화면용 번호 no 로 내보낸다. 내부 PK id 는 FK 전용 (db/sequences.py)
                 관심종목은 계정별. 로그인하지 않으면 /dashboard 의 watchlist 는 빈 목록이다.
"""
from __future__ import annotations

import os
import time
from collections import Counter
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import delete, desc, func, or_, select
from sqlalchemy.orm import Session

from ..core.config import get_settings, load_yaml
from ..core.market_calendar import (
    is_market_open, is_trading_day, is_us_market, is_us_market_open, previous_trading_day,
)
from ..db.models import (
    ApiUsage, Article, Issue, IssueArticle, IssueSummaryRow, IssueTicker, JobRun, MacroSeries, Price,
    SectorIndex, Ticker, User, UserWatchlist,
)
from ..pipeline import topics
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
    "job_intraday_prices": "시세(장중)", "job_fx_rates": "환율·원자재", "job_coin_prices": "코인", "job_sync_tickers": "종목 목록",
    "job_macro": "거시 지표",
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
def prices(symbol: str, days: int = 120, krw: bool = False, usd: bool = False, s: Session = Depends(db)):
    """일봉 시세. krw=true 면 달러 표시 항목(미국 주식·국제 원자재)을 그날 원/달러로 곱해 원화로,
    usd=true 면 원화 표시 코인(COIN:BTC)을 그날 원/달러로 나눠 달러로 돌려준다."""
    t = s.get(Ticker, symbol)
    rows = _series(s, symbol, days)
    if t is not None and _needs_fetch(t, rows, days):
        # 관심종목이 아닌 종목도 차트를 열면 바로 보이도록 그 자리에서 받아 저장한다 (네이버 1~3회 요청)
        from ..jobs.tasks import save_watchlist_prices
        n = BACKFILL_DAYS if len(rows) < min(days, MIN_CHART_ROWS) else 5
        _fetched_at[symbol] = time.monotonic()
        save_watchlist_prices(n, [symbol])
        s.expire_all()
        rows = _series(s, symbol, days)
    points = [{"day": r.day, "close": r.close, "open": r.open, "high": r.high, "low": r.low,
               "volume": r.volume, "change_pct": r.change_pct} for r in rows]
    if symbol.startswith("COIN:"):   # 코인: 원화가 기본, 달러로 바꿔 볼 수 있다
        code = symbol.removeprefix("COIN:")
        name = next((c["name"] for c in load_yaml("sources.yaml").get("coins", []) if c["code"] == code), code)
        if usd and points:
            points = _convert(s, points, 1.0, to_usd=True)
        return {"symbol": symbol, "name": name, "market": None, "is_stock": False, "convertible": True,
                "currency": "USD" if usd else "KRW", "unit": "$" if usd else "원", "points": points}
    usd = is_us_market(t.market) if t else False
    cmdt = next((c for c in load_yaml("sources.yaml").get("commodities", []) if c["symbol"] == symbol), None)
    if cmdt:
        usd = cmdt.get("currency") == "USD"
    unit = cmdt.get("unit") if cmdt else ("$" if usd else None)
    krw_unit = (cmdt.get("krw_unit") if cmdt else None) or ("원" if usd else None)
    if krw and usd and points:
        points = _convert(s, points, float(cmdt.get("krw_per", 1)) if cmdt else 1.0)
    return {"symbol": symbol, "name": t.name if t else (cmdt["name"] if cmdt else symbol),
            "market": t.market if t else None,
            "is_stock": t is not None,   # 지수·환율은 종목 마스터에 없다
            "convertible": usd,          # 원화 토글을 보여 줄지
            "currency": "KRW" if krw and usd else ("USD" if usd else None),
            "unit": krw_unit if krw and usd else unit,
            "points": points}


def _convert(s: Session, points: list[dict], per: float, to_usd: bool = False) -> list[dict]:
    """각 날짜의 값 × 그날(없으면 직전 날) 원/달러 ÷ per (to_usd 면 ÷ 원/달러).
    등락률은 바꾼 통화 기준으로 다시 계산한다."""
    from bisect import bisect_right
    fx = s.execute(select(Price.day, Price.close).where(Price.symbol == "USD/KRW",
                                                      Price.day >= points[0]["day"] - timedelta(days=10))
                   .order_by(Price.day)).all()
    if not fx:
        return points
    days = [d for d, _ in fx]
    out, prev = [], None
    for p in points:
        i = bisect_right(days, p["day"]) - 1
        usdkrw = fx[i][1] if i >= 0 else fx[0][1]
        rate = 1 / usdkrw if to_usd else usdkrw / per
        nd = 6 if to_usd else 2   # 달러로 바꾸면 도지코인처럼 1달러 미만도 있다
        q = p | {k: (round(p[k] * rate, nd) if p[k] is not None else None) for k in ("close", "open", "high", "low")}
        q["change_pct"] = round((q["close"] / prev - 1) * 100, 2) if prev else p["change_pct"]
        prev = q["close"]
        out.append(q)
    return out


# ── 코인 ─────────────────────────────────────────────────────
RANK_SIZE = 10


@app.get("/market/coins")
def coins_board(s: Session = Depends(db)):
    """코인 화면. 현재가·순위는 업비트(30초 캐시), 시가총액·점유율은 코인게코, 공포·탐욕은 alternative.me (10분 캐시).
    summary  시장 요약 (시가총액·BTC 점유율·공포탐욕·BTC 김치 프리미엄)
    coins    주요 코인 카드 (sources.yaml coins) · premium 코인별 김치 프리미엄 · ranking 거래대금·상승·하락 상위"""
    from ..collectors import crypto
    cfg = load_yaml("sources.yaml").get("coins", [])
    names = crypto.cached("markets", 86_400, crypto.krw_markets) or {}
    live = crypto.cached("tickers", 30, lambda: crypto.tickers(list(names) or [f"KRW-{c['code']}" for c in cfg])) or []
    by_code = {x["code"]: x for x in live}
    usd_rows = _series(s, "USD/KRW", 1)
    usdkrw = usd_rows[-1].close if usd_rows else None

    coins = []
    for c in cfg:
        sym = f"COIN:{c['code']}"
        rows = _series(s, sym, 130)
        closes = [r.close for r in rows]
        t = by_code.get(c["code"])
        price = t["price"] if t else (closes[-1] if closes else None)
        if price is None:
            continue
        coins.append({"symbol": sym, "code": c["code"], "name": c["name"], "price": price,
                      "change": t["change"] if t else None, "change_pct": t["change_pct"] if t else None,
                      "volume_krw": t["volume_krw"] if t else None,
                      "spark": closes[-30:], "high": max(closes) if closes else None,
                      "low": min(closes) if closes else None, "since": rows[0].day if rows else None,
                      "live": t is not None})

    glob = crypto.cached("global_usd", 30, lambda: crypto.global_usd(cfg)) or {}
    premium = []
    if usdkrw:
        for c in coins:
            g = glob.get(c["code"])
            if g:
                gk = g * usdkrw
                premium.append({"code": c["code"], "name": c["name"], "upbit": c["price"],
                                "global_usd": g, "global_krw": round(gk, 2),
                                "premium_pct": round((c["price"] / gk - 1) * 100, 2)})

    overview = crypto.cached("overview", 600, crypto.market_overview)
    ranked = [x | {"name": names.get(x["market"], x["code"])} for x in live]
    by_value = sorted(ranked, key=lambda x: -x["volume_krw"])
    # 상승·하락은 거래대금이 너무 작은 코인(상위 100위 밖)을 빼서 잡코인 급등락에 휘둘리지 않게
    liquid = by_value[:100]
    return {
        "updated_at": _now(),
        "summary": {
            "market_cap_usd": overview["market_cap_usd"] if overview else None,
            "market_cap_krw": overview["market_cap_usd"] * usdkrw if overview and usdkrw else None,
            "market_cap_change_pct": overview["market_cap_change_pct"] if overview else None,
            "btc_dominance": overview["btc_dominance"] if overview else None,
            "eth_dominance": overview["eth_dominance"] if overview else None,
            "fear_greed": crypto.cached("fng", 600, crypto.fear_greed),
            "kimchi": next((p for p in premium if p["code"] == "BTC"), None),
            "usdkrw": usdkrw,
            "markets": len(names),
        },
        "coins": coins,
        "premium": premium,
        "ranking": {
            "value": by_value[:RANK_SIZE],
            "up": sorted(liquid, key=lambda x: -x["change_pct"])[:RANK_SIZE],
            "down": sorted(liquid, key=lambda x: x["change_pct"])[:RANK_SIZE],
        },
    }


TROY_OUNCE_G = 31.1034768   # 금·은 1트로이온스 = 31.1g


def _board_item(s: Session, item: dict) -> dict | None:
    rows = _series(s, item["symbol"], 130)
    if not rows:
        return None
    chg, pct = _change(rows)
    closes = [r.close for r in rows]
    return {"symbol": item["symbol"], "name": item["name"], "close": rows[-1].close, "change": chg,
            "change_pct": pct, "day": rows[-1].day, "stale": (date.today() - rows[-1].day).days > STALE_DAYS,
            "high": max(closes), "low": min(closes), "since": rows[0].day, "spark": closes[-30:]}


@app.get("/market/fx")
def fx_rates(s: Session = Depends(db)):
    """환율·원자재 화면. 기간 최고·최저는 최근 약 6개월.
    items       원화 환율(unit 단위당 원)과 달러 지표(달러 인덱스·교차 환율)
    commodities 금·은·원유·구리 (unit_label: 원/g, $/oz …)
    gold        국제 금을 원/달러로 환산한 원/g 과 국내 금(KRX)과의 차이(%)"""
    cfg = load_yaml("sources.yaml")
    items, commodities = [], []
    for item in cfg.get("fx_rates", []):
        if (row := _board_item(s, item)) is not None:
            items.append(row | {"currency": item.get("currency"), "unit": item.get("unit", 1)})
    for item in cfg.get("commodities", []):
        if (row := _board_item(s, item)) is not None:
            commodities.append(row | {"unit_label": item.get("unit", "")})
    last = s.scalar(select(func.max(JobRun.finished_at)).where(JobRun.job == "job_fx_rates", JobRun.status == "ok"))
    return {"updated_at": last, "items": items, "commodities": commodities, "gold": _gold_premium(s)}


def _gold_premium(s: Session) -> dict | None:
    """국제 금(달러/온스) × 원/달러 ÷ 31.1 = 원/g. 국내 금이 이보다 비싸면 프리미엄(+)."""
    krx, intl, usd = (_series(s, sym, 1) for sym in ("CMDT:GOLD_KRX", "CMDT:GOLD", "USD/KRW"))
    if not (krx and intl and usd):
        return None
    per_g = intl[-1].close * usd[-1].close / TROY_OUNCE_G
    return {"domestic": krx[-1].close, "intl_krw_per_g": round(per_g, 1),
            "premium_pct": round((krx[-1].close / per_g - 1) * 100, 2), "usdkrw": usd[-1].close,
            "day": min(krx[-1].day, intl[-1].day, usd[-1].day)}


BACKFILL_DAYS = 130   # 처음 여는 종목의 과거 시세 (차트 '전체' 범위)
MIN_CHART_ROWS = 20


REFETCH_SECONDS = 60   # 같은 종목은 1분에 한 번만 다시 받는다 (장중 새로고침마다 요청하지 않게)
_fetched_at: dict[str, float] = {}


def _needs_fetch(t: Ticker, rows: list[Price], days: int) -> bool:
    """저장된 시세가 차트를 그리기에 모자라거나, 수집 대상이 아닌 종목의 시세가 낡았으면 True.
    관심종목은 스케줄러가 갱신하므로 비어 있을 때만 받는다."""
    if time.monotonic() - _fetched_at.get(t.code, -REFETCH_SECONDS) < REFETCH_SECONDS:
        return False
    if len(rows) < min(days, MIN_CHART_ROWS):
        return True
    if t.in_watchlist:
        return False
    us = is_us_market(t.market)
    live = is_us_market_open() if us else is_market_open()
    return live or rows[-1].day < _last_session(us)   # 장중이면 현재가, 아니면 빠진 거래일 보충


def _last_session(us: bool) -> date:
    """가장 최근에 열린(또는 오늘 열린) 거래일. 국내는 KRX 휴장일 달력, 미국은 뉴욕 시간 평일 기준."""
    if us:
        from zoneinfo import ZoneInfo
        d = datetime.now(ZoneInfo("America/New_York"))
        day = d.date() if d.weekday() < 5 and (d.hour, d.minute) >= (9, 30) else None
        cur = d.date()
        while day is None:
            cur -= timedelta(days=1)
            day = cur if cur.weekday() < 5 else None
        return day
    now = datetime.now(timezone(timedelta(hours=9)))
    today = now.date()
    return today if is_trading_day(today) and now.hour >= 9 else previous_trading_day(today)


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
        # 받아쓰기 중복(duplicate_of)은 원본 한 줄로 묶고 다른 매체만 덧붙인다. 보도량·매체 수에는 위에서 이미 반영.
        groups: dict[int, list[Article]] = {}
        for a in arts:
            groups.setdefault(a.duplicate_of or a.id, []).append(a)
        rows = []
        for key, g in groups.items():
            head = next((a for a in g if a.id == key), g[0])
            rows.append({"no": head.no, "title": head.title, "publisher": head.publisher, "url": head.url,
                         "published_at": head.published_at, "kind": head.kind, "sentiment": head.sentiment,
                         "cited": any(str(a.id) in used for a in g),
                         "also": list(dict.fromkeys(a.publisher for a in g
                                                    if a is not head and a.publisher and a.publisher != head.publisher))})
        card["articles"] = sorted(rows, key=lambda x: (not x["cited"], x["published_at"]))
    return card


# ── 시그널 ───────────────────────────────────────────────────
# 대표 종목이 없는 이슈(금리·환율 등)는 시장 지수를 대표로 보여 준다
MARKET_PROXY = {"kr": ("KS11", "코스피"), "us": ("US500", "S&P 500")}


def _quote(s: Session, symbol: str) -> dict:
    rows = _series(s, symbol, 2)
    _, pct = _change(rows)
    return {"close": rows[-1].close if rows else None, "change_pct": pct, "day": rows[-1].day if rows else None}


@app.get("/signals")
def signals(region: str = "kr", hours: int = 6, limit: int = 12, s: Session = Depends(db),
            user: User | None = Depends(optional_user)):
    """시그널 맵. 이슈 1건 = 1줄: 주제·키워드·출처 → 대표 종목(이유·등락률) → 함께 언급된 종목.
    로그인하면 관심종목이 나온 이슈는 mine 으로 따로 내려준다 (items 에서는 뺀다)."""
    region = "us" if region == "us" else "kr"
    hours = max(1, min(hours, 72))
    limit = max(1, min(limit, 30))
    mine_codes = set(s.scalars(select(UserWatchlist.ticker).where(UserWatchlist.user_id == user.id)).all())         if user else set()
    issues = s.scalars(select(Issue).where(Issue.last_seen >= _now() - timedelta(hours=hours), Issue.region == region)
                       .order_by(desc(Issue.importance), desc(Issue.last_seen)).limit(limit * 3)).all()
    items, mine = [], []
    for i in issues:
        row = _signal_row(s, i, region)
        if mine_codes and mine_codes & {row["main"]["code"], *(r["code"] for r in row["related"])}:
            mine.append(row)
        elif len(items) < limit:
            items.append(row)
    return {"region": region, "hours": hours, "generated_at": _now(), "items": items, "mine": mine[:limit]}


def _signal_row(s: Session, i: Issue, region: str) -> dict:
    summ = s.scalar(select(IssueSummaryRow.payload).where(IssueSummaryRow.issue_id == i.id,
                                                         IssueSummaryRow.is_current.is_(True))) or {}
    tick = s.execute(select(Ticker.code, Ticker.name, Ticker.market).join(IssueTicker, IssueTicker.ticker == Ticker.code)
                     .where(IssueTicker.issue_id == i.id).order_by(desc(IssueTicker.mentions))).all()
    # 대표 종목: 요약이 꼽은 첫 종목 → 언급이 가장 많은 종목 → 시장 지수
    first = next(iter(summ.get("affected_tickers") or []), None)
    tick = sorted(tick, key=lambda r: r[0] != first)
    names = [n for _, n, _ in tick]
    arts = s.execute(select(Article.title, Article.publisher, Article.published_at)
                     .join(IssueArticle, IssueArticle.article_id == Article.id)
                     .where(IssueArticle.issue_id == i.id).order_by(Article.published_at)).all()
    titles = [a.title for a in arts]
    pubs = list(dict.fromkeys(a.publisher for a in arts if a.publisher))
    headline = summ.get("headline") or (titles[0] if titles else "")

    if tick:
        code, name, market = tick[0]
        main = {"code": code, "name": name, "market": market, "is_index": False}
    else:
        code, name = MARKET_PROXY[region]
        main = {"code": code, "name": name, "market": None, "is_index": True}
    main.update(_quote(s, main["code"]))
    related = [{"code": c, "name": n, "market": m, **_quote(s, c)} for c, n, m in tick[1:4]]
    return {
        "issue_no": i.no, "importance": i.importance, "sentiment": i.sentiment or "neutral",
        "last_seen": i.last_seen, "headline": headline,
        # 예전 요약(필드 추가 전)은 규칙으로 채운다
        "category": summ.get("category") or topics.classify(titles),
        "keywords": summ.get("keywords") or topics.keywords(titles, names),
        "reason": summ.get("reason") or topics.reason(headline, names),
        "publisher_count": i.publisher_count, "publishers": pubs[:3],
        "main": main, "related": related, "related_more": max(0, len(tick) - 4),
    }


# ── 거시 ─────────────────────────────────────────────────────
@app.get("/macro/{series_id}")
def macro(series_id: str, s: Session = Depends(db)):
    rows = s.scalars(select(MacroSeries).where(MacroSeries.series_id == series_id)
                     .order_by(MacroSeries.day)).all()
    return [{"day": r.day, "value": r.value} for r in rows]

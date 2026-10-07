"""스케줄러가 호출하는 작업 단위.

모든 작업은 @tracked 로 감싸 job_runs 테이블에 성공/실패·처리 건수·소요 시간을 남기고,
실패하면 텔레그램으로 알린다 (기획서에 빠져 있던 모니터링).
"""
from __future__ import annotations

import functools
import logging
import traceback
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, select, update

from ..core import http
from ..core.config import get_settings, load_yaml
from ..core.market_calendar import is_market_open, is_trading_day
from ..db.models import (
    ApiUsage, Article, ArticleBody, DartCorpCode, JobRun, MacroSeries, Price, SectorIndex, Ticker,
    UserSession, UserWatchlist,
)
from ..db.ops import upsert
from ..db.session import session_scope
from ..pipeline import run as pipeline

log = logging.getLogger(__name__)


class Skip(Exception):
    """작업을 건너뛸 때 (휴장일 등). 실패로 기록하지 않는다."""


def tracked(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        started = datetime.now(timezone.utc)
        status, items, msg = "ok", 0, None
        try:
            items = fn(*args, **kwargs) or 0
        except Skip as e:
            status, msg = "skipped", str(e)
        except Exception as e:
            status, msg = "error", "".join(traceback.format_exception_only(e)).strip()
            log.exception("작업 %s 실패", fn.__name__)
            from ..notify.telegram import send_job_failure
            send_job_failure(fn.__name__, msg)
        finally:
            with session_scope() as db:
                db.add(JobRun(job=fn.__name__, started_at=started, finished_at=datetime.now(timezone.utc),
                              status=status, items=items, message=msg))
                _flush_api_usage(db)
        return items
    return wrapper


def _flush_api_usage(db) -> None:
    for source, n in http.usage_today().items():
        upsert(db, ApiUsage, dict(source=source, day=date.today(), calls=n), ["source", "day"])


def restore_api_usage() -> None:
    with session_scope() as db:
        rows = db.execute(select(ApiUsage.source, ApiUsage.calls).where(ApiUsage.day == date.today())).all()
    http.seed_usage(dict(rows))


# ── 뉴스·공시 파이프라인 ───────────────────────────────────────
@tracked
def job_news_pipeline() -> int:
    with session_scope() as db:
        n = pipeline.collect_and_ingest(db)
    with session_scope() as db:
        pipeline.cluster_pending(db)
    with session_scope() as db:
        pipeline.enrich_issues(db)
    return n


# ── 시세 (네이버 → 야후 → FDR, 키·로그인 불필요) ─────────────────
def _watchlist_codes(codes: list[str] | None = None) -> list[tuple[str, str | None]]:
    q = select(Ticker.code, Ticker.market)
    q = q.where(Ticker.code.in_(codes)) if codes is not None else q.where(Ticker.in_watchlist.is_(True))
    with session_scope() as db:
        return list(db.execute(q).all())


def _save_rows(model, rows: list[dict], keys: list[str]) -> None:
    with session_scope() as db:
        for r in rows:
            upsert(db, model, r, keys)


def save_watchlist_prices(n: int, codes: list[str] | None = None) -> tuple[int, list[str]]:
    """관심종목(codes 를 주면 그 종목만) 최근 n 거래일 시세 저장."""
    from ..collectors.quotes import fetch_chain, stock_chain, to_price_rows
    total, problems = 0, []
    for code, market in _watchlist_codes(codes):
        bars, src, errs = fetch_chain(stock_chain(code, market), n + 1)
        if not bars:
            problems.append(f"{code}: " + " / ".join(errs))
            continue
        rows = to_price_rows(code, bars, src)[1:] if len(bars) > n else to_price_rows(code, bars, src)
        _save_rows(Price, rows, ["symbol", "day"])
        total += len(rows)
    return total, problems


def save_index_strip(n: int) -> tuple[int, list[str]]:
    from ..collectors.quotes import fetch_chain, index_chain, to_price_rows
    total, problems = 0, []
    for item in load_yaml("sources.yaml").get("index_strip", []):
        sym = item["symbol"] if isinstance(item, dict) else item
        bars, src, errs = fetch_chain(index_chain(item), n + 1)
        if not bars:
            problems.append(f"{sym}: " + " / ".join(errs))
            continue
        rows = to_price_rows(sym, bars, src)
        rows = rows[1:] if len(rows) > n else rows
        _save_rows(Price, rows, ["symbol", "day"])
        total += len(rows)
    return total, problems


def save_sectors() -> tuple[int, list[str]]:
    """업종 ETF 의 최근 두 거래일 종가로 등락률을 계산해 히트맵 데이터로 저장."""
    from ..collectors.quotes import fetch_chain, stock_chain
    rows, problems = [], []
    for e in load_yaml("sources.yaml").get("sector_etfs", []):
        bars, src, errs = fetch_chain(stock_chain(str(e["code"])), 3)
        if len(bars) < 2:
            problems.append(f"{e['name']}({e['code']}): " + (" / ".join(errs) or "데이터 부족"))
            continue
        last, prev = bars[-1], bars[-2]
        rows.append({"market": "ETF", "name": e["name"], "day": last["day"], "close": last["close"],
                     "change_pct": round((last["close"] / prev["close"] - 1) * 100, 2),
                     "trading_value": None, "source": src.split(":")[0], "symbol": str(e["code"])})
    _save_rows(SectorIndex, rows, ["market", "name", "day"])
    return len(rows), problems


def _raise_if_nothing(n: int, problems: list[str], what: str) -> int:
    for p in problems:
        log.warning("%s 수집 실패 %s", what, p)
    if n == 0 and problems:
        raise RuntimeError(f"{what}: 모든 소스 실패 ({problems[0][:200]})")
    return n


@tracked
def job_intraday_prices() -> int:
    """장중 5분마다 관심종목·지수 현재가 (네이버는 장중에 당일 행을 실시간으로 갱신)."""
    if not is_market_open():
        raise Skip("장 운영 시간 아님")
    n1, p1 = save_watchlist_prices(2)
    n2, p2 = save_index_strip(2)
    return _raise_if_nothing(n1 + n2, p1 + p2, "장중 시세")


@tracked
def job_daily_close() -> int:
    """장 마감 후 확정 일봉 + 지수 스트립 + 업종 히트맵."""
    if not is_trading_day(date.today()):
        raise Skip("휴장일")
    n1, p1 = save_watchlist_prices(5)
    n2, p2 = save_index_strip(5)
    n3, p3 = save_sectors()
    return _raise_if_nothing(n1 + n2 + n3, p1 + p2 + p3, "마감 시세")


@tracked
def job_backfill_prices(days: int = 130) -> int:
    """최초 실행·관심종목 추가 시: 차트용 과거 시세를 채운다 (휴장일에도 실행)."""
    n1, p1 = save_watchlist_prices(days)
    n2, p2 = save_index_strip(days)
    n3, p3 = save_sectors()
    return _raise_if_nothing(n1 + n2 + n3, p1 + p2 + p3, "과거 시세")


@tracked
def job_backfill_ticker(code: str, days: int = 130) -> int:
    """화면에서 관심종목을 새로 등록했을 때 그 종목의 과거 시세만 채운다."""
    n, problems = save_watchlist_prices(days, [code])
    return _raise_if_nothing(n, problems, f"과거 시세 {code}")


# ── 거시 지표 ──────────────────────────────────────────────────
@tracked
def job_macro() -> int:
    from ..collectors.macro import fetch_ecos, fetch_fred
    s, src = get_settings(), load_yaml("sources.yaml")
    rows = []
    if src.get("ecos", {}).get("enabled") and s.ecos_api_key:
        rows += fetch_ecos(src["ecos"]["series"])
    if src.get("fred", {}).get("enabled") and s.fred_api_key:
        rows += fetch_fred(src["fred"]["series"])
    if not rows:
        raise Skip("ECOS·FRED 키 없음 (선택 사항)")
    _save_rows(MacroSeries, rows, ["series_id", "day"])
    return len(rows)


# ── 마스터 데이터 ──────────────────────────────────────────────
def sync_watchlist() -> int:
    """tickers 의 수집 대상(in_watchlist)·보유(holding) 표시를 다시 계산한다 (빠름, 네트워크 불필요).

    수집 대상 = watchlist.yaml (계정과 무관한 기본 종목) + 모든 계정의 관심종목.
    보유 = yaml 의 holding + 어느 계정이든 보유로 표시한 종목. 중요도 가산점에 쓰인다.
    """
    wl = load_yaml("watchlist.yaml").get("watchlist", [])
    with session_scope() as db:
        for w in wl:
            upsert(db, Ticker, dict(code=str(w["code"]), name=w["name"], aliases=w.get("aliases", []),
                                    market=w.get("market")), ["code"], ["name", "aliases"])
        codes = {str(w["code"]) for w in wl}
        holds = {str(w["code"]) for w in wl if w.get("holding")}
        for code, holding in db.execute(select(UserWatchlist.ticker, UserWatchlist.holding)).all():
            codes.add(code)
            if holding:
                holds.add(code)
        db.execute(update(Ticker).where(Ticker.code.not_in(holds)).values(holding=False))
        db.execute(update(Ticker).where(Ticker.code.not_in(codes)).values(in_watchlist=False))
        db.execute(update(Ticker).where(Ticker.code.in_(codes)).values(in_watchlist=True))
        db.execute(update(Ticker).where(Ticker.code.in_(holds)).values(holding=True))
    return len(codes)


@tracked
def job_sync_tickers() -> int:
    """종목 마스터 (태깅 사전): DART 고유번호(키가 있으면) → 네이버 상장 목록 → 관심종목만.

    목록을 못 받아도 관심종목 태깅은 그대로 동작한다.
    """
    n = sync_watchlist()
    master: dict[str, dict] = {}
    with session_scope() as db:
        for code, name in db.execute(select(DartCorpCode.stock_code, DartCorpCode.corp_name)
                                     .where(DartCorpCode.stock_code.is_not(None))).all():
            master[code] = {"code": code, "name": name, "market": None}
    if not master:
        from ..collectors.quotes import naver_listing
        for market in ("KOSPI", "KOSDAQ"):
            try:
                for t in naver_listing(market):
                    master[t["code"]] = t
            except Exception as e:  # noqa: BLE001
                log.warning("%s 상장 목록 조회 실패 (관심종목만 태깅): %s", market, e)
    with session_scope() as db:
        for t in master.values():
            upsert(db, Ticker, dict(code=t["code"], name=t["name"], market=t["market"]), ["code"],
                   ["name", "market"] if t["market"] else ["name"])
    return n + len(master)


@tracked
def job_sync_dart_corp_codes() -> int:
    if not get_settings().dart_api_key:
        raise Skip("DART_API_KEY 없음 (선택 사항)")
    from ..collectors.dart import fetch_corp_codes
    rows = fetch_corp_codes()
    _save_rows(DartCorpCode, rows, ["corp_code"])
    return len(rows)


# ── 보존 정책 (저작권·용량) ────────────────────────────────────
@tracked
def job_retention() -> int:
    s = get_settings()
    now = datetime.now(timezone.utc)
    with session_scope() as db:
        n1 = db.execute(delete(ArticleBody).where(ArticleBody.expires_at < now)).rowcount or 0
        n2 = db.execute(delete(Article).where(
            Article.published_at < now - timedelta(days=s.article_retention_days))).rowcount or 0
        n3 = pipeline.close_stale_issues(db)
        db.execute(delete(JobRun).where(JobRun.started_at < now - timedelta(days=30)))
        db.execute(delete(UserSession).where(UserSession.expires_at < now))
    return n1 + n2 + n3

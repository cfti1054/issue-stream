"""APScheduler 스케줄 (Redis·Celery 없이 단일 프로세스).

`issue-stream serve` 는 API 서버 안에서 이 스케줄러를 백그라운드로 함께 돌린다.
`issue-stream scheduler` 는 스케줄러만 따로 돌릴 때 쓴다.
시세 작업은 장중/개장일 여부를 작업 안에서 판단해 건너뛴다.
"""
from __future__ import annotations

import logging
import threading

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import func, select

from . import tasks

TZ = "Asia/Seoul"
MIN_KR_TICKERS = 1000   # 코스피·코스닥은 2,500개 이상. 이보다 적으면 목록 동기화가 안 된 것으로 본다
log = logging.getLogger(__name__)


def build(cls=BlockingScheduler):
    sch = cls(timezone=TZ, job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 300})
    # 뉴스 수집 → 중복 제거 → 클러스터링 → 요약 : 10분
    sch.add_job(tasks.job_news_pipeline, IntervalTrigger(minutes=10), id="news")
    # 장중 시세 : 평일 09~15시 5분 간격 (휴장일·장외 시간은 작업 안에서 Skip)
    sch.add_job(tasks.job_intraday_prices, CronTrigger(day_of_week="mon-fri", hour="9-15", minute="*/5",
                                                       timezone=TZ), id="intraday")
    # 미국 장중 시세 : 한국 시간 22~06시 10분 간격 (서머타임·휴장일은 작업 안에서 Skip)
    sch.add_job(tasks.job_us_intraday_prices, CronTrigger(day_of_week="mon-sat", hour="22-23,0-6", minute="*/10",
                                                          timezone=TZ), id="us_intraday")
    # 장 마감 확정치·지수·업종 히트맵 : 평일 16:10 (해외 지수는 다음 날 아침 07:10 에 한 번 더)
    sch.add_job(tasks.job_daily_close, CronTrigger(day_of_week="mon-fri", hour=16, minute=10, timezone=TZ),
                id="close")
    sch.add_job(tasks.job_backfill_prices, CronTrigger(day_of_week="tue-sat", hour=7, minute=10, timezone=TZ),
                kwargs={"days": 5}, id="overseas")
    # 거시 지표 : 매일 07:30 (키가 없으면 건너뜀)
    sch.add_job(tasks.job_macro, CronTrigger(hour=7, minute=30, timezone=TZ), id="macro")
    # 종목 마스터·DART 고유번호 : 매주 월 06:00
    sch.add_job(tasks.job_sync_tickers, CronTrigger(day_of_week="mon", hour=6, timezone=TZ), id="tickers")
    sch.add_job(tasks.job_sync_dart_corp_codes, CronTrigger(day_of_week="mon", hour=6, minute=20, timezone=TZ),
                id="corp_codes")
    # 보존 정책 : 매일 03:00
    sch.add_job(tasks.job_retention, CronTrigger(hour=3, timezone=TZ), id="retention")
    return sch


def bootstrap() -> None:
    """첫 실행이나 오래 꺼져 있다 켰을 때 화면이 바로 채워지도록 필요한 작업을 한 번 돌린다."""
    from ..db.models import Price, Ticker
    from ..db.session import session_scope

    tasks.sync_watchlist()  # watchlist.yaml 변경 즉시 반영
    with session_scope() as db:
        n_tickers = db.scalar(select(func.count()).select_from(Ticker).where(Ticker.quote_code.is_(None)))
        n_us = db.scalar(select(func.count()).select_from(Ticker).where(Ticker.name_en.is_not(None)))
        wl = list(db.scalars(select(Ticker.code).where(Ticker.in_watchlist.is_(True))).all())
        have = set(db.scalars(select(Price.symbol).where(Price.symbol.in_(wl), Price.source != "demo")
                              .distinct()).all())
    if n_tickers < MIN_KR_TICKERS:   # 첫 실행이거나 지난 동기화가 실패해 관심종목 정도만 있을 때
        log.info("국내 종목 목록 %d개 → 동기화 (태깅 사전)", n_tickers)
        tasks.job_sync_tickers()
    elif not n_us:
        log.info("미국 종목 목록 동기화 (종목 검색용)")
        tasks.sync_us_tickers()
    if set(wl) - have:
        log.info("첫 실행: 과거 시세 채우기 (관심종목 %d개, 수십 초 걸릴 수 있음)", len(wl))
        tasks.job_backfill_prices()
    else:
        tasks.job_backfill_prices(days=5)
    log.info("뉴스 수집·이슈 묶기 시작")
    tasks.job_news_pipeline()
    log.info("초기 데이터 준비 완료 → http://localhost:3000")


def start_background() -> BackgroundScheduler:
    tasks.restore_api_usage()
    sch = build(BackgroundScheduler)
    sch.start()
    threading.Thread(target=_safe_bootstrap, name="bootstrap", daemon=True).start()
    return sch


def _safe_bootstrap() -> None:
    try:
        bootstrap()
    except Exception:  # noqa: BLE001
        log.exception("초기 데이터 준비 중 오류 (스케줄러는 계속 동작)")


def main() -> None:
    from ..core.logging import setup_logging
    setup_logging()
    tasks.restore_api_usage()
    _safe_bootstrap()
    build().start()

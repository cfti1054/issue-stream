"""한국거래소(KRX)·미국(NYSE/NASDAQ) 개장일·장중 판단.

기획서에 빠져 있던 항목. 시세 수집을 "장중에만" 돌리고,
주말·공휴일·연말 휴장·수능일 지연 개장에 헛수집을 하지 않기 위해 필요하다.

exchange_calendars 의 XKRX(국내)·XNYS(미국) 캘린더를 쓰고, 라이브러리가 없거나
데이터 범위를 벗어나면 평일 정규장 시간 규칙(국내 09:00~15:30, 미국 09:30~16:00 뉴욕 시간)으로 대체한다.
미국 캘린더는 서머타임·미국 공휴일을 반영한다.
"""
from __future__ import annotations

from datetime import date, datetime, time
from functools import lru_cache
from zoneinfo import ZoneInfo

import logging

KST = ZoneInfo("Asia/Seoul")
NY = ZoneInfo("America/New_York")
REGULAR_OPEN = time(9, 0)
REGULAR_CLOSE = time(15, 30)
US_OPEN = time(9, 30)
US_CLOSE = time(16, 0)

# 미국 종목의 market 값 (tickers.market). 업종 히트맵의 미국 ETF 는 "US"
US_MARKETS = ("NASDAQ", "NYSE", "AMEX")


def is_us_market(market: str | None) -> bool:
    return market in US_MARKETS or market == "US"

log = logging.getLogger(__name__)


@lru_cache
def _calendar(name: str = "XKRX"):
    try:
        import exchange_calendars as xcals

        return xcals.get_calendar(name)
    except Exception as e:  # 라이브러리 미설치 등
        log.warning("%s 캘린더를 불러오지 못해 평일 규칙으로 대체합니다: %s", name, e)
        return None


def is_us_market_open(now: datetime | None = None) -> bool:
    """미국 정규장 (뉴욕 09:30~16:00, 한국 시간으로 서머타임 22:30~05:00 / 그 외 23:30~06:00)."""
    now = (now or datetime.now(KST)).astimezone(NY)
    cal = _calendar("XNYS")
    if cal is not None:
        try:
            import pandas as pd

            return bool(cal.is_open_on_minute(pd.Timestamp(now).tz_convert("UTC")))
        except Exception:
            pass
    return now.weekday() < 5 and US_OPEN <= now.time() <= US_CLOSE


def is_trading_day(d: date) -> bool:
    cal = _calendar()
    if cal is not None:
        try:
            return bool(cal.is_session(d.isoformat()))
        except Exception:
            pass  # 캘린더 데이터 범위 밖
    return d.weekday() < 5


def is_market_open(now: datetime | None = None) -> bool:
    now = (now or datetime.now(KST)).astimezone(KST)
    cal = _calendar()
    if cal is not None:
        try:
            import pandas as pd

            return bool(cal.is_open_on_minute(pd.Timestamp(now).tz_convert("UTC")))
        except Exception:
            pass
    return is_trading_day(now.date()) and REGULAR_OPEN <= now.time() <= REGULAR_CLOSE


def previous_trading_day(d: date) -> date:
    from datetime import timedelta

    cur = d - timedelta(days=1)
    for _ in range(15):
        if is_trading_day(cur):
            return cur
        cur -= timedelta(days=1)
    return cur

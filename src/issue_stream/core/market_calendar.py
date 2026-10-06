"""한국거래소(KRX) 개장일·장중 판단.

기획서에 빠져 있던 항목. 시세 수집을 "장중에만" 돌리고,
주말·공휴일·연말 휴장·수능일 지연 개장에 헛수집을 하지 않기 위해 필요하다.

exchange_calendars 의 XKRX 캘린더를 쓰고, 라이브러리가 없거나
데이터 범위를 벗어나면 "평일 09:00~15:30" 규칙으로 대체한다.
"""
from __future__ import annotations

from datetime import date, datetime, time
from functools import lru_cache
from zoneinfo import ZoneInfo

import logging

KST = ZoneInfo("Asia/Seoul")
REGULAR_OPEN = time(9, 0)
REGULAR_CLOSE = time(15, 30)

log = logging.getLogger(__name__)


@lru_cache
def _calendar():
    try:
        import exchange_calendars as xcals

        return xcals.get_calendar("XKRX")
    except Exception as e:  # 라이브러리 미설치 등
        log.warning("XKRX 캘린더를 불러오지 못해 평일 규칙으로 대체합니다: %s", e)
        return None


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

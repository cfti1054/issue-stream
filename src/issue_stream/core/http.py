"""외부 API 호출 공통 처리: 재시도, 타임아웃, 일일 호출량 집계.

기획서에 빠져 있던 항목. DART·네이버 등 무료 API는 일일 쿼터가 있으므로
호출 수를 세어 두고(api_usage 테이블), 한도에 가까우면 수집을 건너뛴다.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import date

import httpx

log = logging.getLogger(__name__)

# 소스별 일일 한도 (보수적으로 잡음. 실제 한도는 각 서비스 콘솔에서 확인)
DAILY_LIMITS: dict[str, int] = {
    "dart": 18_000,     # OPEN DART: 계정당 일 20,000건
    "naver_search": 24_000,  # 네이버 뉴스 검색 API: 일 25,000건
    "ecos": 5_000,
    "fred": 5_000,
}

_counts: dict[tuple[str, date], int] = defaultdict(int)

# 일부 언론사·포털은 기본 파이썬 User-Agent 를 차단하므로 일반 브라우저처럼 요청한다.
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/126.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}


class QuotaExceededError(RuntimeError):
    pass


def _count(source: str) -> None:
    key = (source, date.today())
    _counts[key] += 1
    limit = DAILY_LIMITS.get(source)
    if limit and _counts[key] > limit:
        raise QuotaExceededError(f"{source} 일일 호출 한도({limit}) 도달")


def seed_usage(counts: dict[str, int]) -> None:
    """프로세스 재시작 시 DB(api_usage)에 저장된 오늘 호출 수를 다시 채운다."""
    for source, n in counts.items():
        _counts[(source, date.today())] = max(_counts[(source, date.today())], n)


def usage_today() -> dict[str, int]:
    today = date.today()
    return {s: n for (s, d), n in _counts.items() if d == today}


def get_json(source: str, url: str, *, params: dict | None = None, headers: dict | None = None,
             retries: int = 3, timeout: float = 15.0) -> dict | list:
    return _request(source, url, params=params, headers=headers, retries=retries, timeout=timeout).json()


def get_bytes(source: str, url: str, *, params: dict | None = None, headers: dict | None = None,
              retries: int = 3, timeout: float = 30.0) -> bytes:
    return _request(source, url, params=params, headers=headers, retries=retries, timeout=timeout).content


def _request(source, url, *, params, headers, retries, timeout) -> httpx.Response:
    last: Exception | None = None
    for attempt in range(1, retries + 1):
        _count(source)
        try:
            r = httpx.get(url, params=params, headers={**DEFAULT_HEADERS, **(headers or {})}, timeout=timeout,
                          follow_redirects=True)
            if r.status_code in (429, 500, 502, 503, 504):
                raise httpx.HTTPStatusError(f"HTTP {r.status_code}", request=r.request, response=r)
            r.raise_for_status()
            return r
        except (httpx.TransportError, httpx.HTTPStatusError) as e:
            if attempt == retries:
                last = e
                break
            last = e
            if isinstance(e, httpx.HTTPStatusError) and e.response.status_code in (400, 401, 403, 404):
                break  # 다시 시도해도 같은 결과
            wait = 2 ** attempt
            log.warning("%s 요청 실패 (%d/%d), %ds 후 재시도: %s", source, attempt, retries, wait, e)
            time.sleep(wait)
    raise RuntimeError(f"{source} 요청 최종 실패: {last}")

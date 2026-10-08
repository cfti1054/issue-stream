"""기사 지역(국내 kr / 미국 us / 코인 co) 판정. 대시보드 AI 요약·주요 뉴스(국내·미국만),
이슈 브리핑·시그널의 지역 탭에 쓴다.

순서대로 먼저 걸리는 규칙을 따른다.
  1) 소스가 지역을 정해 둔 경우 (sources.yaml 의 region: us — 영어 원문 피드, '뉴욕증시' 검색, 코인 검색 등)
  1-1) 태깅된 종목이 전부 코인(COIN:BTC)이거나, 주식 종목 없이 코인 단어(비트코인·가상자산…)가 있으면 → 코인
  2) 제목에 한글이 없으면 영어 원문 → 미국
  3) 국내 시장 단어(코스피·코스닥…)가 있거나 국내 종목이 태깅되면 → 국내
     ("셀트리온 美 FDA 승인", "현대차 미국 관세 우려" 처럼 미국이 나와도 국내 종목 기사는 국내)
  4) 미국 시장 단어(뉴욕증시·나스닥·연준…)가 있거나 태깅된 종목이 전부 미국 종목이면 → 미국
  5) 그 밖에는 국내
이슈의 지역은 묶인 기사들의 다수결 (동수면 국내 → 미국 → 코인 순).
"""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from functools import lru_cache

_HANGUL = re.compile(r"[가-힣]")

KR_MARKET = ("코스피", "코스닥", "국내 증시", "국내증시", "유가증권시장", "한국거래소", "원달러", "원·달러",
             "원/달러", "한국은행", "한은", "금통위")
US_MARKET = ("뉴욕증시", "뉴욕 증시", "뉴욕 주식", "미 증시", "미국 증시", "美증시", "美 증시", "나스닥", "다우지수",
             "다우존스", "S&P", "월가", "연준", "Fed", "FOMC", "파월", "미 국채", "미국 국채", "美국채", "美 국채",
             "미국 CPI", "미 CPI", "미국 고용", "빅테크", "필라델피아 반도체")
COIN_MARKET = ("비트코인", "가상자산", "가상화폐", "암호화폐", "알트코인", "코인 시장", "코인시장", "스테이블코인",
               "업비트", "빗썸", "Bitcoin", "bitcoin", "crypto", "Crypto", "BTC")
REGIONS = ("kr", "us", "co")
COIN_PREFIX = "COIN:"


def classify(title: str, source_region: str | None, tickers: Iterable[str], us_codes: set[str]) -> str:
    if source_region in REGIONS:
        return source_region
    codes = set(tickers)
    stocks = {c for c in codes if not c.startswith(COIN_PREFIX)}
    if (codes and not stocks) or (not stocks and any(k in title for k in COIN_MARKET)):
        return "co"
    if not _HANGUL.search(title):
        return "us"
    codes = stocks
    if any(k in title for k in KR_MARKET) or codes - us_codes:
        return "kr"
    if any(k in title for k in US_MARKET) or (codes and codes <= us_codes):
        return "us"
    return "kr"


def source_region(source: str) -> str | None:
    """수집기가 정해 두는 지역을 소스 이름으로 복원 (이미 저장된 기사를 다시 판정할 때)."""
    if source in ("google:us", "google:en", "yahoo"):
        return "us"
    if source in ("google:co", "google:co-en"):
        return "co"
    if source.startswith("rss:"):
        return _rss_regions().get(source)
    return None


@lru_cache
def _rss_regions() -> dict[str, str]:
    from ..core.config import load_yaml
    return {f"rss:{f['name']}": f["region"] for f in load_yaml("sources.yaml").get("rss", []) if f.get("region")}


def majority(regions: Iterable[str | None]) -> str:
    c = Counter(r or "kr" for r in regions)
    return max(REGIONS, key=lambda r: (c[r], -REGIONS.index(r)))   # 동수면 앞쪽(국내) 우선

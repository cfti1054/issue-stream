"""기사 지역(국내 kr / 미국 us) 판정. 대시보드 AI 요약·주요 뉴스·이슈 브리핑의 국내/미국 탭에 쓴다.

순서대로 먼저 걸리는 규칙을 따른다.
  1) 소스가 지역을 정해 둔 경우 (sources.yaml 의 region: us — 영어 원문 피드, '뉴욕증시' 검색 등)
  2) 제목에 한글이 없으면 영어 원문 → 미국
  3) 국내 시장 단어(코스피·코스닥…)가 있거나 국내 종목이 태깅되면 → 국내
     ("셀트리온 美 FDA 승인", "현대차 미국 관세 우려" 처럼 미국이 나와도 국내 종목 기사는 국내)
  4) 미국 시장 단어(뉴욕증시·나스닥·연준…)가 있거나 태깅된 종목이 전부 미국 종목이면 → 미국
  5) 그 밖에는 국내
이슈의 지역은 묶인 기사들의 다수결 (동수면 국내).
"""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable

_HANGUL = re.compile(r"[가-힣]")

KR_MARKET = ("코스피", "코스닥", "국내 증시", "국내증시", "유가증권시장", "한국거래소", "원달러", "원·달러",
             "원/달러", "한국은행", "한은", "금통위")
US_MARKET = ("뉴욕증시", "뉴욕 증시", "뉴욕 주식", "미 증시", "미국 증시", "美증시", "美 증시", "나스닥", "다우지수",
             "다우존스", "S&P", "월가", "연준", "Fed", "FOMC", "파월", "미 국채", "미국 국채", "美국채", "美 국채",
             "미국 CPI", "미 CPI", "미국 고용", "빅테크", "필라델피아 반도체")


def classify(title: str, source_region: str | None, tickers: Iterable[str], us_codes: set[str]) -> str:
    if source_region in ("kr", "us"):
        return source_region
    if not _HANGUL.search(title):
        return "us"
    codes = set(tickers)
    if any(k in title for k in KR_MARKET) or codes - us_codes:
        return "kr"
    if any(k in title for k in US_MARKET) or (codes and codes <= us_codes):
        return "us"
    return "kr"


def majority(regions: Iterable[str | None]) -> str:
    c = Counter(r or "kr" for r in regions)
    return "us" if c["us"] > c["kr"] else "kr"

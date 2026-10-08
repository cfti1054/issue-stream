"""파이프라인 단계 사이에서 주고받는 데이터 형태.

수집기는 소스가 무엇이든 RawDoc 리스트를 반환하고,
요약기는 provider가 무엇이든 IssueSummary를 반환한다.
이 두 계약만 지키면 소스·모델을 바꿔도 파이프라인 코드는 그대로다.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Sentiment = Literal["positive", "neutral", "negative"]
DocKind = Literal["news", "disclosure"]


class RawDoc(BaseModel):
    source: str                       # "rss:한국경제 증권", "dart", "naver" ...
    kind: DocKind = "news"
    external_id: str                  # 소스 내 고유 ID (URL, 접수번호 등)
    title: str
    url: str
    publisher: str | None = None
    published_at: datetime
    snippet: str | None = None        # RSS description / 검색 스니펫 (짧은 요약문)
    body: str | None = None           # FETCH_ARTICLE_BODY=true 일 때만. 저장 시 TTL 적용.
    raw_tickers: list[str] = Field(default_factory=list)  # 소스가 직접 준 종목코드(DART 등)
    region: Literal["kr", "us", "co"] | None = None  # 소스가 정해 둔 지역(co 코인). None 이면 pipeline/region.py 가 판정


class IssueSummary(BaseModel):
    headline: str
    bullets: list[str] = Field(default_factory=list, max_length=5)
    sentiment: Sentiment = "neutral"
    affected_tickers: list[str] = Field(default_factory=list)
    confidence: float = Field(0.5, ge=0.0, le=1.0)
    conflicting_views: bool = False
    source_article_ids: list[str] = Field(default_factory=list)
    generated_by: str = "extractive"  # 어떤 provider가 만들었는지 (화면에 표시·비교용)
    # 시그널 화면용 (pipeline/topics.py). 이 필드가 생기기 전에 만든 요약에는 없어서 화면이 규칙으로 채운다.
    category: str | None = None       # 주제 (topics.ALL_CATEGORIES 중 하나)
    keywords: list[str] = Field(default_factory=list)   # 짧은 키워드 2~3개
    reason: str | None = None         # 대표 종목이 움직인 이유 한 줄 ("AI칩 자금조달 논의로")

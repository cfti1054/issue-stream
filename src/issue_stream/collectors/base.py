"""수집기 공통 인터페이스.

모든 뉴스·공시 수집기는 fetch(since) -> list[RawDoc] 하나만 구현한다.
새 소스를 추가할 때는 이 클래스를 상속한 파일을 만들고 enabled_collectors()에 등록하면 끝.
"""
from __future__ import annotations

import html
import re
from abc import ABC, abstractmethod
from datetime import datetime

from ..core.schemas import RawDoc


class Collector(ABC):
    name: str = "base"

    @abstractmethod
    def fetch(self, since: datetime) -> list[RawDoc]:
        ...


_TAG = re.compile(r"<[^>]+>")


def clean_text(s: str | None) -> str:
    """HTML 태그·엔티티 제거 (네이버 API의 <b> 태그, RSS description 등)."""
    if not s:
        return ""
    return re.sub(r"\s+", " ", html.unescape(_TAG.sub("", s))).strip()


def enabled_collectors() -> list[Collector]:
    """config/sources.yaml 과 .env 키 유무를 보고 켜진 수집기만 반환."""
    from ..core.config import get_settings, load_yaml
    from .dart import DartCollector
    from .google_news import GoogleNewsCollector
    from .naver_news import NaverNewsCollector
    from .rss import RssCollector

    s = get_settings()
    src = load_yaml("sources.yaml")
    out: list[Collector] = []

    for feed in src.get("rss", []):
        if feed.get("enabled"):
            out.append(RssCollector(feed["name"], feed["url"]))

    g = src.get("google_news", {})
    if g.get("enabled", True):
        out.append(GoogleNewsCollector(extra_queries=g.get("extra_queries", []),
                                       per_ticker=g.get("per_ticker", True), window=g.get("window", "1d")))

    naver = src.get("naver_news", {})
    if naver.get("enabled") and s.naver_client_id:
        out.append(NaverNewsCollector(extra_keywords=naver.get("extra_keywords", []),
                                      display=naver.get("display", 50)))

    if s.dart_api_key:
        out.append(DartCollector())

    return out

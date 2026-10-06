"""구글 뉴스 RSS 검색 (무료, 키 불필요).

네이버 뉴스 검색 API(키 필요)의 무료 대안. 관심종목 이름과 추가 키워드로 최근 1일 기사를 찾는다.
여러 언론사의 기사가 한곳에 모여 이슈 클러스터링(같은 사건 묶기)에 특히 유용하다.
링크는 news.google.com 을 거쳐 원문으로 이동한다.
"""
from __future__ import annotations

import calendar
from datetime import datetime, timezone
from urllib.parse import quote

import feedparser

from ..core.config import load_yaml
from ..core.http import get_bytes
from ..core.schemas import RawDoc
from .base import Collector, clean_text

URL = "https://news.google.com/rss/search?q={q}&hl=ko&gl=KR&ceid=KR:ko"


def split_publisher(title: str, publisher: str | None) -> tuple[str, str | None]:
    """구글 뉴스 제목은 '기사 제목 - 매체명' 형태라 매체명을 떼어낸다."""
    if publisher and title.endswith(f" - {publisher}"):
        return title[: -len(publisher) - 3].strip(), publisher
    if " - " in title:
        head, tail = title.rsplit(" - ", 1)
        if 0 < len(tail) <= 20:
            return head.strip(), publisher or tail.strip()
    return title, publisher


class GoogleNewsCollector(Collector):
    name = "google"

    def __init__(self, extra_queries: list[str] | None = None, per_ticker: bool = True, window: str = "1d"):
        self.extra = extra_queries or []
        self.per_ticker = per_ticker
        self.window = window

    def queries(self) -> list[str]:
        qs = []
        if self.per_ticker:
            qs += [f'"{w["name"]}"' for w in load_yaml("watchlist.yaml").get("watchlist", [])]
        return qs + list(self.extra)

    def fetch(self, since: datetime) -> list[RawDoc]:
        docs: dict[str, RawDoc] = {}
        for q in self.queries():
            feed = feedparser.parse(get_bytes("google", URL.format(q=quote(f"{q} when:{self.window}"))))
            for e in feed.entries:
                ts = e.get("published_parsed") or e.get("updated_parsed")
                published = datetime.fromtimestamp(calendar.timegm(ts), tz=timezone.utc) if ts else None
                if published is None or published < since:
                    continue
                src = e.get("source") or {}
                title, publisher = split_publisher(clean_text(e.get("title")), src.get("title"))
                ext = e.get("id") or e.get("link")
                if not ext or not title:
                    continue
                docs[ext] = RawDoc(source=self.name, external_id=ext[:500], title=title, url=e.get("link", ""),
                                   publisher=publisher, published_at=published, snippet=None)
        return list(docs.values())

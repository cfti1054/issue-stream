"""네이버 뉴스 검색 API (무료, 일 25,000회). 제목·스니펫만 제공, 본문 없음."""
from __future__ import annotations

from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

from ..core.config import get_settings
from ..core.http import get_json
from ..core.schemas import RawDoc
from .base import Collector, clean_text, watchlist_names

API = "https://openapi.naver.com/v1/search/news.json"


class NaverNewsCollector(Collector):
    name = "naver"

    def __init__(self, extra_keywords: list[str], display: int = 50):
        self.extra_keywords = extra_keywords
        self.display = min(display, 100)

    def _queries(self) -> list[str]:
        return watchlist_names() + list(self.extra_keywords)

    def fetch(self, since: datetime) -> list[RawDoc]:
        s = get_settings()
        headers = {"X-Naver-Client-Id": s.naver_client_id, "X-Naver-Client-Secret": s.naver_client_secret}
        docs: dict[str, RawDoc] = {}
        for q in self._queries():
            data = get_json("naver_search", API, params={"query": q, "display": self.display, "sort": "date"},
                            headers=headers)
            for it in data.get("items", []):
                published = parsedate_to_datetime(it["pubDate"])
                if published < since:
                    continue
                # originallink = 언론사 원문, link = 네이버 뉴스 링크
                url = it.get("originallink") or it["link"]
                docs[url] = RawDoc(
                    source=self.name,
                    external_id=url,
                    title=clean_text(it["title"]),
                    url=url,
                    publisher=urlparse(url).netloc.removeprefix("www."),
                    published_at=published,
                    snippet=clean_text(it.get("description")) or None,
                )
        return list(docs.values())

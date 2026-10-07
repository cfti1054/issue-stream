from __future__ import annotations

import calendar
from datetime import datetime, timezone

import feedparser

from ..core.http import get_bytes
from ..core.schemas import RawDoc
from .base import Collector, clean_text


class RssCollector(Collector):
    def __init__(self, feed_name: str, url: str, region: str | None = None):
        self.name = f"rss:{feed_name}"
        self.publisher = feed_name.split()[0]
        self.url = url
        self.region = region   # sources.yaml 의 region (us = 미국 시장 피드). 없으면 기사마다 판정

    def fetch(self, since: datetime) -> list[RawDoc]:
        parsed = feedparser.parse(get_bytes("rss", self.url))
        docs: list[RawDoc] = []
        for e in parsed.entries:
            ts = e.get("published_parsed") or e.get("updated_parsed")
            published = (datetime.fromtimestamp(calendar.timegm(ts), tz=timezone.utc)
                         if ts else datetime.now(timezone.utc))
            if published < since:
                continue
            link = e.get("link", "")
            docs.append(RawDoc(
                source=self.name,
                external_id=e.get("id") or link,
                title=clean_text(e.get("title")),
                url=link,
                publisher=self.publisher,
                published_at=published,
                # description은 매체가 공개한 짧은 요약. 400자로 잘라 저장.
                snippet=clean_text(e.get("summary"))[:400] or None,
                region=self.region,
            ))
        return docs

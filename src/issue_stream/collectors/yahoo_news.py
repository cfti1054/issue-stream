"""야후 파이낸스 종목별 헤드라인 RSS (무료, 키 불필요, 영어).

미국 관심종목(누군가 ☆ 한 NASDAQ·NYSE·AMEX 종목)마다 최근 영어 헤드라인을 받는다.
요청 수가 종목 수만큼 늘어나므로 max_tickers 로 상한을 둔다.
"""
from __future__ import annotations

import calendar
from datetime import datetime, timezone

import feedparser

from ..core.http import get_bytes
from ..core.schemas import RawDoc
from .base import Collector, clean_text, us_watch_symbols

URL = "https://feeds.finance.yahoo.com/rss/2.0/headline?s={sym}&region=US&lang=en-US"


class YahooTickerNewsCollector(Collector):
    name = "yahoo"

    def __init__(self, max_tickers: int = 30):
        self.max_tickers = max_tickers

    def fetch(self, since: datetime) -> list[RawDoc]:
        docs: dict[str, RawDoc] = {}
        for sym in us_watch_symbols()[: self.max_tickers]:
            feed = feedparser.parse(get_bytes("yahoo_rss", URL.format(sym=sym.replace(".", "-"))))
            for e in feed.entries:
                ts = e.get("published_parsed") or e.get("updated_parsed")
                published = datetime.fromtimestamp(calendar.timegm(ts), tz=timezone.utc) if ts else None
                link = e.get("link", "")
                title = clean_text(e.get("title"))
                if published is None or published < since or not link or not title:
                    continue
                docs[link] = RawDoc(source=self.name, external_id=(e.get("id") or link)[:500], title=title,
                                    url=link, publisher="Yahoo Finance", published_at=published,
                                    snippet=clean_text(e.get("summary"))[:400] or None,
                                    raw_tickers=[sym], region="us")
        return list(docs.values())

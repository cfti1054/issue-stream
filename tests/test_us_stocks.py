"""미국 종목: 시세 체인·네이버 해외주식 파싱·장 운영 시간 (네트워크 없이)."""
from datetime import date, datetime

from issue_stream.collectors import quotes
from issue_stream.core.market_calendar import KST, is_us_market, is_us_market_open


def test_us_stock_chain_uses_world_api_then_yahoo():
    assert quotes.stock_chain("NVDA", "NASDAQ", "NVDA.O") == ["naver:world:NVDA.O", "yahoo:NVDA", "fdr:NVDA"]
    assert quotes.stock_chain("BRK.B", "NYSE", "BRK.B")[1] == "yahoo:BRK-B"
    assert quotes.stock_chain("005930", "KOSPI")[0] == "naver:stock:005930"
    assert is_us_market("NYSE") and is_us_market("US") and not is_us_market("KOSDAQ") and not is_us_market(None)


def test_naver_world_parses_daily_candles(monkeypatch):
    seen = {}

    def fake_get_json(source, url, params=None, **_):
        seen["url"], seen["params"] = url, params
        return [{"localDate": "20261005", "closePrice": 237.1, "openPrice": 235.0, "highPrice": 238.0,
                 "lowPrice": 234.2, "accumulatedTradingVolume": 1000},
                {"localDate": "20261006", "closePrice": 239.24, "openPrice": 237.0, "highPrice": 240.1,
                 "lowPrice": 236.5, "accumulatedTradingVolume": 2000}]
    monkeypatch.setattr(quotes, "get_json", fake_get_json)
    bars = quotes.fetch("naver:world:NVDA.O", 5)
    assert seen["url"].endswith("/chart/foreign/item/NVDA.O/day")
    assert [b["day"] for b in bars] == [date(2026, 10, 5), date(2026, 10, 6)] and bars[-1]["close"] == 239.24


def test_naver_world_listing_keeps_quote_code(monkeypatch):
    page = {"stocks": [{"symbolCode": "NVDA", "reutersCode": "NVDA.O", "stockName": "엔비디아"},
                       {"symbolCode": "JPM", "reutersCode": "JPM", "stockName": "제이피모간체이스"},
                       {"symbolCode": None, "reutersCode": "X", "stockName": "skip"}]}
    monkeypatch.setattr(quotes, "get_json", lambda *a, **k: page)
    got = quotes.naver_world_listing("NASDAQ", max_pages=3)
    assert got == [{"code": "NVDA", "name": "엔비디아", "market": "NASDAQ", "quote_code": "NVDA.O"},
                   {"code": "JPM", "name": "제이피모간체이스", "market": "NASDAQ", "quote_code": "JPM"}]


def test_us_market_hours_follow_dst_and_holidays():
    kst = lambda s: datetime.fromisoformat(s).replace(tzinfo=KST)  # noqa: E731
    assert is_us_market_open(kst("2026-10-07 22:40"))          # 서머타임: 22:30 개장
    assert not is_us_market_open(kst("2026-12-08 23:00"))      # 표준시: 23:30 개장
    assert is_us_market_open(kst("2026-12-08 23:40"))
    assert not is_us_market_open(kst("2026-10-10 23:40"))      # 토요일
    assert not is_us_market_open(kst("2026-11-26 23:40"))      # 추수감사절

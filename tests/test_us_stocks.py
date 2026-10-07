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
    page = {"stocks": [{"symbolCode": "NVDA", "reutersCode": "NVDA.O", "stockName": "엔비디아",
                        "stockNameEng": "NVIDIA Corporation"},
                       {"symbolCode": "JPM", "reutersCode": "JPM", "stockName": "제이피모간체이스"},
                       {"symbolCode": None, "reutersCode": "X", "stockName": "skip"}]}
    monkeypatch.setattr(quotes, "get_json", lambda *a, **k: page)
    got = quotes.naver_world_listing("NASDAQ", max_pages=3)
    assert got == [{"code": "NVDA", "name": "엔비디아", "market": "NASDAQ", "quote_code": "NVDA.O", "name_en": "NVIDIA"},
                   {"code": "JPM", "name": "제이피모간체이스", "market": "NASDAQ", "quote_code": "JPM", "name_en": None}]


def test_us_market_hours_follow_dst_and_holidays():
    kst = lambda s: datetime.fromisoformat(s).replace(tzinfo=KST)  # noqa: E731
    assert is_us_market_open(kst("2026-10-07 22:40"))          # 서머타임: 22:30 개장
    assert not is_us_market_open(kst("2026-12-08 23:00"))      # 표준시: 23:30 개장
    assert is_us_market_open(kst("2026-12-08 23:40"))
    assert not is_us_market_open(kst("2026-10-10 23:40"))      # 토요일
    assert not is_us_market_open(kst("2026-11-26 23:40"))      # 추수감사절


def test_english_company_name_drops_legal_suffixes():
    from issue_stream.collectors.quotes import english_name
    assert english_name("NVIDIA Corporation") == "NVIDIA"
    assert english_name("Alphabet Inc Class A") == "Alphabet"
    assert english_name("Apple Inc.") == "Apple"
    assert english_name("Taiwan Semiconductor Manufacturing Co Ltd ADR") == "Taiwan Semiconductor Manufacturing"


def test_region_rules():
    from issue_stream.pipeline.region import classify, majority
    us = {"NVDA", "AAPL"}
    assert classify("Stocks rally as Nasdaq hits record", None, [], us) == "us"          # 영어 원문
    assert classify("코스피 하락", "us", [], us) == "us"                                 # 소스 지정이 우선
    assert classify("뉴욕증시, 나스닥 사상 최고치", None, [], us) == "us"
    assert classify("나스닥 급락에 코스피도 하락", None, [], us) == "kr"                  # 국내 시장 단어 우선
    assert classify("셀트리온 美 FDA 바이오시밀러 승인", None, ["068270"], us) == "kr"    # 국내 종목 기사
    assert classify("현대차 미국 관세 우려", None, ["005380"], us) == "kr"
    assert classify("엔비디아 신고가", None, ["NVDA"], us) == "us"                        # 미국 종목만
    assert classify("SK하이닉스, 엔비디아 공급 확대", None, ["000660", "NVDA"], us) == "kr"
    assert classify("반도체 업황 개선", None, [], us) == "kr"
    assert majority(["us", "us", "kr"]) == "us" and majority(["us", "kr"]) == "kr"


def test_english_sentiment_uses_word_boundaries():
    from issue_stream.providers.sentiment import LexiconSentiment
    got = LexiconSentiment().classify([
        "Nvidia shares surge to record high after earnings beat",
        "Stocks tumble as recession fears grow",
        "Enterprise software company announces new CEO",     # 'rise' 가 enterprise 에 걸리면 안 됨
        "삼성전자 신고가 돌파",
    ])
    assert got == ["positive", "negative", "neutral", "positive"]


def test_tagger_matches_english_names_case_insensitively():
    from issue_stream.pipeline.tagging import TickerEntry, TickerTagger
    t = TickerTagger([TickerEntry("NVDA", ("엔비디아", "NVIDIA", "NVDA")), TickerEntry("META", ("메타", "Meta", "META")),
                      TickerEntry("005930", ("삼성전자",))])
    assert t.tag("Nvidia and nvda rally; 엔비디아 강세") == {"NVDA": 3}
    assert t.tag("Metal prices rise, metaverse hype") == {}                  # 단어 일부는 제외
    assert t.tag("Meta's AI push, 삼성전자도 상승") == {"META": 1, "005930": 1}

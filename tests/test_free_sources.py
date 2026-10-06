"""무료 소스 파서 단위 테스트 (네트워크 없이)."""
from datetime import date

import pytest

from issue_stream.collectors.google_news import split_publisher
from issue_stream.collectors.quotes import (
    _rows, fetch_chain, index_chain, naver_bar, num, parse_day, stock_chain, to_price_rows,
)


def test_num_and_day_parsing():
    assert num("1,234.50") == 1234.5 and num("-0.31%") == -0.31 and num("-") is None
    assert parse_day("2026-10-02") == date(2026, 10, 2)
    assert parse_day("20261002") == date(2026, 10, 2)
    assert parse_day("2026-10-02T15:30:00+09:00") == date(2026, 10, 2)


def test_naver_row_shapes():
    row = {"localTradedAt": "2026-10-02", "closePrice": "95,700", "openPrice": "96,000",
           "highPrice": "97,100", "lowPrice": "95,200", "accumulatedTradingVolume": "12,345,678"}
    b = naver_bar(row)
    assert b["close"] == 95700 and b["volume"] == 12345678 and b["day"] == date(2026, 10, 2)
    assert naver_bar({"closePrice": "1"}) is None                      # 날짜 없으면 버림
    assert len(_rows([row])) == 1
    assert len(_rows({"result": [row, row]})) == 2
    assert len(_rows({"result": {"items": [row]}})) == 1


def test_price_rows_change_pct():
    bars = [{"day": date(2026, 9, 30), "close": 100.0, "open": None, "high": None, "low": None, "volume": None},
            {"day": date(2026, 10, 1), "close": 103.0, "open": None, "high": None, "low": None, "volume": None}]
    rows = to_price_rows("X", bars, "naver:stock:X")
    assert rows[0]["change_pct"] is None and rows[1]["change_pct"] == 3.0 and rows[1]["source"] == "naver"


def test_chains_prefer_keyless_sources():
    assert stock_chain("005930")[0] == "naver:stock:005930"
    assert stock_chain("035720", "KOSDAQ")[1] == "yahoo:035720.KQ"
    assert index_chain({"symbol": "KS11"})[0] == "naver:index:KOSPI"
    assert index_chain({"symbol": "US500"})[0] == "yahoo:^GSPC"
    assert index_chain({"symbol": "X", "sources": ["fdr:X"]}) == ["fdr:X"]


def test_chain_falls_through(monkeypatch):
    import issue_stream.collectors.quotes as q

    def fake(src, n):
        if src.startswith("naver"):
            raise RuntimeError("blocked")
        return [{"day": date(2026, 10, 2), "close": 1.0, "open": None, "high": None, "low": None, "volume": None}]
    monkeypatch.setattr(q, "fetch", fake)
    bars, used, errs = fetch_chain(["naver:stock:1", "yahoo:1.KS"], 5)
    assert used == "yahoo:1.KS" and len(errs) == 1 and bars


@pytest.mark.parametrize("title,pub,expect", [
    ("삼성전자 실적 발표 - 한국경제", "한국경제", ("삼성전자 실적 발표", "한국경제")),
    ("코스피 2,700 회복 - 연합뉴스", None, ("코스피 2,700 회복", "연합뉴스")),
    ("제목에 - 하이픈이 있는 아주 긴 기사 제목입니다 정말 길어요 길어요", None,
     ("제목에 - 하이픈이 있는 아주 긴 기사 제목입니다 정말 길어요 길어요", None)),
])
def test_google_title_split(title, pub, expect):
    assert split_publisher(title, pub) == expect


def test_stale_source_is_skipped(monkeypatch):
    """KRX 로그인 문제로 갱신이 멈춘 캐시(예: 9/17 이후)는 건너뛰고 다음 소스를 쓴다."""
    from datetime import timedelta

    import issue_stream.collectors.quotes as q

    def fake(src, n):
        d = date.today() - timedelta(days=15 if src.startswith("fdr") else 1)
        return [{"day": d, "close": 1.0, "open": None, "high": None, "low": None, "volume": None}]
    monkeypatch.setattr(q, "fetch", fake)
    bars, used, errs = fetch_chain(["fdr:KS11", "yahoo:^KS11"], 5)
    assert used == "yahoo:^KS11" and "오래된 데이터" in errs[0]
    _, used, errs = fetch_chain(["fdr:KS11"], 5)
    assert used is None


def test_breaker_skips_repeatedly_failing_provider(monkeypatch):
    import issue_stream.collectors.quotes as q
    q.reset_breaker()
    calls = []

    def fake(src, n):
        calls.append(src)
        if src.startswith("naver"):
            raise RuntimeError("blocked")
        return [{"day": date.today(), "close": 1.0, "open": None, "high": None, "low": None, "volume": None}]
    monkeypatch.setattr(q, "fetch", fake)
    for i in range(5):
        fetch_chain([f"naver:stock:{i}", f"yahoo:{i}.KS"], 3)
    assert sum(c.startswith("naver") for c in calls) == q.BREAKER_FAILS   # 3번 실패 후 건너뜀
    q.reset_breaker()

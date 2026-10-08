"""시세 수집 (무료, 키·로그인 불필요).

KRX 정보데이터시스템은 2024-12 부터 로그인이 필요해 pykrx·FinanceDataReader 의 KRX 기반 기능이
막혔다. 그래서 다음 순서로 시도하고, 처음 성공한 소스를 쓴다.

  1) 네이버 증권 API (국내 종목·코스피/코스닥·환율, 미국 종목은 해외주식 API)
  2) 야후 파이낸스 (yfinance)  — 해외 지수, 국내 종목 대체
  3) FinanceDataReader        — 마지막 대체

소스 표기:  "naver:stock:005930", "naver:world:NVDA.O", "naver:index:KOSPI", "naver:worldindex:.INX",
           "naver:fx:FX_USDKRW", "naver:metal:M04020000"(KRX 금현물),
           "yahoo:^GSPC", "fdr:US500"
           "*100" 을 붙이면 값에 곱한다 (예: "yahoo:JPYKRW=X*100" → 1엔당 시세를 100엔당으로).
미국 종목은 tickers.code 가 티커(NVDA), tickers.quote_code 가 네이버 조회 코드(NVDA.O, NYSE 는 대개 접미사 없음).
`issue-stream doctor` 로 PC 에서 각 소스가 실제로 응답하는지 확인할 수 있다.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import date, datetime, timedelta
from typing import TypedDict

from ..core.http import get_json
from ..core.market_calendar import US_MARKETS, is_us_market

log = logging.getLogger(__name__)

NAVER = "https://m.stock.naver.com"
NAVER_WORLD = "https://api.stock.naver.com"
PAGE = 60


class Bar(TypedDict):
    day: date
    open: float | None
    high: float | None
    low: float | None
    close: float
    volume: float | None


# ── 파싱 도우미 (응답 형식이 조금 바뀌어도 견디도록) ───────────
def num(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(",", "").replace("%", "").strip()
    if s in ("", "-", "N/A"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_day(v) -> date | None:
    if v is None:
        return None
    s = str(v).strip()
    for fmt, n in (("%Y-%m-%d", 10), ("%Y%m%d", 8), ("%Y.%m.%d", 10)):
        try:
            return datetime.strptime(s[:n], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _first(d: dict, *keys):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None


def _rows(payload) -> list[dict]:
    """[...] / {"result": [...]} / {"result": {"items": [...]}} 등 여러 모양을 리스트로."""
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        for k in ("result", "items", "priceInfos", "prices", "data", "stocks"):
            if k in payload:
                return _rows(payload[k])
    return []


def naver_bar(r: dict) -> Bar | None:
    day = parse_day(_first(r, "localTradedAt", "localTradeAt", "localDate", "tradeDate", "date", "bizdate"))
    close = num(_first(r, "closePrice", "close", "tradePrice", "price"))
    if day is None or close is None:
        return None
    return Bar(day=day, close=close,
               open=num(_first(r, "openPrice", "open")),
               high=num(_first(r, "highPrice", "high")),
               low=num(_first(r, "lowPrice", "low")),
               volume=num(_first(r, "accumulatedTradingVolume", "volume", "tradingVolume")))


def _dedupe_sort(bars: list[Bar]) -> list[Bar]:
    by_day = {b["day"]: b for b in bars}
    return [by_day[d] for d in sorted(by_day)]


# ── 1) 네이버 ─────────────────────────────────────────────────
def _naver_paged(path: str, n: int, extra: dict | None = None, base: str = NAVER) -> list[Bar]:
    bars: list[Bar] = []
    for page in range(1, 10):
        params = {"pageSize": PAGE, "page": page, **(extra or {})}
        rows = _rows(get_json("naver", f"{base}{path}", params=params, retries=2))
        if not rows:
            break
        bars += [b for b in (naver_bar(r) for r in rows) if b]
        if len(bars) >= n or len(rows) < PAGE:
            break
    return _dedupe_sort(bars)[-n:]


def naver(kind: str, code: str, n: int) -> list[Bar]:
    if kind == "stock":
        return _naver_paged(f"/api/stock/{code}/price", n)
    if kind == "index":
        return _naver_paged(f"/api/index/{code}/price", n)
    if kind == "fx":
        # 원화 환율(하나은행 고시 매매기준율). 엔화는 100엔당. 2026-10 기존 front-api/v1 경로가 404 로 바뀜
        return _naver_paged(f"/marketindex/exchange/{code}/prices", n, base=NAVER_WORLD)
    if kind == "metal":
        # 국내 금 시세 (M04020000 = KRX 금현물, 원/g)
        return _naver_paged(f"/marketindex/metals/{code}/prices", n, base=NAVER_WORLD)
    if kind == "world":
        return naver_world(code, n)
    if kind == "worldindex":
        return naver_world(code, n, "index")
    raise ValueError(kind)


def naver_world(quote_code: str, n: int, kind: str = "item") -> list[Bar]:
    """미국 등 해외 종목(item)·지수(index, 예: .INX) 일봉. 장중에는 당일 봉이 현재가로 갱신된다."""
    end = date.today() + timedelta(days=1)
    start = date.today() - timedelta(days=int(n * 1.6) + 10)
    rows = _rows(get_json("naver", f"{NAVER_WORLD}/chart/foreign/{kind}/{quote_code}/day",
                          params={"startDateTime": start.strftime("%Y%m%d0000"),
                                  "endDateTime": end.strftime("%Y%m%d0000")}, retries=2))
    return _dedupe_sort([b for b in (naver_bar(r) for r in rows) if b])[-n:]


# ── 2) 야후 ───────────────────────────────────────────────────
def yahoo(symbol: str, n: int) -> list[Bar]:
    import yfinance as yf

    days = max(10, int(n * 1.6) + 7)
    df = yf.Ticker(symbol).history(period=f"{days}d", interval="1d", auto_adjust=False)
    return _df_bars(df)[-n:]


# ── 3) FinanceDataReader ─────────────────────────────────────
def fdr(symbol: str, n: int) -> list[Bar]:
    import FinanceDataReader as fdr_

    df = fdr_.DataReader(symbol, date.today() - timedelta(days=int(n * 1.6) + 7))
    return _df_bars(df)[-n:]


def _df_bars(df) -> list[Bar]:
    out: list[Bar] = []
    if df is None or len(df) == 0:
        return out
    for idx, r in df.iterrows():
        close = num(r.get("Close"))
        if close is None or close != close:  # NaN
            continue
        out.append(Bar(day=idx.date() if hasattr(idx, "date") else parse_day(idx), close=close,
                       open=num(r.get("Open")), high=num(r.get("High")), low=num(r.get("Low")),
                       volume=num(r.get("Volume"))))
    return _dedupe_sort(out)


# ── 체인 ─────────────────────────────────────────────────────
def fetch(source: str, n: int) -> list[Bar]:
    source, _, mul = source.partition("*")
    bars = _fetch(source, n)
    if mul:
        k = float(mul)
        for b in bars:
            for f in ("open", "high", "low", "close"):
                if b[f] is not None:
                    b[f] *= k
    return bars


def _fetch(source: str, n: int) -> list[Bar]:
    parts = source.split(":", 2)
    if parts[0] == "naver":
        return naver(parts[1], parts[2], n)
    if parts[0] == "yahoo":
        return yahoo(parts[1], n)
    if parts[0] == "fdr":
        return fdr(parts[1], n)
    raise ValueError(f"알 수 없는 시세 소스: {source}")


# 연속으로 실패한 공급자(네이버·야후·FDR)는 잠시 건너뛴다. 네트워크가 막힌 환경에서
# 수십 개 종목이 매번 모든 공급자를 재시도하며 몇 분씩 걸리는 것을 막는다.
BREAKER_FAILS = 3
BREAKER_COOLDOWN = 600  # 초
_fails: dict[str, tuple[int, float]] = {}


def _provider(src: str) -> str:
    return src.split(":", 1)[0]


def _tripped(src: str) -> bool:
    n, last = _fails.get(_provider(src), (0, 0.0))
    if n >= BREAKER_FAILS and time.monotonic() - last < BREAKER_COOLDOWN:
        return True
    if n >= BREAKER_FAILS:
        _fails.pop(_provider(src), None)  # 쿨다운 끝, 다시 시도
    return False


def _record(src: str, ok: bool) -> None:
    p = _provider(src)
    if ok:
        _fails.pop(p, None)
    else:
        n, _ = _fails.get(p, (0, 0.0))
        _fails[p] = (n + 1, time.monotonic())


def reset_breaker() -> None:
    _fails.clear()


MAX_AGE_DAYS = 10  # 추석·설 연휴(최대 6~7일)를 넘겨도 갱신이 없으면 '멈춘 소스'로 본다


def fetch_chain(chain: list[str], n: int, max_age_days: int = MAX_AGE_DAYS
                ) -> tuple[list[Bar], str | None, list[str]]:
    """(봉 목록, 성공한 소스, 실패 사유들).

    마지막 봉이 max_age_days 보다 오래된 소스는 '멈춘 데이터'로 보고 다음 소스로 넘어간다
    (예: KRX 로그인 문제로 2026-09-17 이후 갱신이 멈춘 FinanceDataReader 지수 캐시).
    """
    errors = []
    oldest_ok = date.today() - timedelta(days=max_age_days)
    for src in chain:
        if _tripped(src):
            errors.append(f"{src}: 최근 연속 실패로 잠시 건너뜀")
            continue
        try:
            bars = fetch(src, n)
            _record(src, True)
            if bars and bars[-1]["day"] < oldest_ok:
                errors.append(f"{src}: 오래된 데이터({bars[-1]['day']} 이후 갱신 없음)")
                continue
            if bars:
                return bars, src, errors
            errors.append(f"{src}: 빈 응답")
        except Exception as e:  # noqa: BLE001 - 어떤 실패든 다음 소스로
            _record(src, False)
            errors.append(f"{src}: {type(e).__name__}: {str(e)[:120]}")
    return [], None, errors


def stock_chain(code: str, market: str | None = None, quote_code: str | None = None) -> list[str]:
    if is_us_market(market):
        # 야후는 클래스 주식을 BRK-B 처럼 쓴다
        return [f"naver:world:{quote_code or code}", f"yahoo:{code.replace('.', '-')}", f"fdr:{code}"]
    yh = [f"yahoo:{code}.KQ", f"yahoo:{code}.KS"] if market == "KOSDAQ" else [f"yahoo:{code}.KS", f"yahoo:{code}.KQ"]
    return [f"naver:stock:{code}", *yh, f"fdr:{code}"]


# 지수 스트립 기본 체인 (sources.yaml 에서 sources: 로 덮어쓸 수 있다)
INDEX_CHAINS: dict[str, list[str]] = {
    "KS11": ["naver:index:KOSPI", "yahoo:^KS11", "fdr:KS11"],
    "KQ11": ["naver:index:KOSDAQ", "yahoo:^KQ11", "fdr:KQ11"],
    "US500": ["naver:worldindex:.INX", "yahoo:^GSPC", "fdr:US500"],
    "IXIC": ["naver:worldindex:.IXIC", "yahoo:^IXIC", "fdr:IXIC"],
    "DJI": ["naver:worldindex:.DJI", "yahoo:^DJI", "fdr:DJI"],
    "USD/KRW": ["naver:fx:FX_USDKRW", "yahoo:KRW=X", "fdr:USD/KRW"],
    # 환율 화면 (sources.yaml fx_rates). 원화 환율은 네이버(하나은행 고시) → 야후, 해외 교차 환율은 야후
    "JPY/KRW": ["naver:fx:FX_JPYKRW", "yahoo:JPYKRW=X*100"],   # 100엔당
    "EUR/KRW": ["naver:fx:FX_EURKRW", "yahoo:EURKRW=X"],
    "CNY/KRW": ["naver:fx:FX_CNYKRW", "yahoo:CNYKRW=X"],
    "GBP/KRW": ["naver:fx:FX_GBPKRW", "yahoo:GBPKRW=X"],
    "EUR/USD": ["yahoo:EURUSD=X", "fdr:EUR/USD"],
    "USD/JPY": ["yahoo:USDJPY=X", "fdr:USD/JPY"],
    "DXY": ["yahoo:DX-Y.NYB"],
    # 원자재 (sources.yaml commodities). 종목 티커(GOLD·CL 등)와 겹치지 않게 CMDT: 를 붙인다
    "CMDT:GOLD_KRX": ["naver:metal:M04020000"],          # 국내 금 원/g
    "CMDT:GOLD": ["yahoo:GC=F"],                          # 국제 금 달러/온스 (뉴욕 선물)
    "CMDT:SILVER": ["yahoo:SI=F"],                        # 국제 은 달러/온스
    "CMDT:WTI": ["yahoo:CL=F"],                           # WTI 원유 달러/배럴
    "CMDT:BRENT": ["yahoo:BZ=F"],                         # 브렌트유 달러/배럴
    "CMDT:COPPER": ["yahoo:HG=F"],                        # 구리 달러/파운드
}


# 미국 장중에 갱신하는 지수 (나머지 지수 스트립 항목은 국내 장중에 갱신)
US_INDEX_SYMBOLS = {"US500", "IXIC", "DJI"}


def index_chain(item: dict | str) -> list[str]:
    if isinstance(item, dict):
        if item.get("sources"):
            return list(item["sources"])
        sym = item["symbol"]
    else:
        sym = item
    return INDEX_CHAINS.get(sym, [f"yahoo:{sym}", f"fdr:{sym}"])


def to_price_rows(symbol: str, bars: list[Bar], source: str) -> list[dict]:
    """DB prices 행으로 변환하며 전일 대비 등락률을 계산한다 (첫 봉은 None)."""
    rows, prev = [], None
    for b in bars:
        rows.append({"symbol": symbol, "day": b["day"], "open": b["open"], "high": b["high"], "low": b["low"],
                     "close": b["close"], "volume": b["volume"],
                     "change_pct": round((b["close"] / prev - 1) * 100, 2) if prev else None,
                     "source": source.split(":")[0]})
        prev = b["close"]
    return rows


# ── 종목 마스터 (태깅 사전·종목 검색) ─────────────────────────────
def naver_world_listing(exchange: str, max_pages: int = 40) -> list[dict]:
    """미국 거래소(NASDAQ·NYSE·AMEX) 시가총액순 종목 목록. 한글 이름이 있으면 한글로."""
    out: dict[str, dict] = {}
    for page in range(1, max_pages + 1):
        rows = _rows(get_json("naver", f"{NAVER_WORLD}/stock/exchange/{exchange}/marketValue",
                              params={"page": page, "pageSize": 100}, retries=2))
        for r in rows:
            sym, quote = _first(r, "symbolCode"), _first(r, "reutersCode")
            name = _first(r, "stockName", "stockNameEng")
            if sym and quote and name and len(str(sym)) <= 12:
                out[str(sym)] = {"code": str(sym), "name": str(name)[:100], "market": exchange,
                                 "quote_code": str(quote)[:20],
                                 "name_en": english_name(_first(r, "stockNameEng") or "") or None}
        if len(rows) < 100:
            break
    return list(out.values())


US_EXCHANGES = US_MARKETS

_EN_SUFFIX = re.compile(r"[,.]?\s+(inc|incorporated|corp|corporation|co|company|ltd|limited|plc|holdings?|group|"
                        r"class [a-c]|adr|common stock|ordinary shares|sa|nv|ag|se)\.?$", re.IGNORECASE)


def english_name(full: str) -> str:
    """'NVIDIA Corporation' → 'NVIDIA', 'Alphabet Inc Class A' → 'Alphabet' (영어 기사 태깅용)."""
    name = full.strip()
    for _ in range(4):
        trimmed = _EN_SUFFIX.sub("", name).strip(" ,.")
        if trimmed == name:
            break
        name = trimmed
    return name[:100]


def naver_listing(market: str, max_pages: int = 40) -> list[dict]:
    """시가총액순 상장 종목 목록 (best-effort, 응답 형식을 알 수 없으면 빈 목록)."""
    out: dict[str, dict] = {}
    for page in range(1, max_pages + 1):
        rows = _rows(get_json("naver", f"{NAVER}/api/stocks/marketValue/{market}",
                              params={"page": page, "pageSize": 100}, retries=2))
        got = 0
        for r in rows:
            code = _first(r, "itemCode", "code", "symbolCode", "stockCode")
            name = _first(r, "stockName", "itemName", "name", "stockNameEng")
            if code and name and str(code).isdigit() and len(str(code)) == 6:
                out[str(code)] = {"code": str(code), "name": str(name), "market": market}
                got += 1
        if got == 0 or len(rows) < 100:
            break
    return list(out.values())

"""코인 시세 (무료, 키 불필요).

  업비트       원화 시세·24시간 등락·거래대금 (KRW 마켓 전체), 일봉
  바이낸스     해외 달러(USDT) 시세 → 김치 프리미엄. 막히면 코인게코로 대체
  코인게코     전체 시가총액·BTC/ETH 점유율 (무료 API 분당 호출 제한이 있어 10분 캐시)
  alternative.me  공포·탐욕 지수 (하루 1번 갱신)

화면용 실시간 값은 요청 때 받아 짧게 캐시하고(cached), 차트용 일봉만 prices 테이블에 저장한다 (COIN:BTC).
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime

from ..core.http import get_json

log = logging.getLogger(__name__)

UPBIT = "https://api.upbit.com/v1"
BINANCE = "https://api.binance.com/api/v3"
COINGECKO = "https://api.coingecko.com/api/v3"
FNG = "https://api.alternative.me/fng/"

FNG_LABELS = {"Extreme Fear": "극단적 공포", "Fear": "공포", "Neutral": "중립", "Greed": "탐욕",
              "Extreme Greed": "극단적 탐욕"}

_cache: dict[str, tuple[float, object]] = {}


def cached(key: str, ttl: float, fn):
    """ttl 초 안에는 이전 결과를 쓴다. 실패하면 마지막 성공 값(오래됐어도)을, 그것도 없으면 None."""
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < ttl:
        return hit[1]
    try:
        value = fn()
    except Exception as e:  # noqa: BLE001 - 한 소스 실패가 화면 전체를 막지 않게
        log.warning("코인 %s 조회 실패: %s", key, e)
        return hit[1] if hit else None
    _cache[key] = (time.monotonic(), value)
    return value


# ── 업비트 ────────────────────────────────────────────────────
def krw_markets() -> dict[str, str]:
    """{"KRW-BTC": "비트코인", ...} 업비트 원화 마켓 전체."""
    rows = get_json("upbit", f"{UPBIT}/market/all", retries=2)
    return {r["market"]: r["korean_name"] for r in rows if r["market"].startswith("KRW-")}


def tickers(markets: list[str]) -> list[dict]:
    """현재가·24시간 등락률(%)·24시간 거래대금(원). markets 는 한 번에 수백 개까지 된다."""
    rows = get_json("upbit", f"{UPBIT}/ticker", params={"markets": ",".join(markets)}, retries=2)
    return [{"market": r["market"], "code": r["market"].split("-", 1)[1], "price": r["trade_price"],
             "change": r["signed_change_price"], "change_pct": round(r["signed_change_rate"] * 100, 2),
             "volume_krw": r["acc_trade_price_24h"]} for r in rows]


def upbit_days(market: str, n: int):
    """일봉 (quotes.Bar 형식). 한 번에 최대 200개. 업비트 일봉은 한국 시간 09:00 에 바뀐다."""
    from .quotes import Bar, _dedupe_sort
    rows = get_json("upbit", f"{UPBIT}/candles/days", params={"market": market, "count": min(n, 200)}, retries=2)
    return _dedupe_sort([Bar(day=datetime.fromisoformat(r["candle_date_time_kst"]).date(), close=r["trade_price"],
                             open=r["opening_price"], high=r["high_price"], low=r["low_price"],
                             volume=r["candle_acc_trade_volume"]) for r in rows])


# ── 해외 시세 ─────────────────────────────────────────────────
def global_usd(coins: list[dict]) -> dict[str, float]:
    """{"BTC": 83127.5, ...} 해외 달러 시세. 바이낸스 USDT → 실패하면 코인게코."""
    try:
        syms = json.dumps([f"{c['code']}USDT" for c in coins], separators=(",", ":"))
        rows = get_json("binance", f"{BINANCE}/ticker/price", params={"symbols": syms}, retries=1, timeout=8)
        return {r["symbol"].removesuffix("USDT"): float(r["price"]) for r in rows}
    except Exception as e:  # noqa: BLE001 - 지역 차단(451) 등
        log.info("바이낸스 실패, 코인게코로 대체: %s", e)
    ids = {c["coingecko"]: c["code"] for c in coins if c.get("coingecko")}
    data = get_json("coingecko", f"{COINGECKO}/simple/price",
                    params={"ids": ",".join(ids), "vs_currencies": "usd"}, retries=1)
    return {ids[k]: float(v["usd"]) for k, v in data.items() if "usd" in v}


def market_overview() -> dict:
    d = get_json("coingecko", f"{COINGECKO}/global", retries=1)["data"]
    pct = d.get("market_cap_percentage", {})
    return {"market_cap_usd": d["total_market_cap"]["usd"], "btc_dominance": round(pct.get("btc", 0), 1),
            "eth_dominance": round(pct.get("eth", 0), 1),
            "market_cap_change_pct": round(d.get("market_cap_change_percentage_24h_usd") or 0, 2)}


def fear_greed() -> dict:
    rows = get_json("alternative.me", FNG, params={"limit": 2}, retries=1)["data"]
    now, prev = rows[0], rows[1] if len(rows) > 1 else None
    return {"value": int(now["value"]), "label": FNG_LABELS.get(now["value_classification"], now["value_classification"]),
            "prev": int(prev["value"]) if prev else None}

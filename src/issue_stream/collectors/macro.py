"""거시 지표: 한국은행 ECOS, 미국 FRED (모두 무료 키). 1일 1회 배치."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from ..core.config import get_settings
from ..core.http import get_json

ECOS_API = "https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr/1/1000/{code}/{cycle}/{start}/{end}/{item}"
FRED_API = "https://api.stlouisfed.org/fred/series/observations"


def _ecos_fmt(d: date, cycle: str) -> str:
    return {"D": d.strftime("%Y%m%d"), "M": d.strftime("%Y%m"), "A": d.strftime("%Y")}.get(
        cycle, d.strftime("%Y%m%d"))


def fetch_ecos(series: list[dict], days: int = 60) -> list[dict]:
    key = get_settings().ecos_api_key
    end, start = date.today(), date.today() - timedelta(days=days)
    rows = []
    for sr in series:
        url = ECOS_API.format(key=key, code=sr["code"], cycle=sr["cycle"], item=sr["item"],
                              start=_ecos_fmt(start, sr["cycle"]), end=_ecos_fmt(end, sr["cycle"]))
        data = get_json("ecos", url)
        for it in data.get("StatisticSearch", {}).get("row", []):
            t = it["TIME"]
            day = datetime.strptime(t, {8: "%Y%m%d", 6: "%Y%m", 4: "%Y"}[len(t)]).date()
            rows.append({"series_id": f"ecos:{sr['code']}:{sr['item']}", "day": day,
                         "value": float(it["DATA_VALUE"]), "name": sr["name"]})
    return rows


def fetch_fred(series_ids: list[str], days: int = 120) -> list[dict]:
    key = get_settings().fred_api_key
    start = (date.today() - timedelta(days=days)).isoformat()
    rows = []
    for sid in series_ids:
        data = get_json("fred", FRED_API, params={"series_id": sid, "api_key": key, "file_type": "json",
                                                  "observation_start": start})
        for o in data.get("observations", []):
            if o["value"] in (".", ""):
                continue
            rows.append({"series_id": f"fred:{sid}", "day": date.fromisoformat(o["date"]),
                         "value": float(o["value"]), "name": sid})
    return rows

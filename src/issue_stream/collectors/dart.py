"""OPEN DART 공시 수집 (무료, 계정당 일 20,000건).

주의: DART의 회사고유번호(corp_code, 8자리)는 종목코드(stock_code, 6자리)와 다르다.
sync_corp_codes()로 전체 매핑을 먼저 받아 dart_corp_codes 테이블에 넣어 둔다 (주 1회 작업).
"""
from __future__ import annotations

import io
import zipfile
from datetime import datetime, timedelta
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

from ..core.config import get_settings
from ..core.http import get_bytes, get_json
from ..core.schemas import RawDoc
from .base import Collector

KST = ZoneInfo("Asia/Seoul")
LIST_API = "https://opendart.fss.or.kr/api/list.json"
CORP_CODE_API = "https://opendart.fss.or.kr/api/corpCode.xml"
VIEW_URL = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={}"


class DartCollector(Collector):
    name = "dart"

    def fetch(self, since: datetime) -> list[RawDoc]:
        key = get_settings().dart_api_key
        since_kst = since.astimezone(KST)
        docs: list[RawDoc] = []
        page = 1
        while True:
            data = get_json("dart", LIST_API, params={
                "crtfc_key": key,
                "bgn_de": since_kst.strftime("%Y%m%d"),
                "end_de": datetime.now(KST).strftime("%Y%m%d"),
                "page_no": page, "page_count": 100,
            })
            status = data.get("status")
            if status == "013":        # 조회된 데이터 없음
                break
            if status != "000":
                raise RuntimeError(f"DART 오류 {status}: {data.get('message')}")
            for it in data.get("list", []):
                # 접수일자만 있고 시각은 없으므로 접수일 00:00 KST 로 둔다
                rcept_day = datetime.strptime(it["rcept_dt"], "%Y%m%d").replace(tzinfo=KST)
                if rcept_day < since_kst.replace(hour=0, minute=0, second=0, microsecond=0):
                    continue
                stock = (it.get("stock_code") or "").strip()
                docs.append(RawDoc(
                    source=self.name, kind="disclosure",
                    external_id=it["rcept_no"],
                    title=f"[공시] {it['corp_name']} - {it['report_nm'].strip()}",
                    url=VIEW_URL.format(it["rcept_no"]),
                    publisher="DART",
                    published_at=rcept_day,
                    snippet=f"제출인: {it.get('flr_nm', '')}",
                    raw_tickers=[stock] if stock else [],
                ))
            if page >= int(data.get("total_page", 1)):
                break
            page += 1
        return docs


def fetch_corp_codes() -> list[dict]:
    """전체 회사 고유번호 목록 (zip 안의 CORPCODE.xml). 상장사만 반환."""
    raw = get_bytes("dart", CORP_CODE_API, params={"crtfc_key": get_settings().dart_api_key}, timeout=120)
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        xml = z.read(z.namelist()[0])
    rows = []
    for el in ElementTree.fromstring(xml).iter("list"):
        stock = (el.findtext("stock_code") or "").strip()
        if not stock:
            continue
        rows.append({
            "corp_code": el.findtext("corp_code"),
            "corp_name": el.findtext("corp_name"),
            "stock_code": stock,
            "modify_date": el.findtext("modify_date"),
        })
    return rows


def default_since() -> datetime:
    return datetime.now(KST) - timedelta(days=1)

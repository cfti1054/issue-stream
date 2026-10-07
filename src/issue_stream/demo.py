"""데모 데이터. API 키 없이도 대시보드 화면을 바로 확인하기 위한 가상 데이터.

  issue-stream seed-demo           데모 데이터 넣기 (기존 데모 데이터는 지우고 다시 생성)
  issue-stream seed-demo --clear   데모 데이터만 지우기

모든 기사·시세는 가상이며 source 가 'demo' 로 시작한다. 실제 수집 데이터와 섞여도 --clear 로 깔끔히 지워진다.
화면 상단에도 "데모 데이터" 표시가 뜬다.
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, select

from .core.config import load_yaml
from .core.schemas import RawDoc
from .db.ops import upsert
from .db.models import Article, Issue, IssueArticle, Price, SectorIndex, Ticker
from .db.session import session_scope

EXTRA_TICKERS = [
    ("373220", "LG에너지솔루션", []), ("035420", "NAVER", ["네이버"]), ("035720", "카카오", []),
    ("068270", "셀트리온", []), ("051910", "LG화학", []), ("105560", "KB금융", []),
]

# (종목코드, 시작가) - 관심종목이 아니면 무시
START_PRICE = {"005930": 84_000, "000660": 248_000, "005380": 241_000, "000720": 34_500}
INDEX_START = {"KS11": 2_940.0, "KQ11": 846.0, "US500": 6_480.0, "IXIC": 21_150.0, "USD/KRW": 1_386.0}

SECTORS = ["반도체", "2차전지", "자동차", "은행", "증권", "보험", "건설", "철강", "에너지화학", "기계장비",
           "운송", "헬스케어", "바이오", "미디어·엔터", "게임", "IT"]

# (제목, 매체, 스니펫, 몇 시간 전)
NEWS = [
    # 이슈 A: 삼성전자 실적
    ("삼성전자 3분기 영업이익 10조원 돌파…시장 예상 상회", "한국경제", "HBM 판매 확대가 실적 개선을 견인했다.", 2.2),
    ("[종합] 삼성전자 3분기 영업이익 10조원 돌파, 시장 예상 상회", "연합뉴스", None, 2.0),
    ("삼성전자, 3분기 영업이익 10조 돌파 '어닝 서프라이즈'", "매일경제", "시장 예상치 8조원을 크게 웃돌았다.", 1.6),
    ("삼성전자 3분기 영업익 10조원 돌파 호실적", "서울경제", "메모리 가격 반등으로 반도체 부문 흑자 폭이 확대됐다.", 0.9),
    ("삼성전자 영업이익 10조 돌파에 반도체주 강세", "머니투데이", "외국인 순매수가 이어졌다.", 0.4),
    # 이슈 B: 기준금리
    ("한국은행 기준금리 연 3.0% 동결", "한국경제", "금통위는 만장일치로 기준금리를 동결했다.", 5.5),
    ("한은 기준금리 3.0% 동결…연내 인하 가능성 시사", "연합뉴스", "총재는 물가 경로를 지켜보겠다고 밝혔다.", 5.0),
    ("기준금리 3.0% 동결…한은 연내 인하 가능성 열어둬", "이데일리", None, 4.2),
    # 이슈 C: SK하이닉스 HBM
    ("SK하이닉스 HBM4 양산 돌입…엔비디아 공급 확대", "전자신문", "차세대 HBM4 양산 라인 가동을 시작했다.", 7.5),
    ("SK하이닉스, HBM4 양산 돌입 엔비디아 공급 확대 기대", "한국경제", None, 6.8),
    ("SK하이닉스 HBM4 양산 돌입 소식에 신고가", "매일경제", "장중 신고가를 경신했다.", 3.1),
    # 이슈 D: 현대차 관세
    ("현대차 미국 관세 우려에 약세", "매일경제", "관세 부담 전망에 주가가 하락했다.", 3.8),
    ("현대차 미국 관세 부담 우려…주가 약세 지속", "서울경제", "현지 생산 확대 계획에도 투자심리가 위축됐다.", 2.9),
    # 이슈 E: 환율
    ("원달러 환율 1,380원대 하락…외국인 순매수 영향", "연합뉴스", None, 1.2),
    ("원달러 환율 1,380원대로 하락 외국인 순매수", "이데일리", "달러 약세와 외국인 자금 유입이 겹쳤다.", 0.8),
    # 이슈 F: 현대건설 수주
    ("현대건설 중동 원전 수주…3조원 규모 계약 체결", "머니투데이", "해외 원전 수주 실적이 확대됐다.", 9.5),
    ("현대건설, 중동 원전 3조원 규모 수주 계약 체결", "한국경제", None, 9.0),
    # 단독 이슈들
    ("카카오 공동체 구조조정 발표 지연", "전자신문", "계열사 정리 일정이 지연되고 있다.", 11.0),
    ("셀트리온 美 FDA 바이오시밀러 승인", "머니투데이", "신규 바이오시밀러가 승인을 받았다.", 13.0),
    # 미국 시장 (한국어 보도 + 영어 원문)
    ("뉴욕증시, 기술주 강세에 나스닥 사상 최고치…S&P500도 상승", "연합뉴스", "AI 반도체주가 상승을 이끌었다.", 6.0),
    ("뉴욕증시 기술주 랠리…나스닥 최고치 경신", "뉴스1", None, 5.6),
    ("Stocks rally as Nasdaq hits record high on tech gains", "CNBC", "Chipmakers led the gains on Wall Street.", 5.8),
    ("Nasdaq jumps to all-time high as tech stocks surge", "Nasdaq.com", None, 5.4),
    ("연준 위원들 \"금리 인하 서두를 필요 없어\"…미 국채 금리 상승", "한국경제", "물가 둔화 확인이 더 필요하다는 입장이다.", 8.0),
    ("Fed officials signal no rush to cut rates, Treasury yields rise", "CNBC", None, 7.6),
]

DISCLOSURES = [
    ("005930", "삼성전자", "연결재무제표기준영업(잠정)실적(공정공시)"),
    ("000720", "현대건설", "단일판매ㆍ공급계약체결"),
]


def _trading_days(n: int) -> list[date]:
    days, d = [], date.today()
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    return list(reversed(days))


def _walk(rng: random.Random, start: float, n: int, vol: float, drift: float = 0.0) -> list[float]:
    out, v = [], start
    for _ in range(n):
        v *= 1 + rng.gauss(drift, vol)
        out.append(v)
    return out


def clear() -> None:
    with session_scope() as db:
        demo_ids = select(Article.id).where(Article.source.like("demo%"))
        issue_ids = select(IssueArticle.issue_id).where(IssueArticle.article_id.in_(demo_ids))
        db.execute(delete(Issue).where(Issue.id.in_(issue_ids)))
        db.execute(delete(Article).where(Article.source.like("demo%"), Article.duplicate_of.is_not(None)))
        db.execute(delete(Article).where(Article.source.like("demo%")))
        db.execute(delete(Price).where(Price.source == "demo"))
        db.execute(delete(SectorIndex).where(SectorIndex.source == "demo"))


def seed() -> dict:
    from .pipeline.run import cluster_pending, collect_and_ingest, enrich_issues

    clear()
    rng = random.Random(20260930)
    days = _trading_days(90)
    wl = load_yaml("watchlist.yaml").get("watchlist", [])

    with session_scope() as db:
        # 종목 마스터 (실제 동기화 전이라도 태깅이 되도록)
        for w in wl:
            vals = dict(code=str(w["code"]), name=w["name"], aliases=w.get("aliases", []), in_watchlist=True,
                        holding=bool(w.get("holding")))
            upsert(db, Ticker, vals, ["code"], ["in_watchlist", "holding", "aliases"])
        for code, name, aliases in EXTRA_TICKERS:
            upsert(db, Ticker, dict(code=code, name=name, aliases=aliases), ["code"], [])

        # 시세: 관심종목 + 지수 스트립
        series = {w["code"]: _walk(rng, START_PRICE.get(w["code"], 50_000), len(days), 0.017, 0.0006)
                  for w in wl}
        series.update({k: _walk(rng, v, len(days), 0.008 if k != "USD/KRW" else 0.003)
                       for k, v in INDEX_START.items()})
        for sym, closes in series.items():
            prev = None
            is_stock = sym.isdigit()
            for d, c in zip(days, closes):
                c = round(c / 50) * 50 if is_stock and c > 50_000 else round(c, 2 if not is_stock else 0)
                o = c * (1 + rng.gauss(0, 0.004))
                db.add(Price(symbol=sym, day=d, open=o, high=max(o, c) * 1.006, low=min(o, c) * 0.994,
                             close=c, volume=rng.randint(2, 30) * 1e6 if is_stock else None,
                             change_pct=round((c / prev - 1) * 100, 2) if prev else None, source="demo"))
                prev = c

        # 업종 지수 (최근 거래일)
        for name in SECTORS:
            db.add(SectorIndex(market="ETF", name=name, day=days[-1], close=round(rng.uniform(300, 6000), 2),
                               change_pct=round(rng.gauss(0.2, 1.3), 2), trading_value=rng.uniform(1e11, 3e12),
                               source="demo"))
        for e in load_yaml("sources.yaml").get("us_sector_etfs", []):
            db.add(SectorIndex(market="US", name=e["name"], day=days[-1], close=round(rng.uniform(40, 600), 2),
                               change_pct=round(rng.gauss(0.1, 1.1), 2), source="demo", symbol=str(e["code"])))

    now = datetime.now(timezone.utc)
    docs = [RawDoc(source="demo:news", external_id=f"demo-{i}", title=t, url=f"https://example.com/demo/{i}",
                   publisher=p, published_at=now - timedelta(hours=h), snippet=s)
            for i, (t, p, s, h) in enumerate(NEWS)]
    docs += [RawDoc(source="demo:dart", kind="disclosure", external_id=f"demo-dart-{i}",
                    title=f"[공시] {name} - {rep}", url="https://dart.fss.or.kr", publisher="DART",
                    published_at=now - timedelta(hours=1 + i), raw_tickers=[code])
             for i, (code, name, rep) in enumerate(DISCLOSURES)]

    with session_scope() as db:
        n = collect_and_ingest(db, docs=docs)
    with session_scope() as db:
        cluster_pending(db)
    with session_scope() as db:
        enrich_issues(db)
    with session_scope() as db:
        issues = db.scalar(select(Issue.id).order_by(Issue.id.desc()).limit(1))
    return {"articles": n, "prices_days": len(days), "last_issue_id": issues}

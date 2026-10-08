"""`issue-stream doctor` : 무료 데이터 소스가 이 PC 에서 실제로 응답하는지 한 번에 점검한다.

외부 사이트(언론사 RSS, 네이버, 야후 등)는 예고 없이 주소·형식이 바뀌므로,
안 되는 소스를 찾아 config/sources.yaml 에서 끄거나 순서를 바꾸는 데 쓴다.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone

OK, FAIL, WARN = "[ OK ]", "[실패]", "[주의]"


def _line(tag: str, name: str, detail: str = "") -> None:
    print(f"  {tag} {name:<22} {detail}")


def check_db() -> bool:
    from sqlalchemy import func, select, text

    from .db.models import Article, Issue, Price
    from .db.session import get_engine, resolve_url, session_scope
    print("\n■ 데이터베이스")
    url = resolve_url()
    try:
        with get_engine().connect() as c:
            c.execute(text("SELECT 1"))
        with session_scope() as db:
            counts = [db.scalar(select(func.count()).select_from(m)) for m in (Article, Issue, Price)]
        _line(OK, url.split("?")[0][:60], f"기사 {counts[0]} · 이슈 {counts[1]} · 시세 {counts[2]}")
        return True
    except Exception as e:  # noqa: BLE001
        msg = str(e).splitlines()[0][:120]
        if "no such table" in msg:
            _line(WARN, url[:60], "테이블 없음 → issue-stream migrate 실행")
        else:
            _line(FAIL, url[:60], msg)
        return False


def check_news() -> tuple[int, int]:
    import feedparser

    from .collectors.google_news import URL as GURL
    from .core.config import load_yaml
    from .core.http import get_bytes
    src = load_yaml("sources.yaml")
    ok = bad = 0
    print("\n■ 뉴스 RSS (키 불필요)")
    for f in src.get("rss", []):
        state = "켜짐" if f.get("enabled") else "꺼짐"
        try:
            feed = feedparser.parse(get_bytes("rss", f["url"], retries=1, timeout=10))
            n = len(feed.entries)
            if n:
                ok += f.get("enabled", False)
                _line(OK, f["name"], f"{n}건 ({state}) 예: {feed.entries[0].get('title', '')[:40]}")
            else:
                bad += f.get("enabled", False)
                _line(FAIL, f["name"], f"항목 0건 ({state}) → enabled: false 권장")
        except Exception as e:  # noqa: BLE001
            bad += f.get("enabled", False)
            _line(FAIL, f["name"], f"{str(e)[:70]} ({state}) → enabled: false 권장")
    print("\n■ 구글 뉴스 RSS (키 불필요)")
    from urllib.parse import quote
    try:
        feed = feedparser.parse(get_bytes("google", GURL.format(q=quote("코스피 when:1d")), retries=1, timeout=10))
        n = len(feed.entries)
        (_line(OK, "구글 뉴스 검색", f"'코스피' {n}건") if n else _line(FAIL, "구글 뉴스 검색", "0건"))
        ok += bool(n)
        bad += not n
    except Exception as e:  # noqa: BLE001
        bad += 1
        _line(FAIL, "구글 뉴스 검색", str(e)[:80])
    return ok, bad


def _try_each(label: str, chain: list[str]) -> bool:
    from .collectors.quotes import MAX_AGE_DAYS, fetch
    any_ok = False
    for src in chain:
        t0 = time.time()
        try:
            bars = fetch(src, 5)
            if bars and (date.today() - bars[-1]["day"]).days > MAX_AGE_DAYS:
                _line(WARN, f"{label} ← {src}", f"{bars[-1]['day']} 이후 갱신 없음 (사용 안 함)")
            elif bars:
                b = bars[-1]
                _line(OK, f"{label} ← {src}", f"{b['day']} 종가 {b['close']:,.2f} ({len(bars)}일, {time.time() - t0:.1f}s)")
                any_ok = True
            else:
                _line(FAIL, f"{label} ← {src}", "빈 응답")
        except Exception as e:  # noqa: BLE001
            _line(FAIL, f"{label} ← {src}", f"{type(e).__name__}: {str(e)[:70]}")
    return any_ok


def check_quotes() -> tuple[int, int]:
    from .collectors.quotes import index_chain, stock_chain
    from .core.config import load_yaml
    print("\n■ 시세 (위에서부터 순서대로 시도, 하나만 되어도 동작)")
    ok = bad = 0
    cfg = load_yaml("sources.yaml")
    for item in cfg.get("index_strip", []) + [x for x in cfg.get("fx_rates", []) if x["symbol"] != "USD/KRW"]:
        name = item["name"] if isinstance(item, dict) else item
        r = _try_each(name, index_chain(item))
        ok += r
        bad += not r
    for w in load_yaml("watchlist.yaml").get("watchlist", [])[:2]:
        r = _try_each(w["name"], stock_chain(str(w["code"]), w.get("market")))
        ok += r
        bad += not r
    return ok, bad


def check_sectors() -> tuple[int, int]:
    from .collectors.quotes import fetch_chain, reset_breaker, stock_chain
    reset_breaker()
    from .core.config import load_yaml
    print("\n■ 업종 히트맵용 ETF")
    ok = bad = 0
    cfg = load_yaml("sources.yaml")
    for e in cfg.get("sector_etfs", []) + [dict(x, us=True) for x in cfg.get("us_sector_etfs", [])]:
        code = str(e["code"])
        chain = stock_chain(code.split(".")[0], "US", code) if e.get("us") else stock_chain(code)
        bars, src, errs = fetch_chain(chain, 3)
        if len(bars) >= 2:
            chg = (bars[-1]["close"] / bars[-2]["close"] - 1) * 100
            _line(OK, f"{e['name']} ({e['code']})", f"{bars[-1]['day']} {chg:+.2f}% ← {src}")
            ok += 1
        else:
            _line(FAIL, f"{e['name']} ({e['code']})", (errs[0] if errs else "데이터 부족")[:90])
            bad += 1
    return ok, bad


def check_listing() -> None:
    from .collectors.quotes import naver_listing
    print("\n■ 종목 목록 (태깅 사전, 없어도 관심종목 태깅은 동작)")
    try:
        rows = naver_listing("KOSPI", max_pages=1)
        (_line(OK, "네이버 상장 목록", f"{len(rows)}종목 예: {rows[0]['name']}") if rows
         else _line(WARN, "네이버 상장 목록", "응답 형식 인식 실패 → 관심종목만 태깅"))
    except Exception as e:  # noqa: BLE001
        _line(WARN, "네이버 상장 목록", f"{str(e)[:70]} → 관심종목만 태깅")


def run() -> int:
    from .core.config import get_settings
    s = get_settings()
    print(f"issue-stream 점검  ({datetime.now(timezone(timedelta(hours=9))):%Y-%m-%d %H:%M} KST)")
    print(f"  구성: 임베딩={s.embedding_provider} 요약={s.summarizer_provider} 감성={s.sentiment_provider} "
          f"유료허용={s.allow_paid_apis}")
    db_ok = check_db()
    n_ok, n_bad = check_news()
    q_ok, q_bad = check_quotes()
    s_ok, s_bad = check_sectors()
    check_listing()
    print("\n■ 요약")
    print(f"  DB {'정상' if db_ok else '문제'} · 뉴스 소스 {n_ok}개 정상/{n_bad}개 실패 · "
          f"시세 {q_ok}개 정상/{q_bad}개 실패 · 업종 ETF {s_ok}개 정상/{s_bad}개 실패")
    if db_ok and n_ok and q_ok:
        print("  → 무료 구성으로 동작 가능합니다. issue-stream serve 로 실행하세요.")
        return 0
    print("  → 위 [실패] 항목을 확인하세요. 네트워크(회사 방화벽·VPN) 문제일 수도 있습니다.")
    return 1

"""명령줄 도구.

  issue-stream serve              ★ API + 수집 스케줄러를 한 번에 실행 (첫 실행 시 데이터 자동 채움)
  issue-stream doctor             무료 데이터 소스가 이 PC 에서 응답하는지 점검
  issue-stream check              설정·키·provider 점검 (유료 여부 표시)
  issue-stream collect --dry-run  DB 없이 수집 결과만 출력 (1단계)
  issue-stream init               DB 스키마 생성 + 종목 마스터·DART 고유번호 동기화 (최초 1회)
  issue-stream migrate            DB 스키마만 최신으로 (빠름)
  issue-stream run                파이프라인 1회 실행 (수집→중복제거→태깅→클러스터링→요약)
  issue-stream issues             최근 이슈 목록 출력 (3단계 눈 검수용)
  issue-stream tune-threshold     최근 기사 유사도 분포 출력 (클러스터 임계값 튜닝)
  issue-stream reembed            임베딩 모델 교체 후 전체 재임베딩·재클러스터링
  issue-stream seed-demo         화면 확인용 가상 데이터 넣기 (--clear 로 삭제)
  issue-stream scheduler          스케줄러만 실행 (API 를 따로 띄울 때)
  issue-stream api                API 서버만 실행
  issue-stream erd                docs/ERD.md 를 models.py 에서 다시 생성 (--check: 최신인지 검사)
  issue-stream user add <아이디>   로그인 계정 생성 (관리자용). passwd·list·disable·enable·delete
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone


def cmd_check(_):
    from .core.config import PAID_PROVIDERS, get_settings, load_yaml
    s = get_settings()
    print("── provider 구성")
    for comp, val in (("임베딩", s.embedding_provider), ("요약", s.summarizer_provider),
                      ("감성", s.sentiment_provider)):
        tag = "유료" if val in PAID_PROVIDERS else "무료"
        print(f"  {comp:6s} {val:12s} [{tag}]")
    print(f"  유료 API 허용: {s.allow_paid_apis}")
    print("── 무료 API 키")
    for k in ("dart_api_key", "ecos_api_key", "fred_api_key", "naver_client_id", "kis_app_key",
              "telegram_bot_token"):
        print(f"  {k:20s} {'설정됨' if getattr(s, k) else '-'}")
    from .db.session import resolve_url
    print(f"── DB: {resolve_url()}")
    print("── 활성 RSS")
    for f in load_yaml("sources.yaml").get("rss", []):
        print(f"  [{'on ' if f.get('enabled') else 'off'}] {f['name']}  {f['url']}")
    try:
        s.require_paid("SUMMARIZER_PROVIDER", s.summarizer_provider)
        s.require_paid("EMBEDDING_PROVIDER", s.embedding_provider)
    except Exception as e:
        print(f"\n⚠ {e}")


def cmd_collect(a):
    from .collectors import enabled_collectors
    from .pipeline.dedupe import find_duplicate, simhash
    from .pipeline.normalize import normalize_title
    since = datetime.now(timezone.utc) - timedelta(hours=a.hours)
    seen: dict[int, int] = {}
    total = dup = 0
    for c in enabled_collectors():
        docs = c.fetch(since)
        print(f"\n■ {c.name}: {len(docs)}건")
        for i, d in enumerate(docs):
            h = simhash(normalize_title(d.title))
            is_dup = find_duplicate(h, seen, 3) is not None
            seen[total + i] = h
            dup += is_dup
            print(f"  {'(중복) ' if is_dup else ''}{d.published_at:%m-%d %H:%M} {d.title[:70]}")
        total += len(docs)
    print(f"\n합계 {total}건, 제목 중복 {dup}건")
    if not a.dry_run:
        from .db.session import session_scope
        from .pipeline.run import collect_and_ingest
        with session_scope() as db:
            print(f"DB 적재: {collect_and_ingest(db, since)}건")


def migrate() -> None:
    from alembic import command
    from alembic.config import Config

    from .core.config import ROOT_DIR
    cfg = Config(str(ROOT_DIR / "alembic.ini"))
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")


def cmd_migrate(_):
    migrate()
    print("DB 스키마 최신 상태")


def cmd_init(_):
    from .jobs import tasks
    migrate()
    print("스키마 준비 완료. 종목·시세 채우는 중...")
    print(f"DART 고유번호 {tasks.job_sync_dart_corp_codes()}건 (키가 없으면 0)")
    print(f"종목 {tasks.job_sync_tickers()}건")
    print(f"시세 {tasks.job_backfill_prices()}건")


def cmd_doctor(_):
    from . import doctor
    sys.exit(doctor.run())


def cmd_serve(a):
    import os

    import uvicorn
    migrate()
    os.environ["ISSUE_STREAM_SCHEDULER"] = "0" if a.no_scheduler else "1"
    print(f"API: http://{a.host}:{a.port}/docs   대시보드: http://localhost:3000 (web 폴더에서 npm run dev)")
    if a.host == "::":
        # 컨테이너 기본값(IPV6_V6ONLY)에 따라 IPv6 만 받는 경우가 있어 IPv4 도 받도록 직접 연다.
        # Railway 헬스체크는 IPv4, 내부망은 IPv6 로 들어온다.
        server = uvicorn.Server(uvicorn.Config("issue_stream.api.main:app", log_level="info"))
        server.run(sockets=[_dual_stack_socket(a.port)])
    else:
        uvicorn.run("issue_stream.api.main:app", host=a.host, port=a.port, log_level="info")


def _dual_stack_socket(port: int):
    import socket
    sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
    sock.bind(("::", port))
    return sock


def cmd_run(_):
    from .jobs import tasks
    migrate()
    print(f"신규 기사 {tasks.job_news_pipeline()}건 처리")


def cmd_issues(a):
    from sqlalchemy import desc, select

    from .db.models import Article, Issue, IssueArticle, IssueSummaryRow
    from .db.session import session_scope
    since = datetime.now(timezone.utc) - timedelta(hours=a.hours)
    with session_scope() as db:
        for i in db.scalars(select(Issue).where(Issue.last_seen >= since)
                            .order_by(desc(Issue.importance)).limit(a.limit)).all():
            sm = db.scalar(select(IssueSummaryRow).where(IssueSummaryRow.issue_id == i.id,
                                                         IssueSummaryRow.is_current.is_(True)))
            print(f"\n[{i.importance:5.1f}] #{i.no} 기사 {i.article_count} / 매체 {i.publisher_count} "
                  f"/ {i.sentiment or '-'}")
            if sm:
                print(f"  ▶ {sm.payload['headline']}")
                for b in sm.payload["bullets"]:
                    print(f"    • {b}")
            if a.verbose:
                for t, in db.execute(select(Article.title).join(IssueArticle, IssueArticle.article_id == Article.id)
                                     .where(IssueArticle.issue_id == i.id)).all():
                    print(f"      - {t}")


def cmd_tune(a):
    from sqlalchemy import select

    from .db.models import Article
    from .db.session import session_scope
    from .pipeline.cluster import similarity_histogram
    from .providers.embedding import get_embedder
    since = datetime.now(timezone.utc) - timedelta(hours=a.hours)
    with session_scope() as db:
        rows = db.execute(select(Article.title, Article.snippet).where(
            Article.published_at >= since, Article.duplicate_of.is_(None)).limit(800)).all()
    emb = get_embedder()
    vecs = emb.embed([emb.text_for(t, s) for t, s in rows])
    from .core.config import get_settings
    print(f"기사 {len(rows)}건 쌍별 코사인 유사도 분포 (오른쪽 꼬리가 '같은 사건' 구간)")
    print(f"현재 임계값: {get_settings().effective_cluster_threshold()}  ({emb.name})")
    hist = similarity_histogram(vecs)
    peak = max((c for _, c in hist), default=1)
    for edge, c in hist:
        print(f"  {edge:5.2f} | {'█' * max(1 if c else 0, int(40 * c / peak))} {c}")


def cmd_reembed(_):
    from sqlalchemy import delete, update

    from .db.models import Article, Issue, IssueArticle, IssueSummaryRow
    from .db.session import session_scope
    from .pipeline.run import cluster_pending, enrich_issues
    ok = input("모든 임베딩·이슈를 지우고 현재 EMBEDDING_PROVIDER 로 다시 만듭니다. 계속? (y/N) ")
    if ok.lower() != "y":
        return
    with session_scope() as db:
        db.execute(delete(IssueSummaryRow))
        db.execute(delete(IssueArticle))
        db.execute(delete(Issue))
        db.execute(update(Article).values(embedding=None, embedding_model=None))
    total = 0
    while True:
        with session_scope() as db:
            n = cluster_pending(db)
        total += n
        if n == 0:
            break
    with session_scope() as db:
        enrich_issues(db)
    print(f"재임베딩 {total}건 완료")


def cmd_seed_demo(a):
    from . import demo
    migrate()
    if a.clear:
        demo.clear()
        print("데모 데이터를 지웠습니다.")
        return
    r = demo.seed()
    print(f"데모 데이터 생성: 기사 {r['articles']}건, 시세 {r['prices_days']}거래일")
    print("  issue-stream serve --no-scheduler  →  cd web && npm run dev  →  http://localhost:3000")


def cmd_scheduler(_):
    from .jobs.scheduler import main
    migrate()
    main()


def cmd_api(a):
    import uvicorn
    uvicorn.run("issue_stream.api.main:app", host=a.host, port=a.port, reload=a.reload)


def _ask_password() -> str:
    import getpass
    pw = getpass.getpass("비밀번호: ")
    if sys.stdin.isatty() and getpass.getpass("비밀번호 확인: ") != pw:
        sys.exit("비밀번호가 서로 다릅니다.")
    return pw


def cmd_user(a):
    from . import accounts
    migrate()
    try:
        if a.action == "list":
            rows = accounts.list_users()
            if not rows:
                print("계정이 없습니다. issue-stream user add <아이디>")
            for u in rows:
                last = f"{u['last_login_at']:%Y-%m-%d %H:%M}" if u["last_login_at"] else "-"
                print(f"  {'' if u['active'] else '(비활성) '}{u['username']:20s} {u['name'] or '':10s} "
                      f"관심종목 {u['watchlist']:3d}  마지막 로그인 {last}")
            return
        if not a.username:
            sys.exit(f"아이디를 입력하세요: issue-stream user {a.action} <아이디>")
        if a.action == "add":
            accounts.create_user(a.username, _ask_password(), a.name, default_watchlist=not a.empty)
            print(f"계정 생성: {a.username}" + ("" if a.empty else " (watchlist.yaml 종목을 관심종목으로 등록)"))
        elif a.action == "passwd":
            accounts.set_password(a.username, _ask_password())
            print("비밀번호를 바꿨습니다. 기존 로그인은 모두 해제됩니다.")
        elif a.action in ("disable", "enable"):
            accounts.set_active(a.username, a.action == "enable")
            print(f"{a.username}: {'활성' if a.action == 'enable' else '비활성'}")
        elif a.action == "delete":
            if input(f"{a.username} 계정과 관심종목을 삭제합니다. 계속? (y/N) ").lower() == "y":
                accounts.delete_user(a.username)
                print("삭제했습니다.")
    except accounts.AccountError as e:
        sys.exit(str(e))


def cmd_erd(a):
    from . import erd
    if missing := erd.unassigned_tables():
        sys.exit(f"erd.py 의 DOMAINS 에 테이블을 추가하세요: {', '.join(sorted(missing))}")
    if a.check:
        if not erd.is_up_to_date():
            sys.exit("docs/ERD.md 가 models.py 와 다릅니다. issue-stream erd 로 다시 만드세요.")
        print("docs/ERD.md 최신 상태")
        return
    erd.write()
    print(f"생성: {erd.ERD_PATH}")


def main(argv: list[str] | None = None) -> None:
    from .core.logging import setup_logging
    setup_logging()
    p = argparse.ArgumentParser(prog="issue-stream")
    sub = p.add_subparsers(dest="cmd", required=True)
    sv = sub.add_parser("serve")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)
    sv.add_argument("--no-scheduler", action="store_true", help="수집 없이 API 만")
    sv.set_defaults(fn=cmd_serve)
    sub.add_parser("doctor").set_defaults(fn=cmd_doctor)
    sub.add_parser("check").set_defaults(fn=cmd_check)
    c = sub.add_parser("collect")
    c.add_argument("--hours", type=int, default=6)
    c.add_argument("--dry-run", action="store_true")
    c.set_defaults(fn=cmd_collect)
    sub.add_parser("init").set_defaults(fn=cmd_init)
    sub.add_parser("migrate").set_defaults(fn=cmd_migrate)
    sub.add_parser("run").set_defaults(fn=cmd_run)
    i = sub.add_parser("issues")
    i.add_argument("--hours", type=int, default=24)
    i.add_argument("--limit", type=int, default=20)
    i.add_argument("-v", "--verbose", action="store_true")
    i.set_defaults(fn=cmd_issues)
    t = sub.add_parser("tune-threshold")
    t.add_argument("--hours", type=int, default=48)
    t.set_defaults(fn=cmd_tune)
    sub.add_parser("reembed").set_defaults(fn=cmd_reembed)
    sd = sub.add_parser("seed-demo")
    sd.add_argument("--clear", action="store_true")
    sd.set_defaults(fn=cmd_seed_demo)
    sub.add_parser("scheduler").set_defaults(fn=cmd_scheduler)
    ap = sub.add_parser("api")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--reload", action="store_true")
    ap.set_defaults(fn=cmd_api)
    e = sub.add_parser("erd", help="docs/ERD.md 생성")
    e.add_argument("--check", action="store_true", help="최신이 아니면 실패")
    e.set_defaults(fn=cmd_erd)
    u = sub.add_parser("user", help="로그인 계정 관리")
    u.add_argument("action", choices=["add", "passwd", "list", "disable", "enable", "delete"])
    u.add_argument("username", nargs="?", help="로그인 아이디")
    u.add_argument("--name", help="표시 이름")
    u.add_argument("--empty", action="store_true", help="add: 관심종목 없이 시작 (기본은 watchlist.yaml 복사)")
    u.set_defaults(fn=cmd_user)
    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    sys.exit(main())

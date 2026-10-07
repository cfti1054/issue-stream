"""파이프라인 오케스트레이션 (DB 연동).

  collect_and_ingest : 수집 → 정규화 → 중복 제거 → 종목 태깅 → 기사 감성 → 저장
  cluster_pending    : 임베딩 없는 기사 → 임베딩 → 이슈 배정
  enrich_issues      : 중요도 계산 → (필요 시) 요약 → 알림

각 함수는 처리 건수를 반환하고, jobs/tasks.py 가 job_runs 에 기록한다.
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timedelta, timezone

import numpy as np
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..collectors import enabled_collectors
from ..core.config import get_settings
from ..db.ops import insert_ignore_returning_id
from ..db.models import (
    Article, ArticleBody, Issue, IssueArticle, IssueSummaryRow, IssueTicker, Ticker,
)
from ..providers.embedding import get_embedder
from ..providers.sentiment import get_sentiment_model
from ..providers.summarizer import ArticleInput, get_summarizer
from .cluster import ClusterState, assign
from .dedupe import find_duplicate, simhash
from .importance import ImportanceInput, importance
from .normalize import normalize_title
from ..core.market_calendar import is_us_market
from .tagging import TickerEntry, TickerTagger

log = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def ticker_keys(codes: list[str]) -> str:
    """종목별 기사 검색용 문자열 ",005930,000660," (DB 종류와 무관하게 LIKE 로 찾는다)."""
    return f",{','.join(codes)}," if codes else ""


def build_tagger(db: Session) -> TickerTagger:
    """국내 종목은 전부, 미국 종목은 누군가의 관심종목일 때만 (수천 개 이름이 섞이면 오탐이 늘어난다).
    미국 종목은 한글 이름 외에 3자 이상 티커(NVDA, TSLA)도 찾는다."""
    entries = []
    for c, n, a, market, watched in db.execute(
            select(Ticker.code, Ticker.name, Ticker.aliases, Ticker.market, Ticker.in_watchlist)).all():
        if is_us_market(market):
            if watched:
                entries.append(TickerEntry(c, (n, *(a or []), *([c] if len(c) >= 3 else []))))
        else:
            entries.append(TickerEntry(c, (n, *(a or []))))
    return TickerTagger(entries)


# ── 1. 수집·적재 ────────────────────────────────────────────────
def collect_and_ingest(db: Session, since: datetime | None = None, docs: list | None = None) -> int:
    """docs 를 주면 수집을 건너뛰고 그 문서만 적재한다 (데모 데이터·테스트용)."""
    s = get_settings()
    since = since or _now() - timedelta(hours=6)
    collectors = [] if docs is not None else enabled_collectors()
    docs = list(docs or [])
    failed: list[str] = []
    for c in collectors:
        try:
            got = c.fetch(since)
            log.info("%s: %d건", c.name, len(got))
            docs.extend(got)
        except Exception as e:  # 한 소스 실패가 전체를 멈추지 않게
            log.warning("%s 수집 실패: %s", c.name, e)
            failed.append(c.name)
    if collectors and len(failed) == len(collectors):
        raise RuntimeError(f"모든 뉴스 소스 수집 실패 ({', '.join(failed[:3])} 등) → issue-stream doctor 로 확인")

    window = _now() - timedelta(hours=s.cluster_window_hours)
    recent = dict(db.execute(select(Article.id, Article.simhash)
                             .where(Article.published_at >= window, Article.duplicate_of.is_(None))).all())
    tagger = build_tagger(db)
    sentiments = get_sentiment_model().classify([d.title for d in docs]) if docs else []

    inserted = 0
    for d, senti in zip(docs, sentiments):
        norm = normalize_title(d.title)
        h = simhash(norm)
        dup = find_duplicate(h, recent, s.dedupe_hamming_threshold) if d.kind == "news" else None
        tags = tagger.tag(f"{d.title} {d.snippet or ''}")
        tickers = sorted(set(tags) | set(d.raw_tickers))
        aid = insert_ignore_returning_id(db, Article, dict(
            source=d.source, kind=d.kind, external_id=d.external_id[:500], title=d.title, norm_title=norm,
            url=d.url, publisher=d.publisher, published_at=d.published_at, snippet=d.snippet,
            simhash=h, duplicate_of=dup, tickers=tickers, ticker_keys=ticker_keys(tickers), sentiment=senti,
        ), ["source", "external_id"])
        if aid is None:
            continue  # 이미 수집됨
        inserted += 1
        if dup is None:
            recent[aid] = h
        if d.body and s.fetch_article_body:
            db.add(ArticleBody(article_id=aid, body=d.body,
                               expires_at=_now() + timedelta(hours=s.article_body_ttl_hours)))
    db.flush()
    return inserted


# ── 2. 클러스터링 ────────────────────────────────────────────────
def cluster_pending(db: Session, batch: int = 500) -> int:
    s = get_settings()
    emb = get_embedder()
    arts = db.scalars(select(Article).where(Article.embedding.is_(None), Article.duplicate_of.is_(None))
                      .order_by(Article.published_at).limit(batch)).all()
    touched: set[int] = set()
    if arts:
        # 뉴스를 먼저 배정해 이슈를 만든 뒤 공시를 붙인다 (DART 는 시각 없이 날짜만 있어 항상 앞에 정렬됨)
        arts = sorted(arts, key=lambda a: (a.kind == "disclosure", a.published_at))
        vecs = emb.embed([emb.text_for(a.title, a.snippet) for a in arts])

        window = _now() - timedelta(hours=s.cluster_window_hours)
        active = db.scalars(select(Issue).where(Issue.status == "active", Issue.last_seen >= window)).all()
        issue_tickers: dict[int, set[str]] = {}
        for iid, code in db.execute(select(IssueTicker.issue_id, IssueTicker.ticker)
                                    .where(IssueTicker.issue_id.in_([i.id for i in active]))).all():
            issue_tickers.setdefault(iid, set()).add(code)
        states = [ClusterState(i.id, np.asarray(i.centroid, dtype=np.float32), i.article_count,
                               tickers=issue_tickers.get(i.id, set()))
                  for i in active if i.centroid is not None]
        by_id = {i.id: i for i in active}
        assign(vecs, states, s.effective_cluster_threshold(),
               tickers=[list(a.tickers or []) for a in arts], kinds=[a.kind for a in arts])

        for st in states:
            if not st.members:
                continue
            if st.issue_id is None:
                first = arts[st.members[0]].published_at
                issue = Issue(first_seen=first, last_seen=first, centroid=st.centroid.tolist())
                db.add(issue)
                db.flush()
            else:
                issue = by_id[st.issue_id]
                issue.centroid = st.centroid.tolist()
            for idx in st.members:
                a = arts[idx]
                a.embedding, a.embedding_model = vecs[idx].tolist(), emb.name
                db.add(IssueArticle(issue_id=issue.id, article_id=a.id,
                                    similarity=float(vecs[idx] @ st.centroid)))
                issue.last_seen = max(issue.last_seen, a.published_at)
                issue.first_seen = min(issue.first_seen, a.published_at)
            touched.add(issue.id)
        db.flush()

    touched |= _link_duplicates(db)
    _refresh_issue_stats(db, touched)
    return len(arts)


def _link_duplicates(db: Session) -> set[int]:
    """중복 기사(받아쓰기)는 임베딩하지 않지만, 원본이 속한 이슈에 연결해 보도량·매체 수에는 반영한다."""
    linked = select(IssueArticle.article_id)
    rows = db.execute(
        select(Article.id, IssueArticle.issue_id)
        .join(IssueArticle, IssueArticle.article_id == Article.duplicate_of)
        .where(Article.duplicate_of.is_not(None), Article.id.not_in(linked))
    ).all()
    for aid, iid in rows:
        db.add(IssueArticle(issue_id=iid, article_id=aid, similarity=1.0))
    db.flush()
    return {iid for _, iid in rows}


def _refresh_issue_stats(db: Session, issue_ids: set[int]) -> None:
    for iid in issue_ids:
        issue = db.get(Issue, iid)
        arts = db.scalars(select(Article).join(IssueArticle, IssueArticle.article_id == Article.id)
                          .where(IssueArticle.issue_id == iid)).all()
        issue.article_count = len(arts)
        issue.publisher_count = len({a.publisher for a in arts})
        issue.has_disclosure = any(a.kind == "disclosure" for a in arts)
        mentions = Counter(t for a in arts for t in (a.tickers or []))
        db.query(IssueTicker).filter(IssueTicker.issue_id == iid).delete()
        known = set(db.scalars(select(Ticker.code).where(Ticker.code.in_(list(mentions)))).all())
        for code, n in mentions.items():
            if code in known:
                db.add(IssueTicker(issue_id=iid, ticker=code, mentions=n))
    db.flush()


# ── 3. 중요도·요약·알림 ─────────────────────────────────────────
def enrich_issues(db: Session) -> int:
    s = get_settings()
    summarizer = get_summarizer()
    window = _now() - timedelta(hours=s.cluster_window_hours)
    holdings = set(db.scalars(select(Ticker.code).where(Ticker.holding.is_(True))).all())
    watch = set(db.scalars(select(Ticker.code).where(Ticker.in_watchlist.is_(True))).all())
    hour_ago = _now() - timedelta(hours=1)

    done = 0
    for issue in db.scalars(select(Issue).where(Issue.status == "active", Issue.last_seen >= window)).all():
        arts = db.scalars(select(Article).join(IssueArticle, IssueArticle.article_id == Article.id)
                          .where(IssueArticle.issue_id == issue.id)).all()
        codes = {t for a in arts for t in (a.tickers or [])}
        score, _parts = importance(ImportanceInput(
            article_count=issue.article_count, publisher_count=issue.publisher_count,
            articles_last_hour=sum(a.published_at >= hour_ago for a in arts),
            touches_holding=bool(codes & holdings), touches_watchlist=bool(codes & watch),
            has_disclosure=issue.has_disclosure,
        ))
        issue.importance = score

        # 재요약 조건: 요약이 없거나, 기사 수가 RESUMMARIZE_GROWTH_RATIO 이상 늘었을 때
        need = issue.summarized_article_count == 0 or (
            issue.article_count >= issue.summarized_article_count * (1 + s.resummarize_growth_ratio))
        if need:
            bodies = dict(db.execute(select(ArticleBody.article_id, ArticleBody.body)
                                     .where(ArticleBody.article_id.in_([a.id for a in arts]))).all())
            summary = summarizer.summarize([
                ArticleInput(id=str(a.id), title=a.title, publisher=a.publisher, published_at=a.published_at,
                             snippet=a.snippet, body=bodies.get(a.id), kind=a.kind, sentiment=a.sentiment,
                             tickers=list(a.tickers or []))
                for a in arts])
            db.execute(update(IssueSummaryRow).where(IssueSummaryRow.issue_id == issue.id)
                       .values(is_current=False))
            db.add(IssueSummaryRow(issue_id=issue.id, generated_by=summary.generated_by,
                                   payload=summary.model_dump(), is_current=True))
            issue.sentiment = summary.sentiment
            issue.summarized_article_count = issue.article_count
            done += 1

        if not issue.alerted and score >= s.alert_importance_threshold:
            from ..notify.telegram import send_issue_alert
            if send_issue_alert(issue.id, score, db):
                issue.alerted = True
    db.flush()
    return done


def close_stale_issues(db: Session) -> int:
    """윈도우를 벗어난 이슈는 closed 로 바꿔 클러스터 후보에서 뺀다."""
    cutoff = _now() - timedelta(hours=get_settings().cluster_window_hours)
    res = db.execute(update(Issue).where(Issue.status == "active", Issue.last_seen < cutoff)
                     .values(status="closed"))
    return res.rowcount or 0

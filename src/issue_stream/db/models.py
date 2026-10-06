"""DB 스키마.

기획서의 핵심 테이블 5개(articles, issues, issue_articles, tickers, issue_tickers)에
빠져 있던 운영용 테이블을 추가했다.
  - article_bodies : 본문 임시 보관 (TTL 지나면 삭제, 저작권 대응)
  - issue_summaries: 요약 이력. provider별 결과를 남겨 무료/유료 품질 비교에 사용
  - dart_corp_codes: 종목코드 ↔ DART 고유번호 매핑
  - prices, macro_series: 시세·거시 지표
  - job_runs, api_usage: 모니터링 (작업 성공/실패, 무료 API 쿼터 사용량)

SQLite(기본, 설치 불필요)와 PostgreSQL 모두에서 동작하도록 DB 전용 기능(pgvector, JSONB)을 쓰지 않는다.
임베딩은 float32 바이트로 저장하고 유사도는 파이썬에서 계산한다. 모델을 바꾸면 `issue-stream reembed`.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON, BigInteger, Boolean, Date, Float, ForeignKey, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from .types import BigIntPK, UTCDateTime, Vector


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Ticker(Base):
    __tablename__ = "tickers"
    code: Mapped[str] = mapped_column(String(12), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), index=True)
    market: Mapped[str | None] = mapped_column(String(10))       # KOSPI / KOSDAQ
    sector: Mapped[str | None] = mapped_column(String(100))
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    in_watchlist: Mapped[bool] = mapped_column(Boolean, default=False)
    holding: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=_utcnow, onupdate=_utcnow)


class DartCorpCode(Base):
    __tablename__ = "dart_corp_codes"
    corp_code: Mapped[str] = mapped_column(String(8), primary_key=True)
    corp_name: Mapped[str] = mapped_column(String(200))
    stock_code: Mapped[str | None] = mapped_column(String(12), index=True)
    modify_date: Mapped[str | None] = mapped_column(String(8))


class Article(Base):
    __tablename__ = "articles"
    __table_args__ = (UniqueConstraint("source", "external_id"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    source: Mapped[str] = mapped_column(String(80), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="news")   # news | disclosure
    external_id: Mapped[str] = mapped_column(String(500))
    title: Mapped[str] = mapped_column(Text)
    norm_title: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    publisher: Mapped[str | None] = mapped_column(String(100))
    published_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    collected_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_utcnow)
    snippet: Mapped[str | None] = mapped_column(Text)             # 짧은 요약문만 저장
    simhash: Mapped[int] = mapped_column(BigInteger, index=True)
    duplicate_of: Mapped[int | None] = mapped_column(ForeignKey("articles.id", ondelete="SET NULL"))
    tickers: Mapped[list] = mapped_column(JSON, default=list)      # ["005930", ...]
    ticker_keys: Mapped[str] = mapped_column(Text, default="")      # ",005930,000660," (종목별 검색용)
    embedding = mapped_column(Vector, nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(100))
    sentiment: Mapped[str | None] = mapped_column(String(10))


class ArticleBody(Base):
    """본문 임시 저장소. FETCH_ARTICLE_BODY=true 일 때만 채워지고 TTL 후 삭제된다."""
    __tablename__ = "article_bodies"
    article_id: Mapped[int] = mapped_column(ForeignKey("articles.id", ondelete="CASCADE"), primary_key=True)
    body: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)


class Issue(Base):
    __tablename__ = "issues"
    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    centroid = mapped_column(Vector, nullable=True)
    first_seen: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    last_seen: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    article_count: Mapped[int] = mapped_column(Integer, default=0)
    publisher_count: Mapped[int] = mapped_column(Integer, default=0)
    has_disclosure: Mapped[bool] = mapped_column(Boolean, default=False)
    importance: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    sentiment: Mapped[str | None] = mapped_column(String(10))
    summarized_article_count: Mapped[int] = mapped_column(Integer, default=0)  # 재요약 판단용
    alerted: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(10), default="active")          # active | closed

    articles: Mapped[list[IssueArticle]] = relationship(back_populates="issue", cascade="all, delete-orphan")
    tickers: Mapped[list[IssueTicker]] = relationship(back_populates="issue", cascade="all, delete-orphan")
    summaries: Mapped[list[IssueSummaryRow]] = relationship(back_populates="issue",
                                                            cascade="all, delete-orphan")


class IssueArticle(Base):
    __tablename__ = "issue_articles"
    issue_id: Mapped[int] = mapped_column(ForeignKey("issues.id", ondelete="CASCADE"), primary_key=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("articles.id", ondelete="CASCADE"), primary_key=True)
    similarity: Mapped[float] = mapped_column(Float, default=1.0)
    issue: Mapped[Issue] = relationship(back_populates="articles")


class IssueTicker(Base):
    __tablename__ = "issue_tickers"
    issue_id: Mapped[int] = mapped_column(ForeignKey("issues.id", ondelete="CASCADE"), primary_key=True)
    ticker: Mapped[str] = mapped_column(ForeignKey("tickers.code"), primary_key=True)
    mentions: Mapped[int] = mapped_column(Integer, default=1)
    issue: Mapped[Issue] = relationship(back_populates="tickers")


class IssueSummaryRow(Base):
    __tablename__ = "issue_summaries"
    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    issue_id: Mapped[int] = mapped_column(ForeignKey("issues.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_utcnow)
    generated_by: Mapped[str] = mapped_column(String(60))   # extractive / ollama:qwen2.5 / anthropic:haiku
    payload: Mapped[dict] = mapped_column(JSON)             # IssueSummary 전체
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    issue: Mapped[Issue] = relationship(back_populates="summaries")


class Price(Base):
    __tablename__ = "prices"
    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)   # 종목코드 또는 지수 심볼
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    open: Mapped[float | None] = mapped_column(Float)
    high: Mapped[float | None] = mapped_column(Float)
    low: Mapped[float | None] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float | None] = mapped_column(Float)
    change_pct: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(20))


class SectorIndex(Base):
    """업종 히트맵용 등락률. 기본은 업종 ETF(KODEX·TIGER) 종가로 계산 (KRX 로그인 불필요)."""
    __tablename__ = "sector_indices"
    market: Mapped[str] = mapped_column(String(10), primary_key=True)   # ETF / KOSPI ...
    name: Mapped[str] = mapped_column(String(60), primary_key=True)     # 반도체, 은행 ...
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    close: Mapped[float | None] = mapped_column(Float)
    change_pct: Mapped[float | None] = mapped_column(Float)
    trading_value: Mapped[float | None] = mapped_column(Float)          # 거래대금
    source: Mapped[str] = mapped_column(String(20), default="naver")
    symbol: Mapped[str | None] = mapped_column(String(20))              # 계산에 쓴 ETF 코드


class MacroSeries(Base):
    __tablename__ = "macro_series"
    series_id: Mapped[str] = mapped_column(String(60), primary_key=True)  # "ecos:722Y001:0101000"
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    value: Mapped[float] = mapped_column(Float)
    name: Mapped[str | None] = mapped_column(String(100))


class JobRun(Base):
    __tablename__ = "job_runs"
    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    job: Mapped[str] = mapped_column(String(60), index=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    status: Mapped[str] = mapped_column(String(10))          # ok | error | skipped
    items: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str | None] = mapped_column(Text)


class ApiUsage(Base):
    __tablename__ = "api_usage"
    source: Mapped[str] = mapped_column(String(30), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    calls: Mapped[int] = mapped_column(Integer, default=0)

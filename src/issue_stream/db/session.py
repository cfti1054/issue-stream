"""DB 연결.

기본은 SQLite 파일(data/issue_stream.db). DATABASE_URL 로 PostgreSQL 을 지정할 수도 있다.
엔진은 처음 쓸 때 만든다 (테스트·CLI 에서 설정을 바꾼 뒤 연결할 수 있도록).
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..core.config import DEFAULT_DATABASE_URL, LEGACY_DOCKER_PG_URL, get_settings

log = logging.getLogger(__name__)

_engine: Engine | None = None
_factory: sessionmaker | None = None


def _sqlite_pragmas(dbapi_conn, _record) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")      # API 읽기와 스케줄러 쓰기가 동시에 가능
    cur.execute("PRAGMA busy_timeout=30000")
    cur.execute("PRAGMA foreign_keys=ON")       # ON DELETE CASCADE 동작
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.close()


def _make_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        path = url.split(":///", 1)[-1]
        if path and path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        eng = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})
        event.listen(eng, "connect", _sqlite_pragmas)
        return eng
    return create_engine(url, pool_pre_ping=True)


def resolve_url() -> str:
    url = get_settings().database_url
    if url == LEGACY_DOCKER_PG_URL:
        # 예전 기본값(Docker Postgres). Docker 없이도 돌아가도록 연결 실패 시 SQLite 로 대체.
        try:
            eng = create_engine(url, connect_args={"connect_timeout": 3})
            with eng.connect() as c:
                c.execute(text("SELECT 1"))
            eng.dispose()
        except Exception:
            log.warning("Postgres(%s)에 연결할 수 없어 SQLite(%s)를 사용합니다. "
                        ".env 의 DATABASE_URL 줄을 지우면 이 경고가 사라집니다.", url, DEFAULT_DATABASE_URL)
            return DEFAULT_DATABASE_URL
    return url


def get_engine() -> Engine:
    global _engine, _factory
    if _engine is None:
        _engine = _make_engine(resolve_url())
        _factory = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def reset_engine() -> None:
    """설정을 바꾼 뒤 다시 연결할 때 (테스트용)."""
    global _engine, _factory
    if _engine is not None:
        _engine.dispose()
    _engine, _factory = None, None


def SessionLocal() -> Session:  # noqa: N802 (기존 호출부 호환)
    get_engine()
    return _factory()


@contextmanager
def session_scope():
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()

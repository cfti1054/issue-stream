"""엔티티 테이블의 id / no 컬럼.

  id  내부 PK. 이름 있는 시퀀스 seq_<테이블>_id 로 채운다. FK 는 이 값만 참조하고 화면·API 에는 내보내지 않는다.
  no  사람이 보는 번호 (화면·URL·알림). 별도 시퀀스 seq_<테이블>_no 로 채우고 UNIQUE.

PostgreSQL: 두 컬럼 모두 DB 기본값(DEFAULT nextval(...))을 걸어 SQL 로 직접 INSERT 해도 번호가 매겨진다.
SQLite    : 시퀀스가 없어 id 는 INTEGER PRIMARY KEY 자동 증가, no 는 INSERT 트리거로 MAX(no)+1 을 채운다.
매핑 테이블(user_watchlist, issue_articles, issue_tickers)은 FK 복합키만 쓰고 시퀀스를 두지 않는다.
"""
from __future__ import annotations

from sqlalchemy import DDL, BigInteger, FetchedValue, Index, Sequence, Table, event
from sqlalchemy.orm import mapped_column

from .types import BigIntPK

ENTITY_TABLES = ("users", "articles", "issues", "issue_summaries", "job_runs")


def id_column(table: str):
    return mapped_column(BigIntPK, Sequence(f"seq_{table}_id"), primary_key=True,
                         comment="내부 PK (FK 전용, 화면에 노출하지 않음)")


def no_column():
    # 값은 DB 가 채운다 (PG 기본값·SQLite 트리거). FetchedValue → INSERT 후 ORM 이 다시 읽어 온다.
    # SQLite 트리거는 INSERT 뒤에 채우므로 컬럼 정의는 NULL 허용. PG 는 pg_ddl 에서 NOT NULL 을 건다.
    return mapped_column(BigInteger, server_default=FetchedValue(), nullable=True, comment="화면·API 에 보이는 번호")


def pg_ddl(t: str) -> list[str]:
    """테이블과 seq_<t>_id 가 만들어진 뒤 실행 (seq_<t>_no 생성, 기본값·소유 연결)."""
    return [
        f"CREATE SEQUENCE IF NOT EXISTS seq_{t}_no",
        f"ALTER SEQUENCE seq_{t}_id OWNED BY {t}.id",
        f"ALTER SEQUENCE seq_{t}_no OWNED BY {t}.no",
        f"ALTER TABLE {t} ALTER COLUMN id SET DEFAULT nextval('seq_{t}_id')",
        f"ALTER TABLE {t} ALTER COLUMN no SET DEFAULT nextval('seq_{t}_no')",
        f"ALTER TABLE {t} ALTER COLUMN no SET NOT NULL",
    ]


def sqlite_ddl(t: str) -> list[str]:
    # SQLite 는 쓰기가 한 번에 하나라 트리거 안의 MAX(no)+1 이 겹치지 않는다
    return [
        f"CREATE TRIGGER IF NOT EXISTS trg_{t}_no AFTER INSERT ON {t} FOR EACH ROW WHEN NEW.no IS NULL "
        f"BEGIN UPDATE {t} SET no = (SELECT COALESCE(MAX(no), 0) + 1 FROM {t}) WHERE id = NEW.id; END",
    ]


def register(table: Table) -> None:
    """id/no 테이블에 no UNIQUE 인덱스와 DB 별 DDL(테이블 생성 직후 실행)을 붙인다."""
    t = table.name
    Index(f"uq_{t}_no", table.c.no, unique=True)
    for stmt in pg_ddl(t):
        event.listen(table, "after_create", DDL(stmt).execute_if(dialect="postgresql"))
    for stmt in sqlite_ddl(t):
        event.listen(table, "after_create", DDL(stmt).execute_if(dialect="sqlite"))

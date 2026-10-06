"""DB 종류와 무관한 upsert (SQLite·PostgreSQL 모두 ON CONFLICT 지원)."""
from __future__ import annotations

from sqlalchemy.orm import Session


def _insert(db: Session, model):
    if db.get_bind().dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    return insert(model)


def upsert(db: Session, model, values: dict, keys: list[str], update: list[str] | None = None) -> None:
    """keys 가 겹치면 update 컬럼만 갱신 (update 가 None 이면 keys 외 전부, [] 이면 무시)."""
    stmt = _insert(db, model).values(**values)
    cols = [k for k in values if k not in keys] if update is None else update
    if cols:
        stmt = stmt.on_conflict_do_update(index_elements=keys, set_={c: stmt.excluded[c] for c in cols})
    else:
        stmt = stmt.on_conflict_do_nothing(index_elements=keys)
    db.execute(stmt)


def insert_ignore_returning_id(db: Session, model, values: dict, keys: list[str]):
    """중복이면 None, 새로 넣었으면 id."""
    stmt = (_insert(db, model).values(**values)
            .on_conflict_do_nothing(index_elements=keys).returning(model.id))
    return db.execute(stmt).scalar()

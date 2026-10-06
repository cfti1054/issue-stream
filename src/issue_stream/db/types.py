"""DB 종류(SQLite / PostgreSQL)와 무관하게 동작하는 컬럼 타입."""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
from sqlalchemy import BigInteger, DateTime, Integer, LargeBinary
from sqlalchemy.types import TypeDecorator

# SQLite 는 INTEGER PRIMARY KEY 만 자동 증가하므로 BIGINT 대신 INTEGER 를 쓴다.
BigIntPK = BigInteger().with_variant(Integer(), "sqlite")


class UTCDateTime(TypeDecorator):
    """항상 UTC 로 저장하고, 읽을 때 tzinfo=UTC 를 붙여 돌려준다.

    SQLite 는 시간대를 저장하지 못해 naive datetime 이 돌아오므로, 비교 시 오류가 나지 않도록 통일한다.
    """
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        value = value.astimezone(timezone.utc)
        return value.replace(tzinfo=None) if dialect.name == "sqlite" else value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, str):
            value = datetime.fromisoformat(value)
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class Vector(TypeDecorator):
    """float32 벡터를 바이트로 저장한다. 유사도 계산은 파이썬(numpy)에서 하므로 pgvector 가 필요 없다."""
    impl = LargeBinary
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return np.asarray(value, dtype=np.float32).tobytes()

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return np.frombuffer(value, dtype=np.float32).copy()

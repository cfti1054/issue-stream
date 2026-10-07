"""split entity PKs into id (named sequence) / no (display number)

기존 DB 를 db/sequences.py 규칙으로 바꾼다. 새 DB 는 0001 에서 이미 이 구조로 만들어지므로 건너뛴다.
  PostgreSQL: <t>_id_seq(BIGSERIAL) → seq_<t>_id 로 이름 변경, no 컬럼 + seq_<t>_no 추가
  SQLite    : no 컬럼 + 트리거 추가
기존 행의 no 는 id 와 같은 값으로 채운다 (지금까지 화면에 보이던 번호가 그대로 유지된다).

Revision ID: 0004
Revises: 0003
"""
import sqlalchemy as sa
from alembic import op

from issue_stream.db.sequences import ENTITY_TABLES, pg_ddl, sqlite_ddl

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def _has_no(bind, t: str) -> bool:
    return "no" in {c["name"] for c in sa.inspect(bind).get_columns(t)}


def upgrade():
    bind = op.get_bind()
    pg = bind.dialect.name == "postgresql"
    for t in ENTITY_TABLES:
        if _has_no(bind, t):
            continue
        if pg:
            old = bind.scalar(sa.text("SELECT pg_get_serial_sequence(:t, 'id')"), {"t": t})
            if old and old.split(".")[-1] != f"seq_{t}_id":
                op.execute(f"ALTER SEQUENCE {old} RENAME TO seq_{t}_id")
            elif not old:
                op.execute(f"CREATE SEQUENCE IF NOT EXISTS seq_{t}_id")
                op.execute(f"SELECT setval('seq_{t}_id', COALESCE((SELECT MAX(id) FROM {t}), 0) + 1, false)")
            op.execute(f"ALTER TABLE {t} ADD COLUMN no BIGINT")
            op.execute(f"UPDATE {t} SET no = id")
            op.execute(f"CREATE SEQUENCE IF NOT EXISTS seq_{t}_no")
            op.execute(f"SELECT setval('seq_{t}_no', COALESCE((SELECT MAX(no) FROM {t}), 0) + 1, false)")
            op.execute(f"CREATE UNIQUE INDEX uq_{t}_no ON {t} (no)")
            for stmt in pg_ddl(t):
                op.execute(stmt)
        else:
            op.execute(f"ALTER TABLE {t} ADD COLUMN no BIGINT")
            op.execute(f"UPDATE {t} SET no = id")
            op.execute(f"CREATE UNIQUE INDEX uq_{t}_no ON {t} (no)")
            for stmt in sqlite_ddl(t):
                op.execute(stmt)


def downgrade():
    bind = op.get_bind()
    pg = bind.dialect.name == "postgresql"
    for t in ENTITY_TABLES:
        if not _has_no(bind, t):
            continue
        op.execute(f"DROP INDEX IF EXISTS uq_{t}_no")
        if pg:
            op.execute(f"ALTER TABLE {t} DROP COLUMN no")       # OWNED BY 라 seq_<t>_no 도 함께 삭제
            op.execute(f"ALTER SEQUENCE seq_{t}_id RENAME TO {t}_id_seq")
        else:
            op.execute(f"DROP TRIGGER IF EXISTS trg_{t}_no")
            with op.batch_alter_table(t) as b:
                b.drop_column("no")

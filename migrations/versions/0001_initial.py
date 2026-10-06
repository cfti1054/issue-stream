"""initial schema

현재 models.py 의 전체 스키마를 만든다 (SQLite·PostgreSQL 공통, 확장 기능 불필요).
이후 스키마 변경은 `alembic revision --autogenerate -m "..."` 로 추가한다.

Revision ID: 0001
Revises:
"""
from alembic import op

from issue_stream.db.models import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    Base.metadata.create_all(bind=op.get_bind())


def downgrade():
    Base.metadata.drop_all(bind=op.get_bind())

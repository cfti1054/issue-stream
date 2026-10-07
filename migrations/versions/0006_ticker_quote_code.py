"""US stocks: tickers.quote_code (Naver world-stock code, e.g. NVDA.O)

Revision ID: 0006
Revises: 0005
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def _has(bind) -> bool:
    return "quote_code" in {c["name"] for c in sa.inspect(bind).get_columns("tickers")}


def upgrade():
    bind = op.get_bind()
    if _has(bind):
        return   # 새 DB 는 0001 에서 이미 만들어진다
    op.add_column("tickers", sa.Column("quote_code", sa.String(20), nullable=True,
                                       comment="해외 시세 조회 코드 (네이버, 예: NVDA.O)"))


def downgrade():
    bind = op.get_bind()
    if not _has(bind):
        return
    with op.batch_alter_table("tickers") as b:
        b.drop_column("quote_code")

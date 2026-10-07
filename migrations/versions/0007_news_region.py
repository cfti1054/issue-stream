"""US market news: articles.region, issues.region (kr|us), tickers.name_en

기존 기사·이슈는 kr 로 채운다 (새로 수집되는 기사부터 pipeline/region.py 로 판정).
tickers.name_en 은 다음 미국 종목 목록 동기화(시작 시 자동)에서 채워진다.

Revision ID: 0007
Revises: 0006
"""
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

COLUMNS = [
    ("articles", sa.Column("region", sa.String(2), nullable=False, server_default="kr",
                           comment="kr 국내 / us 미국 시장 (pipeline/region.py)")),
    ("issues", sa.Column("region", sa.String(2), nullable=False, server_default="kr",
                         comment="kr 국내 / us 미국 (기사 지역 다수결)")),
    ("tickers", sa.Column("name_en", sa.String(100), nullable=True,
                          comment="영문 이름 (미국 종목, 영어 기사 태깅용)")),
]


def _cols(bind, table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def upgrade():
    bind = op.get_bind()
    for table, col in COLUMNS:
        if col.name not in _cols(bind, table):   # 새 DB 는 0001 에서 이미 만들어진다
            op.add_column(table, col)
    names = {ix["name"] for ix in sa.inspect(bind).get_indexes("issues")}
    if "ix_issues_region" not in names:
        op.create_index("ix_issues_region", "issues", ["region"])


def downgrade():
    bind = op.get_bind()
    op.execute("DROP INDEX IF EXISTS ix_issues_region")
    for table, col in COLUMNS:
        if col.name in _cols(bind, table):
            with op.batch_alter_table(table) as b:
                b.drop_column(col.name)

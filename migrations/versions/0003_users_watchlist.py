"""login accounts and per-user watchlist

Revision ID: 0003
Revises: 0002
"""
from alembic import op

from issue_stream.db.models import User, UserSession, UserWatchlist

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

TABLES = (User, UserSession, UserWatchlist)


def upgrade():
    for m in TABLES:
        m.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade():
    for m in reversed(TABLES):
        m.__table__.drop(bind=op.get_bind(), checkfirst=True)

"""sector indices for dashboard heatmap

Revision ID: 0002
Revises: 0001
"""
from alembic import op

from issue_stream.db.models import SectorIndex

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    SectorIndex.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade():
    SectorIndex.__table__.drop(bind=op.get_bind(), checkfirst=True)

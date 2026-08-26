"""Add browser-driven installation state.

Revision ID: 20260824_0004
Revises: 20260824_0003
"""

from alembic import op
from nextgateway.db import Base

revision = "20260824_0004"
down_revision = "20260824_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.tables["installation_state"].create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    op.drop_table("installation_state")

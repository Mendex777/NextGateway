"""Add subscriptions."""

from alembic import op
from nextgateway.db import Base

revision = "20260824_0002"
down_revision = "20260824_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    table = Base.metadata.tables["subscriptions"]
    table.create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    Base.metadata.tables["subscriptions"].drop(bind=op.get_bind(), checkfirst=True)

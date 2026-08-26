"""Add local authentication."""

from alembic import op
from nextgateway.db import Base

revision = "20260824_0003"
down_revision = "20260824_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.tables["local_users"].create(bind=bind, checkfirst=True)
    Base.metadata.tables["auth_sessions"].create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.tables["auth_sessions"].drop(bind=bind, checkfirst=True)
    Base.metadata.tables["local_users"].drop(bind=bind, checkfirst=True)

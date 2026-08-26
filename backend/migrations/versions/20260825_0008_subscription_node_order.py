"""Preserve provider order for subscription nodes.

Revision ID: 20260825_0008
Revises: 20260825_0007
"""

import sqlalchemy as sa
from alembic import op

revision = "20260825_0008"
down_revision = "20260825_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("subscription_nodes")}
    if "position" not in columns:
        op.add_column(
            "subscription_nodes",
            sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    op.drop_column("subscription_nodes", "position")

"""Track resumable setup operations.

Revision ID: 20260824_0005
Revises: 20260824_0004
"""

import sqlalchemy as sa
from alembic import op

revision = "20260824_0005"
down_revision = "20260824_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = sa.inspect(op.get_bind()).get_columns("installation_state")
    existing = {column["name"] for column in columns}
    with op.batch_alter_table("installation_state") as batch:
        if "operation_kind" not in existing:
            batch.add_column(sa.Column("operation_kind", sa.String(length=32), nullable=True))
        if "operation_id" not in existing:
            batch.add_column(sa.Column("operation_id", sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("installation_state") as batch:
        batch.drop_column("operation_id")
        batch.drop_column("operation_kind")

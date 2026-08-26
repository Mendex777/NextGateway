"""Allow nodes to be shared by multiple subscriptions.

Revision ID: 20260824_0006
Revises: 20260824_0005
"""

import uuid

import sqlalchemy as sa
from alembic import op
from nextgateway.db import Base

revision = "20260824_0006"
down_revision = "20260824_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.tables["subscription_nodes"].create(bind=op.get_bind(), checkfirst=True)
    connection = op.get_bind()
    rows = connection.execute(
        sa.text("SELECT id, source_ref FROM nodes WHERE source_ref IS NOT NULL")
    )
    for node_id, subscription_id in rows:
        connection.execute(
            sa.text(
                "INSERT INTO subscription_nodes (id, subscription_id, node_id) "
                "VALUES (:id, :subscription_id, :node_id)"
            ),
            {
                "id": str(uuid.uuid4()),
                "subscription_id": subscription_id,
                "node_id": node_id,
            },
        )


def downgrade() -> None:
    op.drop_table("subscription_nodes")

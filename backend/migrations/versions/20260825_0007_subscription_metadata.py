"""Add subscription metadata and node probe results.

Revision ID: 20260825_0007
Revises: 20260824_0006
"""

import sqlalchemy as sa
from alembic import op

revision = "20260825_0007"
down_revision = "20260824_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    subscription_columns = {column["name"] for column in inspector.get_columns("subscriptions")}
    for name, column_type in (
        ("remote_name", sa.String(255)),
        ("upload_bytes", sa.BigInteger()),
        ("download_bytes", sa.BigInteger()),
        ("total_bytes", sa.BigInteger()),
        ("expires_at", sa.DateTime(timezone=True)),
        ("announcement", sa.Text()),
        ("support_url", sa.String(2048)),
        ("web_url", sa.String(2048)),
    ):
        if name not in subscription_columns:
            op.add_column("subscriptions", sa.Column(name, column_type, nullable=True))
    node_columns = {column["name"] for column in inspector.get_columns("nodes")}
    if "last_latency_ms" not in node_columns:
        op.add_column("nodes", sa.Column("last_latency_ms", sa.Integer(), nullable=True))
    if "last_probe_at" not in node_columns:
        op.add_column(
            "nodes", sa.Column("last_probe_at", sa.DateTime(timezone=True), nullable=True)
        )
    if "last_probe_error" not in node_columns:
        op.add_column("nodes", sa.Column("last_probe_error", sa.Text(), nullable=True))


def downgrade() -> None:
    for name in ("last_probe_error", "last_probe_at", "last_latency_ms"):
        op.drop_column("nodes", name)
    for name in (
        "web_url", "support_url", "announcement", "expires_at", "total_bytes",
        "download_bytes", "upload_bytes", "remote_name",
    ):
        op.drop_column("subscriptions", name)

"""nested proxy groups and rule providers"""

from alembic import op
import sqlalchemy as sa

revision = "20260827_0009"
down_revision = "20260825_0008"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    columns = {item["name"] for item in inspector.get_columns("proxy_groups")}
    if "include_direct" not in columns:
        op.add_column("proxy_groups", sa.Column("include_direct", sa.Boolean(), nullable=False, server_default=sa.false()))
    if "include_reject" not in columns:
        op.add_column("proxy_groups", sa.Column("include_reject", sa.Boolean(), nullable=False, server_default=sa.false()))
    tables = set(inspector.get_table_names())
    if "proxy_group_group_members" not in tables:
        op.create_table(
        "proxy_group_group_members",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("group_id", sa.String(36), sa.ForeignKey("proxy_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("member_group_id", sa.String(36), sa.ForeignKey("proxy_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.UniqueConstraint("group_id", "member_group_id"),
        )
    if "rule_providers" not in tables:
        op.create_table(
        "rule_providers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("behavior", sa.String(16), nullable=False),
        sa.Column("format", sa.String(16), nullable=False),
        sa.Column("url", sa.Text()), sa.Column("path", sa.Text()),
        sa.Column("interval", sa.Integer(), nullable=False),
        sa.Column("proxy", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )


def downgrade():
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "rule_providers" in tables:
        op.drop_table("rule_providers")
    if "proxy_group_group_members" in tables:
        op.drop_table("proxy_group_group_members")
    columns = {item["name"] for item in inspector.get_columns("proxy_groups")}
    if "include_reject" in columns:
        op.drop_column("proxy_groups", "include_reject")
    if "include_direct" in columns:
        op.drop_column("proxy_groups", "include_direct")

"""add proxy profiles and account proxy assignment

Revision ID: 20260329_120000_add_proxy_profiles
Revises: 20260325_000000_add_request_log_cost
Create Date: 2026-03-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision = "20260329_120000_add_proxy_profiles"
down_revision = "20260325_000000_add_request_log_cost"
branch_labels = None
depends_on = None


def _table_exists(connection: Connection, table_name: str) -> bool:
    inspector = sa.inspect(connection)
    return inspector.has_table(table_name)


def _columns(connection: Connection, table_name: str) -> set[str]:
    inspector = sa.inspect(connection)
    if not inspector.has_table(table_name):
        return set()
    return {str(column["name"]) for column in inspector.get_columns(table_name) if column.get("name") is not None}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("proxy_profiles"):
        op.create_table(
            "proxy_profiles",
            sa.Column("id", sa.String(), primary_key=True, nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("protocol", sa.String(), nullable=False, server_default=sa.text("'vless'")),
            sa.Column("transport_kind", sa.String(), nullable=False),
            sa.Column("server_host", sa.String(), nullable=False),
            sa.Column("server_port", sa.Integer(), nullable=False),
            sa.Column("local_proxy_port", sa.Integer(), nullable=False),
            sa.Column("uri_encrypted", sa.LargeBinary(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("name", name="uq_proxy_profiles_name"),
            sa.UniqueConstraint("local_proxy_port", name="uq_proxy_profiles_local_proxy_port"),
        )

    account_columns = _columns(bind, "accounts")
    with op.batch_alter_table("accounts") as batch_op:
        if "proxy_assignment_mode" not in account_columns:
            batch_op.add_column(
                sa.Column(
                    "proxy_assignment_mode",
                    sa.String(),
                    nullable=False,
                    server_default=sa.text("'inherit_default'"),
                )
            )
        if "proxy_profile_id" not in account_columns:
            batch_op.add_column(sa.Column("proxy_profile_id", sa.String(), nullable=True))
            batch_op.create_foreign_key(
                "fk_accounts_proxy_profile_id_proxy_profiles",
                "proxy_profiles",
                ["proxy_profile_id"],
                ["id"],
                ondelete="SET NULL",
            )

    settings_columns = _columns(bind, "dashboard_settings")
    if _table_exists(bind, "dashboard_settings"):
        with op.batch_alter_table("dashboard_settings") as batch_op:
            if "default_proxy_profile_id" not in settings_columns:
                batch_op.add_column(sa.Column("default_proxy_profile_id", sa.String(), nullable=True))
                batch_op.create_foreign_key(
                    "fk_dashboard_settings_default_proxy_profile_id_proxy_profiles",
                    "proxy_profiles",
                    ["default_proxy_profile_id"],
                    ["id"],
                    ondelete="SET NULL",
                )


def downgrade() -> None:
    return

"""Coffre a secrets, fournisseurs d'IA, modele par tache et journal des appels.

Uniquement des ajouts : aucune table ni colonne existante n'est modifiee.
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "secrets",
        sa.Column("name", sa.String(100), primary_key=True),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("hint", sa.String(12), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "ai_providers",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("base_url", sa.String(300), nullable=False),
        sa.Column("last_test_ok", sa.Boolean(), nullable=True),
        sa.Column("last_test_message", sa.String(300), nullable=False),
        sa.Column("last_test_key_checked", sa.Boolean(), nullable=False),
        sa.Column("last_test_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "task_models",
        sa.Column("task", sa.String(40), primary_key=True),
        sa.Column("provider_id", sa.String(40), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("fallback_provider_id", sa.String(40), nullable=False),
        sa.Column("fallback_model", sa.String(200), nullable=False),
        sa.Column("allow_paid_fallback", sa.Boolean(), nullable=False),
        sa.Column("temperature", sa.Float(), nullable=True),
        sa.Column("max_tokens", sa.Integer(), nullable=True),
        sa.Column("strict_json", sa.Boolean(), nullable=False),
        sa.Column("timeout_s", sa.Float(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "ai_calls",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("task", sa.String(40), nullable=False),
        sa.Column("provider_id", sa.String(40), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("mode", sa.String(10), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("used_fallback", sa.Boolean(), nullable=False),
        sa.Column("error_kind", sa.String(30), nullable=False),
        sa.Column("error", sa.String(300), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=True),
    )
    op.create_index("ix_ai_calls_created_at", "ai_calls", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_ai_calls_created_at", table_name="ai_calls")
    for table in ("ai_calls", "task_models", "ai_providers", "secrets"):
        op.drop_table(table)

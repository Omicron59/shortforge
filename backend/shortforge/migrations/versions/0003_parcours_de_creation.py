"""Nouveau parcours de creation : brief, idees enrichies, storyboard (texte a l'ecran, intention visuelle).

Uniquement des ajouts : une table et des colonnes avec valeur par defaut. Rien n'est supprime ni renomme.
"""

from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

IDEAS: tuple[sa.Column[Any], ...] = (
    sa.Column("summary", sa.Text(), nullable=False, server_default=""),
    sa.Column("difficulty", sa.String(20), nullable=False, server_default=""),
    sa.Column("resources", sa.JSON(), nullable=False, server_default="[]"),
    sa.Column("fit_reason", sa.Text(), nullable=False, server_default=""),
    sa.Column("saved", sa.Boolean(), nullable=False, server_default="0"),
    sa.Column("batch", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("parent_id", sa.String(32), nullable=True),
)
SCENES: tuple[sa.Column[Any], ...] = (
    sa.Column("on_screen_text", sa.Text(), nullable=False, server_default=""),
    sa.Column("visual_intent", sa.Text(), nullable=False, server_default=""),
    sa.Column("visual_changed_at", sa.DateTime(), nullable=True),
)


def upgrade() -> None:
    op.create_table(
        "briefs",
        sa.Column("project_id", sa.String(32), sa.ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("niche", sa.String(200), nullable=False),
        sa.Column("audience", sa.String(300), nullable=False),
        sa.Column("goal", sa.String(30), nullable=False),
        sa.Column("language", sa.String(10), nullable=False),
        sa.Column("tone", sa.String(30), nullable=False),
        sa.Column("duration_s", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(30), nullable=False),
        sa.Column("visual_style", sa.String(300), nullable=False),
        sa.Column("constraints", sa.Text(), nullable=False),
        sa.Column("avoid", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    for column in IDEAS:
        op.add_column("ideas", column)
    for column in SCENES:
        op.add_column("scenes", column)
    op.add_column("projects", sa.Column("content_changed_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("content_changed_at")
    with op.batch_alter_table("scenes") as batch:
        for column in SCENES:
            batch.drop_column(column.name)
    with op.batch_alter_table("ideas") as batch:
        for column in IDEAS:
            batch.drop_column(column.name)
    op.drop_table("briefs")

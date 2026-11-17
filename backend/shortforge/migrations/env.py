"""Environnement Alembic : la connexion est fournie par `shortforge.migrations.migrate`."""

from alembic import context

from shortforge import models  # noqa: F401  (enregistre les modeles)
from shortforge.db import Base

context.configure(connection=context.config.attributes["connection"], target_metadata=Base.metadata,
                  render_as_batch=True)
with context.begin_transaction():
    context.run_migrations()

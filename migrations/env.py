"""Alembic environment — connects to the app's PostgreSQL via src.config."""

from __future__ import annotations

import urllib.parse
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, text

alembic_cfg = context.config

if alembic_cfg.config_file_name is not None:
    fileConfig(alembic_cfg.config_file_name)


def _db_url() -> str:
    from src import config as app_config  # noqa: PLC0415

    pw = urllib.parse.quote_plus(app_config.PG_PASSWORD)
    return (
        f"postgresql+psycopg://{app_config.PG_USER}:{pw}"
        f"@{app_config.PG_HOST}:{app_config.PG_PORT}/{app_config.PG_DB}"
    )


def run_migrations_online() -> None:
    engine = create_engine(_db_url(), echo=False)
    with engine.connect() as conn:
        context.configure(
            connection=conn,
            target_metadata=None,
            version_table="alembic_version",
            compare_type=False,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


def run_migrations_offline() -> None:
    """Generate SQL script for offline review without a live DB."""
    context.configure(
        url=_db_url(),
        target_metadata=None,
        version_table="alembic_version",
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

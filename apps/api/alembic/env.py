from __future__ import annotations

from logging.config import fileConfig
from pathlib import Path
import sys
from typing import Any

from alembic import context
import sqlalchemy as sa
from sqlalchemy import engine_from_config, inspect, pool, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from edu_grader_api.db import Base
from edu_grader_api import models  # noqa: F401
from edu_grader_api.settings import settings

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def configure_version_table_capacity(connection: Any | None) -> None:
    """Allow revision identifiers longer than Alembic's legacy 32-character default."""
    migration_context = context.get_context()
    migration_context._version.c.version_num.type = sa.String(128)
    if connection is None or connection.dialect.name != "postgresql":
        return
    if "alembic_version" not in inspect(connection).get_table_names():
        return
    connection.execute(
        text("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(128)")
    )


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    configure_version_table_capacity(None)

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        configure_version_table_capacity(connection)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

"""
Alembic migration environment.

DATABASE_URL is loaded from the application's environment.

Local:

    sqlite:///./social_links.db

Production:

    postgresql+psycopg://username:password@rds-host:5432/social_links
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import settings
from app.database import Base

# Import models so SQLAlchemy registers all model tables
# inside Base.metadata.
#
# This is required for:
#
#     alembic revision --autogenerate
#
# to detect the application's tables.
from app import models  # noqa: F401


# Alembic configuration object.
config = context.config


# ============================================================
# LOGGING
# ============================================================

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


# ============================================================
# SQLALCHEMY METADATA
# ============================================================
#
# Alembic compares this metadata with the actual database.
# ============================================================

target_metadata = Base.metadata


def get_database_url() -> str:
    """
    Return the database URL configured for this environment.
    """

    return settings.database_url


def run_migrations_offline() -> None:
    """
    Generate SQL without connecting to the database.

    Example:

        alembic upgrade head --sql
    """

    url = get_database_url()

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={
            "paramstyle": "named",
        },
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Execute migrations against a live database.
    """

    configuration = config.get_section(
        config.config_ini_section,
        {},
    )

    # The URL from the environment takes precedence over the
    # empty value in alembic.ini.
    configuration["sqlalchemy.url"] = get_database_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:

        context.configure(
            connection=connection,
            target_metadata=target_metadata,

            # Detect SQLAlchemy column type changes.
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


# ============================================================
# RUN MIGRATIONS
# ============================================================

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

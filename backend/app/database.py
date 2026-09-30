from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool, StaticPool

from app.config import settings


class Base(DeclarativeBase):
    """
    Base class for all SQLAlchemy models.

    Example:

        class Profile(Base):
            ...
    """

    pass


def _make_engine(url: str):
    """
    Create the SQLAlchemy database engine.

    SQLite:
        Used for local development and tests.

    PostgreSQL:
        Used in production with Amazon RDS.
    """

    if url.startswith("sqlite"):
        kwargs: dict = {
            "connect_args": {
                "check_same_thread": False,
            }
        }

        # In-memory SQLite exists only inside one connection.
        #
        # StaticPool makes every SQLAlchemy session share
        # the same connection.
        if url in (
            "sqlite://",
            "sqlite:///:memory:",
        ):
            kwargs["poolclass"] = StaticPool

        return create_engine(
            url,
            **kwargs,
        )

    # PostgreSQL / Amazon RDS.
    #
    # pool_pre_ping verifies that a pooled connection is still
    # alive before SQLAlchemy uses it.
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        # Fail fast instead of holding the request for the
        # default 30 s when every connection is checked out.
        pool_timeout=10,
    )


# Create database engine.
engine = _make_engine(settings.database_url)


def _make_probe_engine(url: str):
    """
    Engine used only by the readiness probe.

    It must not share the request pool: when load has every pooled
    connection checked out, the probe would queue behind it, time
    out, and pull a healthy pod out of the Service.

    NullPool opens one short-lived connection per probe, so it adds
    at most one connection per pod on top of the request pool.
    """

    if url.startswith("sqlite"):
        # An in-memory SQLite database exists only in the main
        # engine's connection, so probe that one.
        return engine

    return create_engine(
        url,
        poolclass=NullPool,
        connect_args={"connect_timeout": 2},
    )


probe_engine = _make_probe_engine(settings.database_url)


# Create SQLAlchemy sessions.
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)


def get_db() -> Iterator[Session]:
    """
    FastAPI dependency that creates a database session.

    The session is always closed after the request finishes.
    """

    db = SessionLocal()

    try:
        yield db

    finally:
        db.close()

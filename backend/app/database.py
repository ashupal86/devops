from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

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
    )


# Create database engine.
engine = _make_engine(settings.database_url)


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

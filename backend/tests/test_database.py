from sqlalchemy import text

from app.database import SessionLocal


def test_database_connection():
    """
    Verify that SQLAlchemy can connect to the configured database.

    Local tests normally use SQLite.

    Production uses PostgreSQL/RDS.
    """

    db = SessionLocal()

    try:
        result = db.execute(text("SELECT 1"))

        assert result.scalar() == 1

    finally:
        db.close()

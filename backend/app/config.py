import os
from dataclasses import dataclass, field


def _split_csv(value: str) -> list[str]:
    """
    Convert a comma-separated environment variable into
    a clean list.

    Example:

        "http://localhost:5173,http://127.0.0.1:5173"

    becomes:

        [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    """
    return [
        item.strip()
        for item in value.split(",")
        if item.strip()
    ]


@dataclass(frozen=True)
class Settings:

    # ---------------------------------------------------------
    # Database
    #
    # Local development:
    #
    # DATABASE_URL is not required and SQLite is used.
    #
    # Production:
    #
    # DATABASE_URL comes from Kubernetes Secret.
    # ---------------------------------------------------------

    database_url: str = field(
        default_factory=lambda: os.getenv(
            "DATABASE_URL",
            "sqlite:///./social_links.db",
        )
    )

    # ---------------------------------------------------------
    # CORS
    # ---------------------------------------------------------

    cors_origins: list[str] = field(
        default_factory=lambda: _split_csv(
            os.getenv(
                "CORS_ORIGINS",
                "http://localhost:5173,http://127.0.0.1:5173",
            )
        )
    )


settings = Settings()

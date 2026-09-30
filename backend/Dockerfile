# ============================================================
# STAGE 1: BUILD + TEST
# ============================================================

FROM python:3.12-alpine AS builder

WORKDIR /app

# Prevent Python from creating .pyc files.
ENV PYTHONDONTWRITEBYTECODE=1

# Send Python logs directly to Docker stdout/stderr.
ENV PYTHONUNBUFFERED=1

# Ask uv to compile Python bytecode.
ENV UV_COMPILE_BYTECODE=1


# ============================================================
# INSTALL UV
# ============================================================
#
# Pin uv for reproducible builds.
# ============================================================

COPY --from=ghcr.io/astral-sh/uv:0.8.15 /uv /usr/local/bin/uv


# ============================================================
# DEPENDENCIES
# ============================================================

COPY pyproject.toml uv.lock ./

# Install all dependencies, including development/test
# dependencies because pytest runs during the image build.
RUN uv sync --frozen


# ============================================================
# APPLICATION SOURCE
# ============================================================

COPY app/ ./app

COPY tests/ ./tests


# ============================================================
# ALEMBIC MIGRATIONS
# ============================================================

COPY alembic/ ./alembic

COPY alembic.ini ./alembic.ini


# ============================================================
# RUN TESTS
# ============================================================
#
# If tests fail, Docker build fails.
# This prevents a broken image from reaching ECR.
# ============================================================

RUN uv run pytest


# ============================================================
# REMOVE DEVELOPMENT DEPENDENCIES
# ============================================================

RUN uv sync --frozen --no-dev


# ============================================================
# STAGE 2: PRODUCTION RUNTIME
# ============================================================

FROM python:3.12-alpine AS runner

WORKDIR /app


# Runtime configuration.

ENV PYTHONDONTWRITEBYTECODE=1

ENV PYTHONUNBUFFERED=1

ENV PATH="/app/.venv/bin:$PATH"


# ============================================================
# PRODUCTION PYTHON ENVIRONMENT
# ============================================================

COPY --from=builder /app/.venv /app/.venv


# ============================================================
# APPLICATION
# ============================================================

COPY --from=builder /app/app /app/app


# ============================================================
# ALEMBIC
# ============================================================
#
# The production image contains migrations because Kubernetes
# will eventually execute:
#
#     alembic upgrade head
#
# against RDS.
# ============================================================

COPY --from=builder /app/alembic /app/alembic

COPY --from=builder /app/alembic.ini /app/alembic.ini


# ============================================================
# FASTAPI PORT
# ============================================================

EXPOSE 8000


# ============================================================
# START APPLICATION
# ============================================================

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]

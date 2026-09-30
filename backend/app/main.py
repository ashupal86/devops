from contextlib import asynccontextmanager

import anyio
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app import models  # noqa: F401  (registers tables on Base.metadata)
from app.config import settings
from app.database import Base, engine, probe_engine
from app.observability import MetricsMiddleware
from app.observability import router as metrics_router
from app.routers import profiles


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="Social Links API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "X-Edit-Token"],
)

app.add_middleware(MetricsMiddleware)

app.include_router(profiles.router)
app.include_router(metrics_router)


@app.get("/api/health", tags=["ops"])
async def health() -> dict:
    """Liveness: the process is up.

    async so it runs on the event loop instead of queueing behind
    request handlers in the threadpool; under load a sync version
    timed out and the kubelet restarted healthy pods.
    """
    return {"status": "ok"}


# Readiness gets its own thread, so it never queues behind request
# handlers in the shared threadpool.
_probe_limiter = anyio.CapacityLimiter(1)


def _check_db() -> None:
    with probe_engine.connect() as conn:
        conn.execute(text("SELECT 1"))


@app.get("/api/ready", tags=["ops"])
async def ready() -> dict:
    """Readiness: the database is reachable.

    Uses probe_engine, not the request pool: under load every pooled
    connection is checked out, and a probe waiting on the pool timed
    out and marked healthy pods NotReady.
    """
    try:
        await anyio.to_thread.run_sync(_check_db, limiter=_probe_limiter)
    except Exception:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "database unavailable")
    return {"status": "ready"}

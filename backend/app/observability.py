"""In-process request metrics plus database stats for the ops console.

The routes live under /metrics, outside /api, so nginx never proxies them
and they are not reachable through the public load balancer. The console
reads them through the Kubernetes API server's pod/service proxy.
"""

import threading
import time
from collections import Counter, deque

from fastapi import APIRouter
from sqlalchemy import text

from app.database import engine

# Latency samples kept per process for the rolling percentiles.
WINDOW_SECONDS = 60
MAX_SAMPLES = 20_000


class RequestMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.started = time.time()
        self.in_flight = 0
        self.counts: Counter[tuple[str, str, int]] = Counter()
        self.recent: deque[tuple[float, str, int, float]] = deque(maxlen=MAX_SAMPLES)

    def begin(self) -> None:
        with self._lock:
            self.in_flight += 1

    def end(self, method: str, route: str, status: int, seconds: float) -> None:
        with self._lock:
            self.in_flight -= 1
            self.counts[(method, route, status)] += 1
            self.recent.append((time.time(), route, status, seconds))

    def snapshot(self) -> dict:
        now = time.time()
        with self._lock:
            counts = list(self.counts.items())
            recent = [r for r in self.recent if now - r[0] <= WINDOW_SECONDS]
            in_flight = self.in_flight

        durations = sorted(r[3] for r in recent)

        def pct(p: float) -> float | None:
            if not durations:
                return None
            return durations[min(len(durations) - 1, int(p / 100 * len(durations)))]

        return {
            "uptime_seconds": round(now - self.started, 1),
            "in_flight": in_flight,
            "requests_total": sum(n for _, n in counts),
            "errors_5xx_total": sum(n for (_, _, s), n in counts if s >= 500),
            "by_route": [
                {"method": m, "route": r, "status": s, "count": n}
                for (m, r, s), n in sorted(counts)
            ],
            "window_seconds": WINDOW_SECONDS,
            "window": {
                "requests": len(recent),
                "errors_5xx": sum(1 for r in recent if r[2] >= 500),
                "p50": pct(50),
                "p95": pct(95),
                "p99": pct(99),
                "max": durations[-1] if durations else None,
            },
        }


metrics = RequestMetrics()


class MetricsMiddleware:
    """Pure ASGI middleware, so it adds no per-request task overhead."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or scope["path"].startswith("/metrics"):
            await self.app(scope, receive, send)
            return

        status = 500

        async def send_wrapper(message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        metrics.begin()
        start = time.perf_counter()
        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            # FastAPI records the matched route on the scope; using its
            # template keeps /api/profiles/{tag} as one series.
            route = getattr(scope.get("route"), "path", "unmatched")
            metrics.end(scope["method"], route, status, time.perf_counter() - start)


def pool_stats() -> dict:
    pool = engine.pool
    stats = {"class": type(pool).__name__}
    for name in ("size", "checkedin", "checkedout", "overflow"):
        fn = getattr(pool, name, None)
        if callable(fn):
            stats[name] = fn()
    return stats


router = APIRouter(prefix="/metrics", tags=["ops"], include_in_schema=False)


@router.get("")
def process_metrics() -> dict:
    """Request counters and latency for this pod, plus its connection pool."""
    return {**metrics.snapshot(), "db_pool": pool_stats()}


@router.get("/db")
def database_metrics() -> dict:
    """Server-side PostgreSQL statistics for the application database."""
    if engine.dialect.name != "postgresql":
        return {"engine": engine.dialect.name}

    with engine.connect() as conn:
        db = conn.execute(text("""
            SELECT numbackends, xact_commit, xact_rollback, blks_read, blks_hit,
                   tup_returned, tup_fetched, tup_inserted, tup_updated,
                   tup_deleted, deadlocks, temp_bytes,
                   pg_database_size(datname) AS size_bytes
            FROM pg_stat_database WHERE datname = current_database()
        """)).mappings().one()
        activity = conn.execute(text("""
            SELECT coalesce(state, 'unknown') AS state, count(*) AS n,
                   count(*) FILTER (WHERE wait_event_type = 'Lock') AS lock_waits,
                   max(extract(epoch FROM now() - query_start))
                       FILTER (WHERE state = 'active') AS longest_active_s
            FROM pg_stat_activity
            WHERE datname = current_database() AND pid <> pg_backend_pid()
            GROUP BY 1
        """)).mappings().all()
        tables = conn.execute(text("""
            SELECT relname, n_live_tup, n_dead_tup, seq_scan, idx_scan,
                   n_tup_ins, n_tup_upd, n_tup_del
            FROM pg_stat_user_tables ORDER BY relname
        """)).mappings().all()
        max_conn = conn.execute(text("SHOW max_connections")).scalar_one()

    return {
        "engine": "postgresql",
        "database": dict(db),
        "connections": {
            "max": int(max_conn),
            "by_state": {a["state"]: a["n"] for a in activity},
            "lock_waits": sum(a["lock_waits"] for a in activity),
            "longest_active_s": max(
                (float(a["longest_active_s"]) for a in activity
                 if a["longest_active_s"] is not None), default=0.0),
        },
        "tables": [dict(t) for t in tables],
    }

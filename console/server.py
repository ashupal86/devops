#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["fastapi>=0.115", "uvicorn>=0.30", "boto3>=1.34"]
# ///
"""Local ops console for social-links: http://127.0.0.1:8088/status

- Starts and stops infra/scripts/eks-load-test.py and streams its log.
- Lists the reports it wrote to loadtest-reports/.
- Samples the backend (pods, HPA, kubectl top, per-pod /metrics) and the
  database (/metrics/db through the backend, plus RDS CloudWatch metrics).

Uses your kubectl context and AWS credentials. It binds to 127.0.0.1 only:
it can start load tests and serves report files, so do not expose it.

Usage:
    ./console/server.py [--port 8088] [--namespace social-links]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import boto3  # noqa: F401
    import fastapi  # noqa: F401
    import uvicorn  # noqa: F401
except ImportError:
    # Started with plain `python3 server.py`: re-run under uv so the inline
    # dependencies above (fastapi, uvicorn, boto3) are installed.
    if shutil.which("uv") and not os.getenv("OPS_CONSOLE_REEXEC"):
        os.environ["OPS_CONSOLE_REEXEC"] = "1"
        os.execvp("uv", ["uv", "run", "--script", __file__, *sys.argv[1:]])
    sys.exit("Missing dependencies. Run ./console/server.py (needs uv), or "
             "pip install fastapi uvicorn boto3.")

import uvicorn
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "infra" / "scripts" / "eks-load-test.py"
REPORTS = ROOT / "loadtest-reports"
TERRAFORM = ROOT / "infra" / "terraform"
STATIC = Path(__file__).resolve().parent / "static"

REPORT_ID = re.compile(r"^\d{8}-\d{6}$")
REPORT_FILES = re.compile(r"^(eks-load-test-report\.pdf|scaling\.png|hey-\d+\.txt|console-run\.log)$")

BACKEND_EVERY = 5      # seconds between backend samples
DB_EVERY = 15          # seconds between /metrics/db samples
HISTORY = 3600         # seconds of history kept in memory


# ----------------------------------------------------------------- helpers

def now_utc() -> datetime:
    return datetime.now(timezone.utc)


KUBECTL_ERROR = {"last": ""}


def kubectl(*args: str, timeout: float = 20) -> str | None:
    try:
        return subprocess.run(["kubectl", *args], capture_output=True, text=True,
                              timeout=timeout, check=True).stdout
    except subprocess.CalledProcessError as exc:
        lines = (exc.stderr or "").strip().splitlines()
        KUBECTL_ERROR["last"] = lines[-1] if lines else f"exit code {exc.returncode}"
        return None
    except subprocess.TimeoutExpired:
        KUBECTL_ERROR["last"] = f"kubectl {' '.join(args[:3])} timed out after {timeout}s"
        return None
    except FileNotFoundError:
        KUBECTL_ERROR["last"] = "kubectl is not installed"
        return None


def kubectl_json(*args: str) -> dict | None:
    out = kubectl(*args, "-o", "json")
    try:
        return json.loads(out) if out else None
    except json.JSONDecodeError:
        return None


def kube_raw(path: str, timeout: float = 8) -> dict | None:
    """GET through the API server, e.g. the pod proxy for /metrics."""
    out = kubectl("get", "--raw", path, timeout=timeout)
    try:
        return json.loads(out) if out else None
    except json.JSONDecodeError:
        return None


def kubeconfig_aws_profile() -> str | None:
    """The AWS profile the current kubectl context uses for `aws eks get-token`."""
    out = kubectl("config", "view", "--minify", "-o", "json", timeout=5)
    try:
        users = json.loads(out)["users"] if out else []
        for env in (users[0]["user"].get("exec") or {}).get("env") or []:
            if env.get("name") == "AWS_PROFILE":
                return env.get("value")
        args = (users[0]["user"].get("exec") or {}).get("args") or []
        if "--profile" in args:
            return args[args.index("--profile") + 1]
    except (json.JSONDecodeError, KeyError, IndexError):
        pass
    return None


def terraform_outputs() -> dict:
    if not shutil.which("terraform") or not (TERRAFORM / "terraform.tfstate").exists():
        return {}
    try:
        out = subprocess.run(["terraform", f"-chdir={TERRAFORM}", "output", "-json"],
                             capture_output=True, text=True, timeout=30, check=True).stdout
        return {k: v.get("value") for k, v in json.loads(out).items()}
    except (subprocess.SubprocessError, json.JSONDecodeError):
        return {}


# ----------------------------------------------------------------- config

class Config:
    def __init__(self, namespace: str, profile: str | None = None) -> None:
        tf = terraform_outputs()
        self.namespace = namespace
        self.region = (os.getenv("AWS_REGION") or tf.get("aws_region") or "ap-south-1")
        endpoint = tf.get("rds_endpoint") or ""
        # The RDS hostname starts with the instance identifier.
        self.rds_id = os.getenv("RDS_INSTANCE_ID") or endpoint.split(".")[0] or "social-links-prod"
        self.cluster = tf.get("eks_cluster_name") or ""
        # Use the same credentials kubectl uses unless told otherwise.
        self.aws_profile = profile or os.getenv("AWS_PROFILE") or kubeconfig_aws_profile()


# ----------------------------------------------------------------- samplers

class BackendSampler:
    """Polls pods, HPA, kubectl top and each pod's /metrics every few seconds.

    Request rates come from per-pod counter deltas, so a restarted pod (whose
    counters reset) only loses one interval instead of producing a spike.
    """

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.history: deque[dict] = deque(maxlen=HISTORY // BACKEND_EVERY)
        self.latest: dict = {}
        self._prev: dict[str, tuple[float, int, int]] = {}
        self._pool = ThreadPoolExecutor(max_workers=8)

    def run(self) -> None:
        while True:
            started = time.monotonic()
            try:
                self.sample()
            except Exception as exc:  # keep sampling whatever happens
                self.latest = {"t": now_utc().isoformat(), "error": str(exc)}
            time.sleep(max(0.0, BACKEND_EVERY - (time.monotonic() - started)))

    def _pod_metrics(self, pod: str) -> dict | None:
        return kube_raw(f"/api/v1/namespaces/{self.cfg.namespace}/pods/{pod}:8000/proxy/metrics")

    def sample(self) -> None:
        ns = self.cfg.namespace
        ts = now_utc()
        pods_json = kubectl_json("-n", ns, "get", "pods", "-l", "app=backend")
        if pods_json is None:
            self.latest = {"t": ts.isoformat(),
                           "error": f"kubectl could not reach the cluster: {KUBECTL_ERROR['last']}"}
            return
        hpa = kubectl_json("-n", ns, "get", "hpa", "backend") or {}
        top = {}
        for line in (kubectl("-n", ns, "top", "pods", "-l", "app=backend",
                             "--no-headers") or "").splitlines():
            parts = line.split()
            if len(parts) >= 3:
                try:
                    top[parts[0]] = (int(parts[1].rstrip("m")), int(parts[2].rstrip("Mi")))
                except ValueError:
                    pass

        pods = []
        for item in pods_json.get("items", []):
            meta, st = item["metadata"], item.get("status", {})
            ready = any(c["type"] == "Ready" and c["status"] == "True"
                        for c in st.get("conditions", []))
            pods.append({
                "name": meta["name"],
                "node": (item["spec"].get("nodeName") or "").split(".")[0],
                "ip": st.get("podIP", ""),
                "phase": "Terminating" if meta.get("deletionTimestamp") else st.get("phase", ""),
                "ready": ready,
                "restarts": sum(c.get("restartCount", 0) for c in st.get("containerStatuses", [])),
                "created": meta.get("creationTimestamp", ""),
                "cpu_m": top.get(meta["name"], (None, None))[0],
                "mem_mi": top.get(meta["name"], (None, None))[1],
            })

        running = [p for p in pods if p["phase"] == "Running" and p["ip"]]
        metrics = dict(zip([p["name"] for p in running],
                           self._pool.map(lambda p: self._pod_metrics(p["name"]), running)))

        now = time.time()
        rps = err_rps = 0.0
        p50 = p95 = p99 = None
        in_flight = pool_out = pool_size = 0
        for p in pods:
            m = metrics.get(p["name"])
            p["metrics"] = m
            if not m:
                continue
            total, errors = m["requests_total"], m["errors_5xx_total"]
            prev = self._prev.get(p["name"])
            if prev and total >= prev[1]:
                dt = now - prev[0]
                p["rps"] = (total - prev[1]) / dt
                p["err_rps"] = (errors - prev[2]) / dt
                rps += p["rps"]
                err_rps += p["err_rps"]
            self._prev[p["name"]] = (now, total, errors)
            w = m["window"]
            # Worst pod wins: a single slow pod is what users notice.
            p50 = max(filter(None, [p50, w["p50"]]), default=None)
            p95 = max(filter(None, [p95, w["p95"]]), default=None)
            p99 = max(filter(None, [p99, w["p99"]]), default=None)
            in_flight += m["in_flight"]
            pool = m.get("db_pool", {})
            pool_out += pool.get("checkedout", 0) + max(pool.get("overflow", 0), 0)
            pool_size += pool.get("size", 0)
        self._prev = {k: v for k, v in self._prev.items() if k in metrics}

        hs, hspec = hpa.get("status", {}), hpa.get("spec", {})
        cpu_pct = None
        for m in hs.get("currentMetrics") or []:
            if m.get("type") == "Resource" and m["resource"]["name"] == "cpu":
                cpu_pct = m["resource"]["current"].get("averageUtilization")

        point = {
            "t": ts.isoformat(),
            "pods": len(pods), "ready": sum(p["ready"] for p in pods),
            "hpa_desired": hs.get("desiredReplicas"),
            "hpa_min": hspec.get("minReplicas"), "hpa_max": hspec.get("maxReplicas"),
            "cpu_pct": cpu_pct,
            "cpu_m": sum(p["cpu_m"] or 0 for p in pods),
            "mem_mi": sum(p["mem_mi"] or 0 for p in pods),
            "rps": round(rps, 2), "err_rps": round(err_rps, 2),
            "p50_ms": p50 and p50 * 1000, "p95_ms": p95 and p95 * 1000,
            "p99_ms": p99 and p99 * 1000,
            "in_flight": in_flight, "pool_in_use": pool_out, "pool_size": pool_size,
        }
        self.history.append(point)
        self.latest = {**point, "pod_list": pods}


class DatabaseSampler:
    """Polls the backend's /metrics/db through the service proxy."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.history: deque[dict] = deque(maxlen=HISTORY // DB_EVERY)
        self.latest: dict = {}
        self._prev: tuple[float, dict] | None = None

    def run(self) -> None:
        while True:
            try:
                self.sample()
            except Exception as exc:
                self.latest = {"t": now_utc().isoformat(), "error": str(exc)}
            time.sleep(DB_EVERY)

    def sample(self) -> None:
        ts = now_utc()
        data = kube_raw(f"/api/v1/namespaces/{self.cfg.namespace}/services/"
                        "backend:8000/proxy/metrics/db")
        if not data:
            self.latest = {"t": ts.isoformat(),
                           "error": "backend /metrics/db unreachable (is the new backend deployed?)"}
            return
        if data.get("engine") != "postgresql":
            self.latest = {"t": ts.isoformat(), "error": f"backend uses {data.get('engine')}"}
            return

        db, conns = data["database"], data["connections"]
        now = time.time()
        point = {"t": ts.isoformat(),
                 "connections": sum(conns["by_state"].values()),
                 "active": conns["by_state"].get("active", 0),
                 "idle": conns["by_state"].get("idle", 0),
                 "lock_waits": conns["lock_waits"],
                 "longest_active_s": conns["longest_active_s"]}
        if self._prev:
            dt, prev = now - self._prev[0], self._prev[1]
            if db["xact_commit"] >= prev["xact_commit"]:
                point["tps"] = round((db["xact_commit"] + db["xact_rollback"]
                                      - prev["xact_commit"] - prev["xact_rollback"]) / dt, 2)
                reads = db["blks_read"] - prev["blks_read"]
                hits = db["blks_hit"] - prev["blks_hit"]
                point["cache_hit_pct"] = round(100 * hits / (hits + reads), 2) if hits + reads else None
                point["rows_read_s"] = round((db["tup_fetched"] - prev["tup_fetched"]) / dt, 1)
                point["rows_written_s"] = round(
                    sum(db[k] - prev[k] for k in ("tup_inserted", "tup_updated", "tup_deleted")) / dt, 1)
        self._prev = (now, db)
        self.history.append(point)
        self.latest = {**point, "raw": data}


class RdsCloudWatch:
    METRICS = [
        ("CPUUtilization", "Average"), ("DatabaseConnections", "Average"),
        ("FreeableMemory", "Average"), ("ReadIOPS", "Average"), ("WriteIOPS", "Average"),
        ("ReadLatency", "Average"), ("WriteLatency", "Average"),
        ("NetworkReceiveThroughput", "Average"), ("NetworkTransmitThroughput", "Average"),
        ("FreeStorageSpace", "Average"), ("DiskQueueDepth", "Average"),
    ]

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._cache: dict[int, tuple[float, dict]] = {}
        self._lock = threading.Lock()

    def _session(self):
        import boto3
        return boto3.session.Session(region_name=self.cfg.region,
                                     profile_name=self.cfg.aws_profile)

    def fetch(self, minutes: int) -> dict:
        with self._lock:
            hit = self._cache.get(minutes)
            if hit and time.time() - hit[0] < 30:
                return hit[1]
        try:
            result = self._fetch(minutes)
        except Exception as exc:
            name = type(exc).__name__
            hint = f" Run `aws sso login --profile {self.cfg.aws_profile}` and reload." \
                if self.cfg.aws_profile and ("Credential" in name or "Token" in name or "SSO" in name
                                             or "Expired" in str(exc)) else ""
            result = {"error": f"{name}: {exc}.{hint}"}
        with self._lock:
            self._cache[minutes] = (time.time(), result)
        return result

    def _fetch(self, minutes: int) -> dict:
        session = self._session()
        cw, rds = session.client("cloudwatch"), session.client("rds")
        end = now_utc()
        start = end - timedelta(minutes=minutes)
        period = 60 if minutes <= 180 else 300
        queries = [{
            "Id": f"m{i}",
            "Label": name,
            "MetricStat": {
                "Metric": {"Namespace": "AWS/RDS", "MetricName": name,
                           "Dimensions": [{"Name": "DBInstanceIdentifier",
                                           "Value": self.cfg.rds_id}]},
                "Period": period, "Stat": stat,
            },
        } for i, (name, stat) in enumerate(self.METRICS)]
        series: dict[str, list] = {}
        token = None
        while True:
            kwargs = {"MetricDataQueries": queries, "StartTime": start, "EndTime": end,
                      "ScanBy": "TimestampAscending"}
            if token:
                kwargs["NextToken"] = token
            resp = cw.get_metric_data(**kwargs)
            for r in resp["MetricDataResults"]:
                series.setdefault(r["Label"], []).extend(
                    [t.isoformat(), v] for t, v in zip(r["Timestamps"], r["Values"]))
            token = resp.get("NextToken")
            if not token:
                break

        inst = rds.describe_db_instances(DBInstanceIdentifier=self.cfg.rds_id)["DBInstances"][0]
        alarms = cw.describe_alarms(AlarmNamePrefix=self.cfg.rds_id).get("MetricAlarms", [])
        return {
            "period": period,
            "series": {k: sorted(v) for k, v in series.items()},
            "instance": {
                "id": inst["DBInstanceIdentifier"], "status": inst["DBInstanceStatus"],
                "class": inst["DBInstanceClass"],
                "engine": f"{inst['Engine']} {inst['EngineVersion']}",
                "storage_gb": inst["AllocatedStorage"], "storage_type": inst.get("StorageType"),
                "multi_az": inst["MultiAZ"], "az": inst.get("AvailabilityZone"),
                "endpoint": inst.get("Endpoint", {}).get("Address"),
            },
            "alarms": [{"name": a["AlarmName"], "state": a["StateValue"],
                        "reason": a.get("StateReason", ""),
                        "metric": a.get("MetricName")} for a in alarms],
        }


# ----------------------------------------------------------------- load test runs

class RunParams(BaseModel):
    url: str | None = Field(default=None, max_length=300, pattern=r"^https?://[^\s]+$")
    accounts: int = Field(default=50, ge=1, le=1000)
    requests: int = Field(default=100_000, ge=100, le=5_000_000)
    concurrency: int = Field(default=500, ge=1, le=5000)
    duration: str | None = Field(default=None, pattern=r"^\d{1,4}[smh]$")
    targets: int = Field(default=5, ge=1, le=50)
    baseline: int = Field(default=15, ge=0, le=600)
    cooldown: int = Field(default=60, ge=0, le=1800)
    cleanup: bool = True


RUN_STATE = REPORTS / ".console" / "run.json"


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes()
    except (ProcessLookupError, PermissionError, OSError):
        return False
    return b"eks-load-test" in cmdline


def find_external_runs() -> list[int]:
    """PIDs of load tests this console did not start (e.g. from a terminal)."""
    pids = []
    for proc in Path("/proc").glob("[0-9]*"):
        try:
            cmd = (proc / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        # The python process running the script, not uv or a shell wrapper.
        if len(cmd) > 1 and b"python" in Path(cmd[0].decode(errors="ignore")).name.encode() \
                and any(c.endswith(b"eks-load-test.py") for c in cmd[1:2]):
            pids.append(int(proc.name))
    return pids


class Run:
    """A load test started by this console.

    Output goes to a log file, not a pipe, and the pid is saved in
    loadtest-reports/.console/run.json. Restarting the console therefore
    neither kills the run nor breaks its logging, and the new console
    re-attaches to it.
    """

    def __init__(self, state: dict) -> None:
        self.state = state
        self.lines: list[str] = []
        self.proc: subprocess.Popen | None = None
        self._pos = 0

    # -- construction

    @classmethod
    def start(cls, params: RunParams, namespace: str) -> "Run":
        argv = ["uv", "run", "--script", str(SCRIPT), "--namespace", namespace,
                "--out", str(REPORTS),
                "--accounts", str(params.accounts), "-c", str(params.concurrency),
                "--targets", str(params.targets), "--baseline", str(params.baseline),
                "--cooldown", str(params.cooldown)]
        argv += ["-z", params.duration] if params.duration else ["-n", str(params.requests)]
        if params.url:
            argv += ["--url", params.url]
        if params.cleanup:
            argv.append("--cleanup")

        RUN_STATE.parent.mkdir(parents=True, exist_ok=True)
        started = now_utc()
        log = RUN_STATE.parent / f"run-{started:%Y%m%d-%H%M%S}.log"
        log.write_text("$ " + " ".join(argv) + "\n")
        with log.open("a") as out:
            # New session so stop() can signal hey and the other children too.
            proc = subprocess.Popen(argv, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=out,
                                    stderr=subprocess.STDOUT, start_new_session=True,
                                    env={**os.environ, "PYTHONUNBUFFERED": "1"})
        run = cls({
            "pid": proc.pid, "argv": argv, "params": params.model_dump(),
            "started": started.isoformat(), "ended": None, "exit_code": None,
            "stopped": False, "report_id": None, "log": str(log),
            "before": sorted(p.name for p in REPORTS.iterdir()),
        })
        run.proc = proc
        run.save()
        threading.Thread(target=run._watch, daemon=True).start()
        return run

    @classmethod
    def load(cls) -> "Run | None":
        try:
            run = cls(json.loads(RUN_STATE.read_text()))
        except (OSError, json.JSONDecodeError):
            return None
        run._tail()
        if run.state["ended"] is None:
            if pid_alive(run.state["pid"]):
                threading.Thread(target=run._watch, daemon=True).start()
            else:
                run._finish(None)
        return run

    def save(self) -> None:
        RUN_STATE.write_text(json.dumps(self.state, indent=2))

    # -- lifecycle

    @property
    def running(self) -> bool:
        return self.state["ended"] is None

    def _tail(self) -> None:
        try:
            with open(self.state["log"]) as f:
                f.seek(self._pos)
                chunk = f.read()
                # Keep a partial last line for the next read.
                cut = chunk.rfind("\n") + 1
                self._pos += len(chunk[:cut].encode())
        except OSError:
            return
        self.lines.extend(chunk[:cut].splitlines())

    def _watch(self) -> None:
        while True:
            self._tail()
            if self.proc is not None:
                code = self.proc.poll()
                if code is not None:
                    return self._finish(code)
            elif not pid_alive(self.state["pid"]):
                # Re-attached after a console restart: the exit code is gone.
                return self._finish(None)
            time.sleep(0.5)

    def _finish(self, code: int | None) -> None:
        self._tail()
        before = set(self.state["before"])
        new = sorted(p.name for p in REPORTS.iterdir()
                     if p.name not in before and REPORT_ID.match(p.name))
        if new:
            rid = new[-1]
            self.state["report_id"] = rid
            shutil.copyfile(self.state["log"], REPORTS / rid / "console-run.log")
            if code is None:
                code = 0 if (REPORTS / rid / "eks-load-test-report.pdf").exists() else 1
        self.state.update(ended=now_utc().isoformat(), exit_code=code)
        self.save()

    def stop(self) -> None:
        if self.running:
            self.state["stopped"] = True
            self.save()
            try:
                os.killpg(os.getpgid(self.state["pid"]), signal.SIGTERM)
            except ProcessLookupError:
                pass

    def summary(self) -> dict:
        s = self.state
        return {"running": self.running, "started": s["started"], "ended": s["ended"],
                "exit_code": s["exit_code"], "stopped": s["stopped"],
                "report_id": s["report_id"], "params": s["params"],
                "command": " ".join(s["argv"]), "lines": len(self.lines)}


# ----------------------------------------------------------------- reports

def report_summary(rid: str) -> dict:
    d = REPORTS / rid
    started = datetime.strptime(rid, "%Y%m%d-%H%M%S").astimezone()
    out = {"id": rid, "started": started.isoformat(),
           "pdf": (d / "eks-load-test-report.pdf").exists(),
           "chart": (d / "scaling.png").exists(),
           "log": (d / "console-run.log").exists(),
           "hey_files": sorted(p.name for p in d.glob("hey-*.txt")),
           "complete": (d / "samples.json").exists()}
    try:
        accounts = json.loads((d / "accounts.json").read_text())
        out["accounts"] = {"total": len(accounts),
                           "created": sum(1 for a in accounts if a.get("status") == 201)}
    except (OSError, json.JSONDecodeError):
        pass
    try:
        s = json.loads((d / "samples.json").read_text())
        samples = s.get("samples", [])
        out["hey_total"] = s.get("hey_total")
        out["pods_start"] = samples[0]["pods"] if samples else None
        out["pods_peak"] = max((x["pods"] for x in samples), default=None)
        out["cpu_peak"] = max((x["cpu_pct"] or 0 for x in samples), default=None)
        out["new_pods"] = sum(1 for p in s.get("pods", []) if not p.get("existed_before"))
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        pass
    return out


def check_report_id(rid: str) -> Path:
    if not REPORT_ID.match(rid) or not (REPORTS / rid).is_dir():
        raise HTTPException(404, "report not found")
    return REPORTS / rid


# ----------------------------------------------------------------- app

def build_app(cfg: Config) -> FastAPI:
    backend, database, rds = BackendSampler(cfg), DatabaseSampler(cfg), RdsCloudWatch(cfg)
    threading.Thread(target=backend.run, daemon=True).start()
    threading.Thread(target=database.run, daemon=True).start()
    state: dict = {"run": Run.load() if REPORTS.exists() else None}
    run_lock = threading.Lock()
    tools_cache: dict = {}

    app = FastAPI(title="social-links ops console", docs_url=None, redoc_url=None)
    api = APIRouter(prefix="/status/api")

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/status")

    @app.get("/status", include_in_schema=False)
    def page():
        return FileResponse(STATIC / "index.html")

    @api.get("/env")
    def env():
        if not tools_cache or time.time() - tools_cache["at"] > 60:
            aws = None
            try:
                ident = rds._session().client("sts").get_caller_identity()
                aws = {"ok": True, "account": ident["Account"], "arn": ident["Arn"]}
            except Exception as exc:
                aws = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            tools_cache.update(at=time.time(), aws=aws, tools={
                t: bool(shutil.which(t)) for t in ("uv", "hey", "kubectl", "aws")})
        return {"namespace": cfg.namespace, "region": cfg.region, "rds_id": cfg.rds_id,
                "aws_profile": cfg.aws_profile,
                "cluster": cfg.cluster,
                "context": (kubectl("config", "current-context", timeout=5) or "").strip(),
                "tools": tools_cache["tools"], "aws": tools_cache["aws"]}

    @api.get("/backend")
    def backend_now():
        return {"latest": backend.latest, "history": list(backend.history)}

    @api.get("/database")
    def database_now():
        return {"latest": database.latest, "history": list(database.history)}

    @api.get("/rds")
    def rds_metrics(minutes: int = 60):
        return rds.fetch(max(15, min(minutes, 24 * 60)))

    @api.get("/runs/current")
    def current_run():
        run: Run | None = state["run"]
        out = run.summary() if run else None
        external = [p for p in find_external_runs()
                    if not (run and run.running and p in _children(run.state["pid"]))]
        if out is not None or external:
            out = {**(out or {"running": False}), "external_pids": external}
        return out

    def _children(pid: int) -> set[int]:
        """pid and all its descendants."""
        found, frontier = {pid}, [pid]
        while frontier:
            p = frontier.pop()
            try:
                kids = Path(f"/proc/{p}/task/{p}/children").read_text().split()
            except OSError:
                continue
            for k in map(int, kids):
                if k not in found:
                    found.add(k)
                    frontier.append(k)
        return found

    @api.post("/runs", status_code=201)
    def start_run(params: RunParams):
        with run_lock:
            run: Run | None = state["run"]
            if run and run.running:
                raise HTTPException(409, "a load test is already running")
            if find_external_runs():
                raise HTTPException(409, "another eks-load-test.py is running on this "
                                         "machine (started outside the console); stop it first")
            missing = [t for t in ("uv", "hey", "kubectl") if not shutil.which(t)]
            if missing:
                raise HTTPException(400, f"missing tools: {', '.join(missing)}")
            REPORTS.mkdir(parents=True, exist_ok=True)
            state["run"] = Run.start(params, cfg.namespace)
            return state["run"].summary()

    @api.post("/runs/current/stop")
    def stop_run():
        run: Run | None = state["run"]
        if run and run.running:
            run.stop()
            return run.summary()
        external = find_external_runs()
        if not external:
            raise HTTPException(409, "no load test is running")
        for pid in external:
            try:
                if os.getpgid(pid) != os.getpgid(0):
                    os.killpg(os.getpgid(pid), signal.SIGTERM)
            except ProcessLookupError:
                pass
        return {"running": False, "stopped_external": external}

    @api.get("/runs/current/log")
    def stream_log(offset: int = 0):
        run: Run | None = state["run"]
        if not run:
            raise HTTPException(404, "no load test has been started")

        def events():
            i = max(0, offset)
            idle = 0
            while True:
                while i < len(run.lines):
                    yield f"data: {json.dumps({'i': i, 'line': run.lines[i]})}\n\n"
                    i += 1
                if not run.running and i >= len(run.lines):
                    yield f"event: done\ndata: {json.dumps(run.summary())}\n\n"
                    return
                time.sleep(0.5)
                idle += 1
                if idle % 30 == 0:
                    yield ": keepalive\n\n"

        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache"})

    @api.get("/reports")
    def reports():
        if not REPORTS.exists():
            return []
        ids = sorted((p.name for p in REPORTS.iterdir()
                      if p.is_dir() and REPORT_ID.match(p.name) and any(p.iterdir())),
                     reverse=True)
        return [report_summary(rid) for rid in ids]

    @api.get("/reports/{rid}")
    def report(rid: str):
        d = check_report_id(rid)
        out = report_summary(rid)
        try:
            # samples.json holds no edit tokens; accounts.json does and is never served.
            out["data"] = json.loads((d / "samples.json").read_text())
        except (OSError, json.JSONDecodeError):
            out["data"] = None
        return out

    @api.get("/reports/{rid}/files/{name}")
    def report_file(rid: str, name: str):
        d = check_report_id(rid)
        if not REPORT_FILES.match(name) or not (d / name).is_file():
            raise HTTPException(404, "file not found")
        return FileResponse(d / name)

    app.include_router(api)
    return app


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", type=int, default=8088)
    p.add_argument("--namespace", default="social-links")
    p.add_argument("--profile", help="AWS profile (default: AWS_PROFILE or the one in kubeconfig)")
    args = p.parse_args()
    if not shutil.which("kubectl"):
        sys.exit("kubectl is not installed")
    cfg = Config(args.namespace, args.profile)
    print(f"ops console: http://127.0.0.1:{args.port}/status "
          f"(namespace {cfg.namespace}, RDS {cfg.rds_id} in {cfg.region}, "
          f"AWS profile {cfg.aws_profile or 'default'})", flush=True)
    uvicorn.run(build_app(cfg), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()

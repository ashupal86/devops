#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["reportlab>=4.0", "matplotlib>=3.8"]
# ///
"""EKS autoscaling load test for social-links.

1. Creates random accounts (profiles) through the public API.
2. Runs `hey` against those profiles (default 100000 requests, 500 concurrent).
3. Samples backend pods, the HPA and `kubectl top` the whole time.
4. Writes a PDF report with the accounts, hey results and pod details.

Usage:
    ./infra/scripts/eks-load-test.py                      # URL from the frontend LB
    ./infra/scripts/eks-load-test.py --url http://<nlb>   # explicit target
    ./infra/scripts/eks-load-test.py --accounts 100 --cleanup

Needs: uv, hey, and kubectl pointed at the cluster
(`aws eks update-kubeconfig --region ap-south-1 --name social-links-prod`).
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import shutil
import string
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

FIRST = ["ada", "alan", "grace", "linus", "margaret", "ken", "barbara", "dennis",
         "radia", "guido", "anita", "tim", "hedy", "vint", "frances", "john",
         "katherine", "edsger", "sophie", "bjarne", "joan", "donald", "lynn", "rob"]
LAST = ["lovelace", "turing", "hopper", "torvalds", "hamilton", "thompson",
        "liskov", "ritchie", "perlman", "rossum", "borg", "lee", "lamarr", "cerf",
        "allen", "backus", "johnson", "dijkstra", "wilson", "stroustrup", "clarke"]
MESSAGES = ["Building things on the internet.", "Coffee, code and cloud.",
            "Load testing is a lifestyle.", "Find me on the links below.",
            "Shipping small, shipping often.", "Kubernetes enjoyer.",
            "Writing about distributed systems.", "Open source contributor."]
SITES = [("GitHub", "https://github.com/{u}"), ("X", "https://x.com/{u}"),
         ("LinkedIn", "https://linkedin.com/in/{u}"), ("Blog", "https://{u}.dev"),
         ("YouTube", "https://youtube.com/@{u}"), ("Mastodon", "https://hachyderm.io/@{u}")]


# ----------------------------------------------------------------- helpers

def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    # The API returns naive UTC timestamps when backed by SQLite.
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def kubectl_json(*args: str) -> dict | None:
    try:
        out = subprocess.run(["kubectl", *args, "-o", "json"], capture_output=True,
                             text=True, timeout=20, check=True).stdout
        return json.loads(out)
    except (subprocess.SubprocessError, json.JSONDecodeError):
        return None


def kubectl_text(*args: str) -> str:
    try:
        return subprocess.run(["kubectl", *args], capture_output=True, text=True,
                              timeout=20, check=True).stdout
    except subprocess.SubprocessError:
        return ""


def http(method: str, url: str, body: dict | None = None,
         headers: dict | None = None, timeout: float = 15) -> tuple[int, dict | None]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return 0, None


def discover_url(namespace: str) -> str:
    host = kubectl_text("-n", namespace, "get", "svc", "frontend", "-o",
                        "jsonpath={.status.loadBalancer.ingress[0].hostname}").strip()
    if not host:
        sys.exit("Could not find the frontend load balancer; pass --url.")
    return f"http://{host}"


# ----------------------------------------------------------------- accounts

@dataclass
class Account:
    tag: str
    display_name: str
    message: str
    links: list[dict]
    status: int = 0
    latency_ms: float = 0.0
    created_at: str = ""
    edit_token: str = ""


def random_account() -> Account:
    first, last = random.choice(FIRST), random.choice(LAST)
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    tag = f"lt-{first[:8]}-{suffix}"
    user = f"{first}{last}{random.randint(1, 999)}"
    links = [{"label": label, "url": url.format(u=user)}
             for label, url in random.sample(SITES, random.randint(2, 5))]
    return Account(tag=tag, display_name=f"{first.title()} {last.title()}",
                   message=random.choice(MESSAGES), links=links)


def create_account(base: str, acct: Account) -> Account:
    start = time.perf_counter()
    status, body = http("POST", f"{base}/api/profiles", {
        "tag": acct.tag, "display_name": acct.display_name,
        "message": acct.message, "links": acct.links})
    acct.latency_ms = (time.perf_counter() - start) * 1000
    acct.status = status
    if status == 201 and body:
        acct.edit_token = body["edit_token"]
        acct.created_at = body["profile"]["created_at"]
    return acct


def create_accounts(base: str, count: int) -> list[Account]:
    with ThreadPoolExecutor(max_workers=20) as pool:
        return list(pool.map(lambda a: create_account(base, a),
                             [random_account() for _ in range(count)]))


def delete_accounts(base: str, accounts: list[Account]) -> int:
    def delete(a: Account) -> bool:
        status, _ = http("DELETE", f"{base}/api/profiles/{a.tag}",
                         headers={"X-Edit-Token": a.edit_token})
        return status == 204
    with ThreadPoolExecutor(max_workers=20) as pool:
        return sum(pool.map(delete, [a for a in accounts if a.edit_token]))


# ----------------------------------------------------------------- cluster monitor

@dataclass
class PodInfo:
    name: str
    node: str = ""
    ip: str = ""
    created: str = ""
    ready_at: str = ""
    phase: str = ""
    restarts: int = 0
    first_seen: str = ""
    last_seen: str = ""
    terminated: bool = False
    existed_before: bool = False
    peak_cpu_m: int = 0
    peak_mem_mi: int = 0


@dataclass
class Monitor:
    namespace: str
    selector: str
    hpa: str
    interval: float
    samples: list[dict] = field(default_factory=list)
    pods: dict[str, PodInfo] = field(default_factory=dict)
    _stop: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = None

    def start(self) -> None:
        self.sample(initial=True)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join()
        self.sample()

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            self.sample()

    def sample(self, initial: bool = False) -> None:
        ts = now_utc()
        pods = kubectl_json("-n", self.namespace, "get", "pods", "-l", self.selector) or {}
        hpa = kubectl_json("-n", self.namespace, "get", "hpa", self.hpa) or {}
        usage = self._top()

        seen, ready = set(), 0
        for item in pods.get("items", []):
            meta, spec, st = item["metadata"], item["spec"], item.get("status", {})
            name = meta["name"]
            seen.add(name)
            info = self.pods.setdefault(name, PodInfo(
                name=name, first_seen=ts.isoformat(), existed_before=initial))
            info.node = spec.get("nodeName", "") or info.node
            info.ip = st.get("podIP", "") or info.ip
            info.created = meta.get("creationTimestamp", "")
            info.phase = "Terminating" if meta.get("deletionTimestamp") else st.get("phase", "")
            info.restarts = sum(c.get("restartCount", 0)
                                for c in st.get("containerStatuses", []))
            for cond in st.get("conditions", []):
                if cond["type"] == "Ready" and cond["status"] == "True":
                    info.ready_at = info.ready_at or cond.get("lastTransitionTime", "")
                    if info.phase == "Running":
                        ready += 1
            info.last_seen = ts.isoformat()
            if name in usage:
                info.peak_cpu_m = max(info.peak_cpu_m, usage[name][0])
                info.peak_mem_mi = max(info.peak_mem_mi, usage[name][1])
        for name, info in self.pods.items():
            if name not in seen:
                info.terminated = True
                info.phase = "Deleted"

        hstatus, hspec = hpa.get("status", {}), hpa.get("spec", {})
        cpu = None
        for m in hstatus.get("currentMetrics") or []:
            if m.get("type") == "Resource" and m["resource"]["name"] == "cpu":
                cpu = m["resource"]["current"].get("averageUtilization")
        self.samples.append({
            "t": ts.isoformat(), "pods": len(seen), "ready": ready,
            "hpa_current": hstatus.get("currentReplicas"),
            "hpa_desired": hstatus.get("desiredReplicas"),
            "hpa_min": hspec.get("minReplicas"), "hpa_max": hspec.get("maxReplicas"),
            "cpu_pct": cpu,
            "cpu_m_total": sum(u[0] for n, u in usage.items() if n in seen),
        })

    def _top(self) -> dict[str, tuple[int, int]]:
        out = kubectl_text("-n", self.namespace, "top", "pods", "-l", self.selector,
                           "--no-headers")
        usage = {}
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 3:
                try:
                    usage[parts[0]] = (int(parts[1].rstrip("m")),
                                       int(parts[2].rstrip("Mi")))
                except ValueError:
                    pass
        return usage


def cluster_snapshot(namespace: str, hpa: str) -> dict:
    nodes = []
    for n in (kubectl_json("get", "nodes") or {}).get("items", []):
        labels = n["metadata"].get("labels", {})
        cap = n["status"].get("capacity", {})
        nodes.append({
            "name": n["metadata"]["name"],
            "instance_type": labels.get("node.kubernetes.io/instance-type", ""),
            "zone": labels.get("topology.kubernetes.io/zone", ""),
            "capacity_type": labels.get("eks.amazonaws.com/capacityType", ""),
            "cpu": cap.get("cpu", ""), "memory": cap.get("memory", ""),
        })
    events = []
    for e in (kubectl_json("-n", namespace, "get", "events") or {}).get("items", []):
        obj = e.get("involvedObject", {})
        if obj.get("kind") == "HorizontalPodAutoscaler" and obj.get("name") == hpa \
                or obj.get("kind") == "ReplicaSet" and "backend" in obj.get("name", ""):
            events.append({
                "time": e.get("lastTimestamp") or e.get("eventTime") or "",
                "kind": obj.get("kind"), "reason": e.get("reason", ""),
                "message": e.get("message", ""),
            })
    events.sort(key=lambda e: e["time"])
    return {
        "context": kubectl_text("config", "current-context").strip(),
        "nodes": nodes, "events": events,
    }


# ----------------------------------------------------------------- hey

def run_hey(urls: list[str], total: int, concurrency: int, duration: str | None,
            out_dir: Path) -> list[dict]:
    """Split the load evenly across one hey process per URL, run them together."""
    workers = len(urls)
    procs = []
    for i, url in enumerate(urls):
        c = concurrency // workers + (1 if i < concurrency % workers else 0)
        cmd = ["hey", "-c", str(c), "-t", "20"]
        if duration:
            cmd += ["-z", duration]
        else:
            n = total // workers + (1 if i < total % workers else 0)
            cmd += ["-n", str(max(n, c))]
        cmd.append(url)
        out_file = out_dir / f"hey-{i + 1}.txt"
        procs.append((url, cmd, out_file, subprocess.Popen(
            cmd, stdout=out_file.open("w"), stderr=subprocess.STDOUT)))
    results = []
    for url, cmd, out_file, proc in procs:
        proc.wait()
        text = out_file.read_text()
        results.append({"url": url, "cmd": " ".join(cmd), "exit": proc.returncode,
                        "raw": text, **parse_hey(text)})
    return results


def parse_hey(text: str) -> dict:
    def num(label: str) -> float | None:
        m = re.search(rf"{label}:\s+([\d.]+)", text)
        return float(m.group(1)) if m else None
    return {
        "total_secs": num("Total"), "slowest": num("Slowest"),
        "fastest": num("Fastest"), "average": num("Average"),
        "rps": num("Requests/sec"),
        "latency": {int(p): float(v) for p, v in
                    re.findall(r"(\d+)%+ in ([\d.]+) secs", text)},
        "status": {int(c): int(n) for c, n in
                   re.findall(r"\[(\d+)\]\s+(\d+) responses", text)},
        "errors": [(int(n), msg.strip()) for n, msg in re.findall(
            r"^\s+\[(\d+)\]\s+(.+)$",
            text.split("Error distribution:")[1] if "Error distribution:" in text else "",
            re.M)],
    }


def combine_hey(results: list[dict]) -> dict:
    status: dict[int, int] = {}
    for r in results:
        for code, n in r["status"].items():
            status[code] = status.get(code, 0) + n
    errors = sum(n for r in results for n, _ in r["errors"])
    responses = sum(status.values())
    ok = sum(n for code, n in status.items() if 200 <= code < 400)
    avg = (sum((r["average"] or 0) * sum(r["status"].values()) for r in results)
           / responses) if responses else None
    return {
        "requests": responses + errors, "responses": responses, "ok": ok,
        "errors": errors, "status": dict(sorted(status.items())),
        "success_pct": 100 * ok / (responses + errors) if responses + errors else 0,
        "rps": sum(r["rps"] or 0 for r in results),
        "duration": max((r["total_secs"] or 0) for r in results),
        "average": avg,
        "slowest": max((r["slowest"] or 0) for r in results),
        "fastest": min((r["fastest"] or 0) for r in results if r["fastest"] is not None)
        if any(r["fastest"] is not None for r in results) else None,
        # Exact percentiles need one process; with several, report the worst.
        "p50": max((r["latency"].get(50, 0) for r in results), default=None),
        "p95": max((r["latency"].get(95, 0) for r in results), default=None),
        "p99": max((r["latency"].get(99, 0) for r in results), default=None),
    }


# ----------------------------------------------------------------- report

def make_chart(samples: list[dict], load_start: datetime, load_end: datetime,
               path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    t0 = parse_ts(samples[0]["t"])
    xs = [(parse_ts(s["t"]) - t0).total_seconds() for s in samples]
    ink, muted, grid = "#0b0b0b", "#52514e", "#e4e3df"
    blue, orange = "#2a78d6", "#eb6834"

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8, 5.2), sharex=True,
                                   gridspec_kw={"hspace": 0.35})
    for ax in (ax1, ax2):
        ax.axvspan((load_start - t0).total_seconds(), (load_end - t0).total_seconds(),
                   color="#f0efeb", zorder=0)
        ax.grid(axis="y", color=grid, linewidth=0.8)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(grid)
        ax.tick_params(colors=muted, labelsize=8)

    ax1.step(xs, [s["pods"] for s in samples], where="post", color=blue,
             linewidth=2, label="Backend pods")
    ax1.step(xs, [s["hpa_desired"] or 0 for s in samples], where="post",
             color=orange, linewidth=2, linestyle="--", label="HPA desired replicas")
    hmax = next((s["hpa_max"] for s in samples if s["hpa_max"]), None)
    top = max([s["pods"] for s in samples] + [hmax or 0]) + 1
    if hmax:
        ax1.axhline(hmax, color=muted, linewidth=1, linestyle=":")
        ax1.text(xs[-1], hmax, f" maxReplicas {hmax}", color=muted, fontsize=7,
                 va="bottom", ha="right")
    ax1.set_ylim(0, top)
    ax1.yaxis.set_major_locator(plt.MaxNLocator(integer=True))
    ax1.set_title("Backend pods vs HPA desired replicas (shaded = load running)",
                  color=ink, fontsize=10, loc="left")
    ax1.legend(frameon=False, fontsize=8, loc="upper left", labelcolor=muted)

    cpu = [s["cpu_pct"] for s in samples]
    ax2.plot([x for x, c in zip(xs, cpu) if c is not None],
             [c for c in cpu if c is not None], color=blue, linewidth=2)
    ax2.axhline(70, color=muted, linewidth=1, linestyle=":")
    ax2.text(xs[-1], 70, " HPA target 70%", color=muted, fontsize=7,
             va="bottom", ha="right")
    ax2.set_title("Average backend CPU utilisation (% of request), from the HPA",
                  color=ink, fontsize=10, loc="left")
    ax2.set_xlabel("Seconds since start", color=muted, fontsize=8)
    ax2.set_ylim(bottom=0)
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)


def fmt_t(value: str | None) -> str:
    ts = parse_ts(value)
    return ts.astimezone().strftime("%H:%M:%S") if ts else "-"


def secs(v: float | None) -> str:
    return f"{v * 1000:.0f} ms" if v is not None else "-"


def build_pdf(path: Path, ctx: dict) -> None:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (Image, PageBreak, Paragraph, Preformatted,
                                    SimpleDocTemplate, Spacer, Table, TableStyle)

    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], alignment=TA_LEFT, fontSize=20)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], spaceBefore=10,
                        textColor=colors.HexColor("#0b0b0b"))
    body = ParagraphStyle("b", parent=ss["BodyText"], fontSize=9, leading=12)
    small = ParagraphStyle("s", parent=body, fontSize=7, leading=9)
    mono = ParagraphStyle("m", fontName="Courier", fontSize=6.5, leading=8)
    good, bad = colors.HexColor("#008300"), colors.HexColor("#e34948")
    head_bg, line = colors.HexColor("#f0efeb"), colors.HexColor("#d6d5cf")

    def table(rows, widths=None, font=7.5):
        cell = ParagraphStyle("cell", parent=body, fontSize=font, leading=font + 2)
        t = Table([rows[0]] + [[Paragraph(str(c), cell) for c in r] for r in rows[1:]],
                  colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle([
            ("FONT", (0, 0), (-1, -1), "Helvetica", font),
            ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", font),
            ("BACKGROUND", (0, 0), (-1, 0), head_bg),
            ("LINEBELOW", (0, 0), (-1, -1), 0.4, line),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))
        return t

    a, hey, mon, snap = ctx["accounts"], ctx["hey_total"], ctx["monitor"], ctx["cluster"]
    samples, pods = mon.samples, list(mon.pods.values())
    created_ok = [x for x in a if x.status == 201]
    start_pods = samples[0]["pods"] if samples else 0
    peak_pods = max((s["pods"] for s in samples), default=0)
    peak_desired = max((s["hpa_desired"] or 0 for s in samples), default=0)
    peak_cpu = max((s["cpu_pct"] or 0 for s in samples), default=0)
    new_pods = [p for p in pods if not p.existed_before]
    scaled = peak_pods > start_pods
    hmax = next((s["hpa_max"] for s in samples if s["hpa_max"]), None)

    story = [
        Paragraph("EKS autoscaling load test", h1),
        Paragraph(f"{ctx['started']:%Y-%m-%d %H:%M %Z} &middot; target "
                  f"<b>{ctx['url']}</b> &middot; cluster <b>{snap['context']}</b>", body),
        Spacer(1, 6),
    ]

    verdict = (f"<font color='#008300'><b>PASS</b></font>: the HPA scaled backend pods "
               f"from {start_pods} to {peak_pods} under load."
               if scaled else
               f"<font color='#e34948'><b>NO SCALE-OUT</b></font>: backend stayed at "
               f"{peak_pods} pod(s). Peak CPU was {peak_cpu}% against a 70% target.")
    story += [Paragraph(verdict, body), Spacer(1, 6)]

    story.append(table([
        ["Metric", "Value"],
        ["Accounts created", f"{len(created_ok)} / {len(a)}"],
        ["Load", ctx["load_desc"]],
        ["Requests recorded by hey", f"{hey['requests']:,}"],
        ["Successful (2xx/3xx)", f"{hey['ok']:,}  ({hey['success_pct']:.2f}%)"],
        ["Transport errors", f"{hey['errors']:,}"],
        ["Throughput", f"{hey['rps']:,.0f} req/s over {hey['duration']:.1f} s"],
        ["Latency avg / p50 / p95 / p99", f"{secs(hey['average'])} / {secs(hey['p50'])}"
                                           f" / {secs(hey['p95'])} / {secs(hey['p99'])}"],
        ["Backend pods start / peak", f"{start_pods} / {peak_pods}"
                                      f"  (HPA max {hmax if hmax else '-'})"],
        ["Peak HPA desired replicas", str(peak_desired)],
        ["Peak average CPU", f"{peak_cpu}%"],
        ["New pods created", str(len(new_pods))],
    ], widths=[60 * mm, 110 * mm], font=8.5))

    if ctx["chart"].exists():
        story += [Spacer(1, 8), Image(str(ctx["chart"]), width=175 * mm,
                                      height=175 * mm * 5.2 / 8.2)]

    # ---- EKS pods
    story += [PageBreak(), Paragraph("EKS backend pods", h2)]
    rows = [["Pod", "Node", "Pod IP", "Created", "Ready", "To ready",
             "Status", "Restarts", "Peak CPU", "Peak mem", "New"]]
    for p in sorted(pods, key=lambda p: p.created):
        c, r = parse_ts(p.created), parse_ts(p.ready_at)
        ttr = f"{(r - c).total_seconds():.0f} s" if c and r else "-"
        rows.append([p.name, p.node.split(".")[0], p.ip, fmt_t(p.created),
                     fmt_t(p.ready_at), ttr, p.phase, str(p.restarts),
                     f"{p.peak_cpu_m}m", f"{p.peak_mem_mi}Mi",
                     "no" if p.existed_before else "yes"])
    story.append(table(rows, font=6.5, widths=[m * mm for m in
                       (36, 19, 16, 14, 14, 12, 15, 12, 14, 14, 8)]))

    story += [Paragraph("Scaling events", h2)]
    if snap["events"]:
        story.append(table([["Time", "Object", "Reason", "Message"]] + [
            [fmt_t(e["time"]), e["kind"], e["reason"], e["message"]]
            for e in snap["events"]], widths=[16 * mm, 34 * mm, 44 * mm, 86 * mm]))
    else:
        story.append(Paragraph("No HPA or ReplicaSet events in the namespace "
                               "(events expire after about an hour).", body))

    story += [Paragraph("Nodes", h2), table(
        [["Node", "Instance type", "Zone", "Capacity", "CPU", "Memory"]] +
        [[n["name"], n["instance_type"], n["zone"], n["capacity_type"], n["cpu"],
          n["memory"]] for n in snap["nodes"]])]

    story += [Paragraph("HPA samples", h2), table(
        [["Time", "Pods", "Ready", "HPA current", "HPA desired", "CPU %", "CPU total"]] +
        [[fmt_t(s["t"]), s["pods"], s["ready"], s["hpa_current"], s["hpa_desired"],
          s["cpu_pct"] if s["cpu_pct"] is not None else "-", f"{s['cpu_m_total']}m"]
         for s in samples], font=6.5)]

    # ---- hey
    story += [PageBreak(), Paragraph("hey load test results", h2),
              Paragraph(ctx["load_desc"] + f", split across {len(ctx['hey'])} hey "
                        "process(es), one per account URL. With more than one process, "
                        "the percentiles shown are the worst across processes.", body),
              Spacer(1, 4)]
    story.append(table([["Target", "Requests", "RPS", "Avg", "p50", "p95", "p99",
                         "Slowest", "Status codes", "Errors"]] + [
        [r["url"].split("/api/")[-1], f"{sum(r['status'].values()) + sum(n for n, _ in r['errors']):,}",
         f"{r['rps'] or 0:,.0f}", secs(r["average"]), secs(r["latency"].get(50)),
         secs(r["latency"].get(95)), secs(r["latency"].get(99)), secs(r["slowest"]),
         ", ".join(f"{k}: {v:,}" for k, v in r["status"].items()) or "-",
         f"{sum(n for n, _ in r['errors']):,}"] for r in ctx["hey"]], font=6.5))

    story += [Paragraph("Status codes (all processes)", h2), table(
        [["Status", "Responses"]] + [[str(k), f"{v:,}"] for k, v in hey["status"].items()]
        + [["transport errors", f"{hey['errors']:,}"]], widths=[40 * mm, 40 * mm])]

    errs: dict[str, int] = {}
    for r in ctx["hey"]:
        for n, msg in r["errors"]:
            key = re.sub(r"lt-[a-z0-9-]+", "<tag>", msg)[:160]
            errs[key] = errs.get(key, 0) + n
    if errs:
        story += [Paragraph("Errors", h2), table(
            [["Count", "Error"]] + [[f"{n:,}", m] for m, n in
                                    sorted(errs.items(), key=lambda kv: -kv[1])],
            widths=[20 * mm, 160 * mm])]

    # ---- accounts
    story += [PageBreak(), Paragraph(f"Test accounts ({len(created_ok)} created)", h2),
              Paragraph("Edit tokens are masked here. The full tokens are in "
                        "accounts.json next to this report.", body), Spacer(1, 4)]
    story.append(table([["#", "Tag", "Display name", "Message", "Links", "HTTP",
                         "Create latency", "Created", "Edit token"]] + [
        [str(i), x.tag, x.display_name, x.message,
         ", ".join(link["label"] for link in x.links), str(x.status or "error"),
         f"{x.latency_ms:.0f} ms", fmt_t(x.created_at),
         f"{x.edit_token[:6]}..." if x.edit_token else "-"]
        for i, x in enumerate(a, 1)], font=6.5))
    if ctx["cleanup"] is not None:
        story.append(Paragraph(f"Cleanup: deleted {ctx['cleanup']} test account(s) "
                               "after the run.", body))

    # ---- raw hey output
    story += [PageBreak(), Paragraph("Appendix: raw hey output", h2)]
    for r in ctx["hey"]:
        story += [Paragraph(f"<b>{r['cmd']}</b>", small),
                  Preformatted(r["raw"][:6000], mono), Spacer(1, 6)]

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#52514e"))
        canvas.drawString(15 * mm, 8 * mm, "social-links EKS load test")
        canvas.drawRightString(doc.pagesize[0] - 15 * mm, 8 * mm, f"Page {doc.page}")
        canvas.restoreState()

    SimpleDocTemplate(str(path), pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                      topMargin=15 * mm, bottomMargin=15 * mm,
                      title="EKS autoscaling load test").build(
        story, onFirstPage=footer, onLaterPages=footer)


# ----------------------------------------------------------------- main

def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", help="App base URL (default: frontend LB from kubectl)")
    p.add_argument("--namespace", default="social-links")
    p.add_argument("--accounts", type=int, default=50, help="random accounts to create")
    p.add_argument("-n", "--requests", type=int, default=100_000)
    p.add_argument("-c", "--concurrency", type=int, default=500)
    p.add_argument("-z", "--duration", help="run hey for a duration (e.g. 5m) instead of -n")
    p.add_argument("--targets", type=int, default=5,
                   help="how many accounts to spread the load across (one hey each)")
    p.add_argument("--interval", type=float, default=5, help="pod sampling interval (s)")
    p.add_argument("--baseline", type=int, default=15, help="seconds to sample before load")
    p.add_argument("--cooldown", type=int, default=60, help="seconds to sample after load")
    p.add_argument("--cleanup", action="store_true", help="delete test accounts at the end")
    p.add_argument("--out", type=Path, default=ROOT / "loadtest-reports")
    args = p.parse_args()

    for tool in ("hey", "kubectl"):
        if not shutil.which(tool):
            sys.exit(f"{tool} is not installed")

    base = (args.url or discover_url(args.namespace)).rstrip("/")

    log(f"Target {base}")
    # A busy backend can miss one check (e.g. still draining a previous run).
    for attempt in range(1, 7):
        status, _ = http("GET", f"{base}/api/ready", timeout=10)
        if status == 200:
            break
        log(f"/api/ready returned {status or 'no response'} (attempt {attempt}/6)")
        if attempt < 6:
            time.sleep(5)
    else:
        sys.exit(f"{base}/api/ready returned {status or 'no response'}; is the app up? "
                 "Check `kubectl -n social-links get pods` and that no other load test is running.")

    started = now_utc().astimezone()
    out_dir = args.out / f"{started:%Y%m%d-%H%M%S}"
    out_dir.mkdir(parents=True, exist_ok=True)

    mon = Monitor(args.namespace, "app=backend", "backend", args.interval)
    mon.start()
    log(f"Monitoring pods: {mon.samples[0]['pods']} backend pod(s), "
        f"HPA desired {mon.samples[0]['hpa_desired']}")

    log(f"Creating {args.accounts} random accounts")
    accounts = create_accounts(base, args.accounts)
    ok = [x for x in accounts if x.status == 201]
    log(f"Created {len(ok)} / {len(accounts)}")
    (out_dir / "accounts.json").write_text(json.dumps([asdict(x) for x in accounts], indent=2))
    with (out_dir / "accounts.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["tag", "display_name", "message", "links", "status",
                    "latency_ms", "created_at", "edit_token"])
        for x in accounts:
            w.writerow([x.tag, x.display_name, x.message,
                        " | ".join(f"{l['label']}={l['url']}" for l in x.links),
                        x.status, f"{x.latency_ms:.1f}", x.created_at, x.edit_token])
    if not ok:
        mon.stop()
        sys.exit("No accounts were created; aborting before the load test.")

    log(f"Baseline for {args.baseline}s")
    time.sleep(args.baseline)

    targets = [f"{base}/api/profiles/{x.tag}"
               for x in random.sample(ok, min(args.targets, len(ok)))]
    load_desc = (f"{args.concurrency} concurrent users for {args.duration}" if args.duration
                 else f"{args.requests:,} requests, {args.concurrency} concurrent users")
    log(f"Running hey: {load_desc} across {len(targets)} account(s)")
    load_start = now_utc()
    hey_results = run_hey(targets, args.requests, args.concurrency, args.duration, out_dir)
    load_end = now_utc()
    hey_total = combine_hey(hey_results)
    log(f"hey done in {(load_end - load_start).total_seconds():.0f}s: "
        f"{hey_total['ok']:,}/{hey_total['requests']:,} ok, {hey_total['rps']:,.0f} req/s")

    log(f"Cooldown for {args.cooldown}s")
    time.sleep(args.cooldown)
    mon.stop()

    cleanup = None
    if args.cleanup:
        cleanup = delete_accounts(base, ok)
        log(f"Deleted {cleanup} test accounts")

    snap = cluster_snapshot(args.namespace, "backend")
    (out_dir / "samples.json").write_text(json.dumps({
        "samples": mon.samples, "pods": [asdict(p) for p in mon.pods.values()],
        "cluster": snap, "hey": [{k: v for k, v in r.items() if k != "raw"}
                                 for r in hey_results], "hey_total": hey_total,
    }, indent=2, default=str))

    chart = out_dir / "scaling.png"
    make_chart(mon.samples, load_start, load_end, chart)
    pdf = out_dir / "eks-load-test-report.pdf"
    build_pdf(pdf, {
        "url": base, "started": started, "accounts": accounts, "hey": hey_results,
        "hey_total": hey_total, "monitor": mon, "cluster": snap, "chart": chart,
        "load_desc": load_desc, "cleanup": cleanup,
    })
    peak = max(s["pods"] for s in mon.samples)
    log(f"Backend pods: {mon.samples[0]['pods']} -> peak {peak}")
    log(f"Report: {pdf}")


if __name__ == "__main__":
    main()

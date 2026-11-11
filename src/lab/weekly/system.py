"""System health for the weekly report: deploy log, backup log, PM2 processes.

Everything is read-only. Log lines are redacted (``key=value`` style secrets) and
only a handful of fields of ``pm2 jlist`` are kept: that output contains every
process's environment (API keys), so it is parsed in memory and never stored,
logged or returned as a whole.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..notify_events import deploy_log_path, redact

BACKUP_LOG = "/var/log/bmtm-backup.log"
MAX_READ = 512 * 1024
LINE_TS = re.compile(r"^\[?(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})")
_LIVE = re.compile(r"\b(backend|frontend) live @ ([0-9a-f]{6,40})")
_START = re.compile(r"\bdeploy (be|fe) (\S+) @ ([0-9a-f]{6,40})")


def backup_log_path() -> str:
    return os.environ.get("LAB_BACKUP_LOG_PATH", BACKUP_LOG)


def _tail_lines(path: str) -> Optional[list[str]]:
    p = Path(path)
    if not p.is_file():
        return None
    try:
        with p.open("rb") as fh:
            size = p.stat().st_size
            fh.seek(max(0, size - MAX_READ))
            data = fh.read()
    except OSError:
        return None
    return data.decode("utf-8", "replace").splitlines()


def _in_week(line: str, start: str, end: str) -> Optional[str]:
    m = LINE_TS.match(line)
    if not m:
        return None
    ts = m.group(1) + "Z"
    return ts if start <= ts < end else None


def deploys(start: str, end: str, path: Optional[str] = None) -> dict:
    lines = _tail_lines(path or deploy_log_path())
    if lines is None:
        return {"available": False, "events": [], "live": 0, "failed": 0, "dry_run": 0}
    events, live, failed, dry = [], 0, 0, 0
    for raw in lines:
        ts = _in_week(raw, start, end)
        if not ts:
            continue
        msg = redact(re.sub(r"^\[[^\]]+\]\s*", "", raw.strip()))
        kind = None
        m = _LIVE.search(msg)
        if m:
            kind, live = "live", live + 1
        elif "GAGAL:" in msg:
            kind, failed = "failed", failed + 1
        elif "dry-run selesai" in msg:
            kind, dry = "dry_run", dry + 1
        elif _START.search(msg) or " pm2" in f" {msg}":
            kind = "start" if _START.search(msg) else "ops"
        if kind:
            events.append({"ts": ts, "kind": kind, "message": msg[:300]})
    return {"available": True, "events": events[-100:], "live": live, "failed": failed, "dry_run": dry}


def backups(start: str, end: str, path: Optional[str] = None) -> dict:
    lines = _tail_lines(path or backup_log_path())
    if lines is None:
        return {"available": False, "ok": 0, "failed": 0, "last": None, "events": []}
    ok, bad, events = 0, 0, []
    last = None
    for raw in lines:
        m = LINE_TS.match(raw)
        if not m:
            continue
        msg = redact(raw[m.end():].lstrip("Z]").strip())[:200]
        if " ok " in f" {msg} " or re.search(r"(?i)\b(gagal|fail|error)\b", msg):
            last = {"ts": m.group(1) + "Z", "message": msg}
        ts = _in_week(raw, start, end)
        if not ts:
            continue
        is_ok = re.match(r"^\s*ok\b", msg) is not None
        is_bad = bool(re.search(r"(?i)\b(gagal|fail|error)\b", msg))
        ok += is_ok
        bad += is_bad and not is_ok
        if is_ok or is_bad:
            events.append({"ts": ts, "ok": is_ok, "message": msg})
    return {"available": True, "ok": ok, "failed": bad, "last": last, "events": events[-20:]}


# ── PM2 ───────────────────────────────────────────────────────────────────

_PM2_KEEP_TTL = 60.0
_pm2_cache: dict = {"t": 0.0, "v": None}
_pm2_lock = threading.Lock()


def _iso_ms(ms) -> Optional[str]:
    try:
        return datetime.fromtimestamp(float(ms) / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def pm2_processes(runner=None) -> Optional[list[dict]]:
    """[{name, status, restarts, unstable_restarts, up_since}] or None when PM2 is not reachable.
    Restart counts are cumulative since the process was (re)registered, not per week."""
    with _pm2_lock:
        if runner is None and time.monotonic() - _pm2_cache["t"] < _PM2_KEEP_TTL:
            return _pm2_cache["v"]
        out = None
        try:
            if runner is not None:
                raw = runner()
            elif shutil.which("pm2"):
                raw = subprocess.run(["pm2", "jlist"], capture_output=True, timeout=8, check=False).stdout
            else:
                raw = None
            if raw:
                procs = json.loads(raw)
                out = []
                for p in procs if isinstance(procs, list) else []:
                    env = p.get("pm2_env") or {}
                    out.append({"name": str(p.get("name") or "")[:60], "status": str(env.get("status") or ""),
                                "restarts": env.get("restart_time"), "unstable_restarts": env.get("unstable_restarts"),
                                "up_since": _iso_ms(env.get("pm_uptime"))})
                    del env
                del procs
        except (OSError, ValueError, subprocess.SubprocessError):
            out = None
        if runner is None:
            _pm2_cache.update(t=time.monotonic(), v=out)
        return out

"""Webhook evidence from logs (stdlib, read-only).

nginx access log (combined format, ``/var/log/nginx/access.log*`` incl. logrotate'd .gz):
every ``POST /webhook/tradingview`` from a non-local IP. The request body is not in
the access log, so a line only says *that* something was delivered, when, from which
client and with which status (499 = the client hung up first: TradingView waits ~3 s).

App log (the API's JSON log lines, PM2 out/error logs + the 2026-11-06 evidence
extracts): the status the app actually returned ("Request completed"), orders that
were placed ("Order placed: ... side=buy"), execution failures and duplicates.

Only sanitised fields are returned: never the raw line, passphrases, API keys, user
ids, order ids or full client IPs.
"""
from __future__ import annotations

import glob
import gzip
import hashlib
import ipaddress
import json
import os
import re
import socket
import subprocess
from datetime import datetime
from functools import lru_cache
from typing import Iterable, Iterator, Optional

TV_UA = "tradingview"

_NGINX = re.compile(
    r'^(?P<ip>\S+) \S+ \S+ \[(?P<ts>[^\]]+)\] "(?P<method>[A-Z]+) (?P<path>\S+)[^"]*" (?P<status>\d{3}) '
    r'(?P<bytes>\d+|-)(?: "(?P<ref>[^"]*)" "(?P<ua>[^"]*)")?')
_NGINX_TS = re.compile(r"\[(\d{2}/\w{3}/\d{4}:\d{2}:\d{2}:\d{2} [+-]\d{4})\]")

_SYMBOL = re.compile(r"symbol=([A-Z0-9]+/?[A-Z0-9]*(?::[A-Z0-9]+)?)")
_ORDER = re.compile(r"Order placed: symbol=(\S+) side=(buy|sell)\b")
_FAIL = re.compile(r"Order execution failed for user=\S+ symbol=(\S+?): (.*)$")
_TIMING = re.compile(r"Webhook timing for (\S+?):")

_REDACT = (
    (re.compile(r"(?i)(passphrase|api[_-]?key|secret|signature|token|password)\S*"), r"\1=***"),
    (re.compile(r"(?i)\buser(?:_id)?[=: ]+'?[\w@.\-]+'?"), "user=***"),
    (re.compile(r"'user-[^']*'"), "'***'"),
    (re.compile(r"\buser-[\w-]+"), "user-***"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "***@***"),
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I), "<id>"),
    (re.compile(r"\b\d{12,}\b"), "<id>"),
)


def sanitize(text: Optional[str], limit: int = 220) -> Optional[str]:
    """Strip anything that identifies a user or could be a secret; shorten."""
    if text is None:
        return None
    s = str(text)
    for rx, rep in _REDACT:
        s = rx.sub(rep, s)
    s = " ".join(s.split())
    return s if len(s) <= limit else s[: limit - 1] + "…"


# ── IPs ──────────────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def own_ips() -> frozenset:
    """The server's own addresses (a curl from the box itself goes out and back in via
    the public IP and shows up in nginx with it)."""
    ips: set[str] = set()
    try:
        out = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=3).stdout
        ips.update(out.split())
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        ips.add(socket.gethostbyname(socket.gethostname()))
    except OSError:
        pass
    return frozenset(ips)


def is_local(ip: str, extra: Iterable[str] = ()) -> bool:
    if ip in extra or ip in own_ips():
        return True
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return a.is_loopback or a.is_private or a.is_link_local or a.is_unspecified


def mask_ip(ip: str) -> str:
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return "?"
    if a.version == 4:
        p = ip.split(".")
        return f"{p[0]}.{p[1]}.x.x"
    return ip.split(":")[0] + ":…"


# ── files ────────────────────────────────────────────────────────────────────

def files(pattern: str) -> list[str]:
    return sorted(p for p in glob.glob(pattern) if os.path.isfile(p))


def file_sig(path: str) -> str:
    st = os.stat(path)
    return f"{os.path.basename(path)}|{st.st_size}|{int(st.st_mtime)}"


def iter_lines(path: str) -> Iterator[str]:
    """Lines of a plain or gzip'ed log; opened read-only, undecodable bytes replaced."""
    with open(path, "rb") as fh:
        magic = fh.read(2)
    opener = gzip.open if magic == b"\x1f\x8b" else open
    try:
        with opener(path, "rb") as fh:
            for raw in fh:
                yield raw.decode("utf-8", "replace").rstrip("\r\n")
    except (OSError, EOFError):  # truncated .gz while logrotate is compressing it
        return


def line_hash(source: str, line: str) -> str:
    return hashlib.sha1(f"{source}\x00{line}".encode("utf-8", "replace")).hexdigest()


# ── nginx ────────────────────────────────────────────────────────────────────

def nginx_ts(s: str) -> Optional[float]:
    try:
        return datetime.strptime(s, "%d/%b/%Y:%H:%M:%S %z").timestamp()
    except ValueError:
        return None


def parse_nginx(line: str, webhook_path: str, local_ips: Iterable[str] = ()) -> Optional[dict]:
    """A webhook POST from a non-local client -> sanitised fact; anything else -> None."""
    if webhook_path not in line:
        return None
    m = _NGINX.match(line)
    if not m or m["method"] != "POST" or m["path"].split("?")[0].rstrip("/") != webhook_path.rstrip("/"):
        return None
    ts = nginx_ts(m["ts"])
    if ts is None or is_local(m["ip"], local_ips):
        return None
    ua = m["ua"] or ""
    return {"ts": ts, "status": int(m["status"]), "tv": TV_UA in ua.lower(), "ip": mask_ip(m["ip"]),
            "ua": "TradingView" if TV_UA in ua.lower() else sanitize(ua.split("/")[0], 40) or "-"}


def first_last_nginx(path: str) -> Optional[tuple[float, float]]:
    first = last = None
    for line in iter_lines(path):
        m = _NGINX_TS.search(line)
        if not m:
            continue
        t = nginx_ts(m.group(1))
        if t is None:
            continue
        first = t if first is None else first
        last = t
    return (first, last) if first is not None else None


# ── app log ──────────────────────────────────────────────────────────────────

def _app_ts(s: str) -> Optional[float]:
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S%z").timestamp()
    except (TypeError, ValueError):
        return None


def parse_app(line: str, webhook_path: str) -> Optional[tuple[str, float, dict]]:
    """(kind, ts, data) for webhook-related JSON log lines, else None. ``ts`` is the
    second the line was written."""
    if not line.startswith("{") or ("webhook" not in line and "src.trading" not in line):
        return None
    try:
        d = json.loads(line)
    except ValueError:
        return None
    ts = _app_ts(d.get("timestamp"))
    if ts is None:
        return None
    msg = str(d.get("message") or "")
    logger = str(d.get("logger") or "")
    if msg == "Request completed":
        if d.get("endpoint") != webhook_path or d.get("method") != "POST":
            return None
        try:
            status = int(d.get("status_code"))
        except (TypeError, ValueError):
            return None
        ms = d.get("response_time_ms")
        return "done", ts, {"status": status, "ms": float(ms) if isinstance(ms, (int, float)) else None}
    m = _ORDER.search(msg)
    if m and logger.endswith("executor"):
        return "order", ts, {"symbol": m.group(1), "trade_dir": 1 if m.group(2) == "buy" else -1}
    m = _FAIL.search(msg)
    if m:
        return "fail", ts, {"symbol": m.group(1), "reason": sanitize(m.group(2))}
    if "Duplicate webhook delivery rejected" in msg:
        sm = _SYMBOL.search(msg)
        return "dup", ts, {"symbol": sm.group(1) if sm else None}
    m = _TIMING.search(msg)
    if m:
        return "timing", ts, {"symbol": m.group(1)}
    if logger.startswith("src.trading") and "symbol=" in msg:
        sm = _SYMBOL.search(msg)
        if sm:  # any other webhook-path line that names the symbol (tells us which coin it was)
            return "sym", ts, {"symbol": sm.group(1)}
    return None


def first_last_app(path: str) -> Optional[tuple[float, float]]:
    first = last = None
    for line in iter_lines(path):
        if not line.startswith('{"timestamp": "'):
            continue
        t = _app_ts(line[15:39].split('"')[0])
        if t is None:
            continue
        first = t if first is None else first
        last = t
    return (first, last) if first is not None else None


# ── collection ───────────────────────────────────────────────────────────────

def collect(nginx_glob: str, app_globs: Iterable[str], webhook_path: str, local_ips: Iterable[str] = (),
            skip_sigs: Iterable[str] = (), now: Optional[float] = None) -> dict:
    """Read every log file once. Files whose signature (name|size|mtime) is in
    ``skip_sigs`` are immutable rotated files already read by an earlier cycle.

    Returns {"evidence": [{hash, source, kind, ts, data}], "coverage": [[start, end, source]],
             "sigs": [signature of every rotated (.gz) file read], "files": n, "errors": [..]}"""
    import time
    now = now or time.time()
    skip = set(skip_sigs)
    local_ips = tuple(local_ips)
    ev: list[dict] = []
    cov: list[list] = []
    sigs: list[str] = []
    errors: list[str] = []
    n = 0

    def _read(path: str, source: str) -> None:
        nonlocal n
        try:
            sig = file_sig(path)
        except OSError as e:
            errors.append(f"{os.path.basename(path)}: {type(e).__name__}")
            return
        rotated = path.endswith(".gz") or "__" in os.path.basename(path)
        if rotated and sig in skip:
            return
        n += 1
        first = last = None
        try:
            for line in iter_lines(path):
                if source == "nginx":
                    m = _NGINX_TS.search(line)
                    t = nginx_ts(m.group(1)) if m else None
                    fact = parse_nginx(line, webhook_path, local_ips)
                    kind = "hit"
                else:
                    t = _app_ts(line[15:39].split('"')[0]) if line.startswith('{"timestamp": "') else None
                    parsed = parse_app(line, webhook_path)
                    fact = None
                    if parsed:
                        kind, _, fact = parsed[0], parsed[1], {**parsed[2], "ts": parsed[1]}
                if t is not None:
                    first = t if first is None else first
                    last = t
                if fact:
                    ts = fact.pop("ts")
                    ev.append({"hash": line_hash(source, line), "source": source, "kind": kind, "ts": ts,
                               "data": fact})
        except PermissionError as e:
            errors.append(f"{os.path.basename(path)}: {type(e).__name__}")
            return
        try:
            live = not rotated and now - os.stat(path).st_mtime < 26 * 3600
        except OSError:
            live = False
        if live and first is not None:  # still being written: no line since the last one = nothing came
            last = now
        if first is not None:
            cov.append([first, last, source])
        if rotated:
            sigs.append(sig)

    for p in files(nginx_glob):
        _read(p, "nginx")
    seen: set[str] = set()
    for g in app_globs:
        for p in files(g):
            if p not in seen:
                seen.add(p)
                _read(p, "app")
    return {"evidence": ev, "coverage": cov, "sigs": sigs, "files": n, "errors": errors}


def merge_intervals(iv: list[list], tolerance_s: float = 26 * 3600) -> list[list]:
    """Union of [start, end, source] intervals; touching / near-touching ones (gap below
    ``tolerance_s``, e.g. between two daily rotated files) are joined."""
    out: list[list] = []
    for a, b, src in sorted((float(x[0]), float(x[1]), x[2] if len(x) > 2 else "") for x in iv):
        if out and a <= out[-1][1] + tolerance_s:
            out[-1][1] = max(out[-1][1], b)
            if src and src not in out[-1][2].split("+"):
                out[-1][2] = "+".join(sorted(set(out[-1][2].split("+") + [src]) - {""}))
        else:
            out.append([a, b, src])
    return out


def covered(t: float, intervals: list[list], slack_s: float = 0.0) -> bool:
    return any(a - slack_s <= t <= b + slack_s for a, b, *_ in intervals)

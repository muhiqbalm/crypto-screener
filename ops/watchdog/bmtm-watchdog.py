#!/usr/bin/env python3
"""BMTM watchdog: checks the production processes every few minutes (cron) and
sends one Telegram message when something breaks, a reminder every hour while it
stays broken, and one message when it recovers. Read-only: it never restarts
anything, never touches orders, and never logs or prints secrets.

Checks
  api      GET 127.0.0.1:8000/api/v1/health == 200
  web      GET 127.0.0.1:3000/login == 200
  pm2      bmtm-api, bmtm-web, bmtm-lab-worker all "online"
  disk     / below 90 % full
  webhook  no 5xx / 499 (TradingView gave up) in the webhook log, last 10 min
  lab      no Lab job queued for more than 20 min

Usage
  bmtm-watchdog.py            run checks, alert on changes (cron)
  bmtm-watchdog.py --status   print the checks, send nothing
  bmtm-watchdog.py --verify-telegram   check the bot token with getMe (no message)
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

# The VPS resolves api.telegram.org to IPv6 first but has no working IPv6
# route, and urllib does not fall back; use IPv4 addresses only.
import socket

_getaddrinfo = socket.getaddrinfo


def _ipv4_first(*args, **kwargs):
    res = _getaddrinfo(*args, **kwargs)
    return [r for r in res if r[0] == socket.AF_INET] or res


socket.getaddrinfo = _ipv4_first

ENV_FILE = Path("/root/crypto-screener/.env")
STATE_FILE = Path("/var/lib/bmtm-watchdog/state.json")
WEBHOOK_LOG = Path("/var/log/nginx/webhook.log")
LAB_DB = Path("/root/crypto-screener/data/lab/lab.db")
PM2_APPS = ("bmtm-api", "bmtm-web", "bmtm-lab-worker")
REMIND_EVERY_S = 3600
WIB = timezone(timedelta(hours=7))


def read_env(keys: tuple[str, ...]) -> dict[str, str]:
    """Read only the named keys from .env; values are never printed."""
    out: dict[str, str] = {}
    try:
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip().removeprefix("export ").strip()
            if k in keys:
                out[k] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return out


def http_status(url: str, timeout: float = 8.0) -> int:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0


def check_api() -> str | None:
    s = http_status("http://127.0.0.1:8000/api/v1/health")
    return None if s == 200 else f"API tidak sehat (status {s or 'tidak menjawab'})"


def check_web() -> str | None:
    s = http_status("http://127.0.0.1:3000/login")
    return None if s == 200 else f"Web tidak sehat (status {s or 'tidak menjawab'})"


def check_pm2() -> str | None:
    try:
        raw = subprocess.run(["pm2", "jlist"], capture_output=True, text=True, timeout=20).stdout
        procs = {p["name"]: p["pm2_env"]["status"] for p in json.loads(raw)}
    except Exception as exc:
        return f"PM2 tidak bisa dibaca ({type(exc).__name__})"
    bad = [f"{n}={procs.get(n, 'tidak ada')}" for n in PM2_APPS if procs.get(n) != "online"]
    return f"Proses mati: {', '.join(bad)}" if bad else None


def check_disk() -> str | None:
    u = shutil.disk_usage("/")
    pct = u.used / u.total * 100
    return f"Disk {pct:.0f}% penuh" if pct >= 90 else None


def check_webhook() -> str | None:
    if not WEBHOOK_LOG.exists():
        return None
    since = datetime.now(timezone.utc) - timedelta(minutes=10)
    bad = []
    try:
        with WEBHOOK_LOG.open() as f:
            lines = f.readlines()[-500:]
    except OSError:
        return None
    for line in lines:
        m = re.match(r"(\S+) .*status=(\d{3}) rt=([\d.]+)", line)
        if not m:
            continue
        try:
            t = datetime.fromisoformat(m.group(1))
        except ValueError:
            continue
        status = int(m.group(2))
        if t >= since and (status >= 500 or status == 499):
            bad.append(f"{status} ({float(m.group(3)):.1f} dtk) {t.astimezone(WIB):%H:%M} WIB")
    if not bad:
        return None
    return "Webhook TradingView gagal: " + "; ".join(bad[-3:]) + ". Cek apakah order masuk di Binance."


def check_lab() -> str | None:
    if not LAB_DB.exists():
        return None
    try:
        c = sqlite3.connect(f"file:{LAB_DB}?mode=ro", uri=True, timeout=5)
        row = c.execute(
            "select count(*), min(created_at) from lab_jobs where status = 'queued'"
        ).fetchone()
        c.close()
    except Exception as exc:
        return f"lab.db tidak bisa dibaca ({type(exc).__name__})"
    n, oldest = row
    if not n or not oldest:
        return None
    try:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(oldest.replace("Z", "+00:00"))
    except ValueError:
        return None
    if age > timedelta(minutes=20):
        return f"{n} job Lab antre, yang tertua sudah {int(age.total_seconds() // 60)} menit"
    return None


CHECKS = {
    "api": check_api,
    "web": check_web,
    "pm2": check_pm2,
    "disk": check_disk,
    "webhook": check_webhook,
    "lab": check_lab,
}


def send(text: str) -> bool:
    env = read_env(("TRADING_TELEGRAM_BOT_TOKEN", "TRADING_TELEGRAM_DEFAULT_CHAT_ID"))
    token, chat = env.get("TRADING_TELEGRAM_BOT_TOKEN"), env.get("TRADING_TELEGRAM_DEFAULT_CHAT_ID")
    if not token or not chat:
        print("telegram not configured; message not sent", file=sys.stderr)
        return False
    data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
    try:
        with urllib.request.urlopen(
            f"https://api.telegram.org/bot{token}/sendMessage", data=data, timeout=10
        ) as r:
            return r.status == 200
    except Exception as exc:  # never include the URL (it holds the token)
        print(f"telegram send failed: {type(exc).__name__}", file=sys.stderr)
        return False


def main() -> int:
    if "--verify-telegram" in sys.argv:
        env = read_env(("TRADING_TELEGRAM_BOT_TOKEN",))
        token = env.get("TRADING_TELEGRAM_BOT_TOKEN")
        if not token:
            print("token: missing")
            return 1
        try:
            with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/getMe", timeout=10) as r:
                ok = json.load(r).get("ok")
        except Exception as exc:
            print(f"getMe failed: {type(exc).__name__}")
            return 1
        print(f"token valid: {ok}")
        return 0 if ok else 1

    results = {name: fn() for name, fn in CHECKS.items()}
    if "--status" in sys.argv:
        for name, problem in results.items():
            print(f"{name:8} {'OK' if problem is None else 'MASALAH: ' + problem}")
        return 0

    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        state = json.loads(STATE_FILE.read_text())
    except Exception:
        state = {}
    now = time.time()
    stamp = datetime.now(WIB).strftime("%d %b %H:%M WIB")
    for name, problem in results.items():
        prev = state.get(name, {})
        if problem:
            due = not prev.get("down") or now - prev.get("last_alert", 0) >= REMIND_EVERY_S
            if due and send(f"[BMTM watchdog] MASALAH {stamp}\n{problem}"):
                prev["last_alert"] = now
            prev.update(down=True, problem=problem, since=prev.get("since") or now)
        elif prev.get("down"):
            mins = int((now - prev.get("since", now)) // 60)
            send(f"[BMTM watchdog] PULIH {stamp}\n{name} normal lagi (bermasalah ±{mins} menit).")
            prev = {"down": False}
        else:
            prev = {"down": False}
        state[name] = prev
    STATE_FILE.write_text(json.dumps(state))
    return 0


if __name__ == "__main__":
    sys.exit(main())

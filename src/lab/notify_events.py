"""Turn Lab events into in-web notifications (stdlib). Each function is called from
one hook point with a single additive line and never raises:

  job_finished      src/lab/queue.py finish() / reap()   (run: backtest / validate / optimize, whole scans)
  paper_position    src/lab/paper.py open_position() / close_position()   (preset paper watches)
  ledger_verdicts   src/lab/ledger/jobs.py execute_cycle()   (after scoring)
  deploy_log_scan   src/lab/weekly/schedule.py tick()   (worker scheduler; /var/log/bmtm-deploy.log)
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
from pathlib import Path
from typing import Optional

from .notify import notify

log = logging.getLogger("lab.notify")

MODE_LABEL = {"backtest": "Backtest", "validate": "Validasi", "optimize": "Optimasi"}
VERDICT_LABEL = {"terbukti": "terbukti", "negatif": "negatif", "belum_terbukti": "belum terbukti",
                 "belum_cukup_data": "belum cukup data"}
STRONG = ("terbukti", "negatif")
DEPLOY_LOG = "/var/log/bmtm-deploy.log"
DEPLOY_RE = re.compile(r"\b(backend|frontend) live @ ([0-9a-f]{6,40})|GAGAL:")   # bmtm-deploy.sh: die() = "GAGAL: ..."
_SECRET_RE = re.compile(r"(?i)(pass(phrase|word)?|secret|token|api[_-]?key|authorization)\s*[=:]\s*\S+")


def _coin(symbol: str) -> str:
    s = (symbol or "").upper()
    return s[:-4] if s.endswith("USDT") else s


def _pct(v) -> str:
    return "—" if v is None else f"{v:+.2f}%"


def _safe(fn):
    def wrap(*a, **kw):
        try:
            return fn(*a, **kw)
        except Exception:  # noqa: BLE001
            log.exception("notification hook %s failed", fn.__name__)
            return None
    wrap.__name__ = fn.__name__
    wrap.__doc__ = fn.__doc__
    return wrap


# ── Lab jobs ──────────────────────────────────────────────────────────────

@_safe
def job_finished(conn, job: dict) -> Optional[int]:
    """A run job reached a terminal status. Single runs: done / error. Scan cells: one
    notification when the LAST cell of the scan is finished (any terminal status)."""
    if job.get("kind") != "run" or job.get("ref_id") is None:
        return None
    r = conn.execute("SELECT id, scan_id, mode, template_id, symbol, timeframe, status, verdict, net_return_pct, "
                     "max_dd_pct, trades, error FROM lab_runs WHERE id=?", (job["ref_id"],)).fetchone()
    if r is None:
        return None
    status = job.get("status")
    if r["scan_id"] is not None:
        return _scan_finished(conn, int(r["scan_id"]))
    if status not in ("done", "error"):
        return None
    label = MODE_LABEL.get(r["mode"], r["mode"])
    what = f"{r['timeframe'].upper()}-{_coin(r['symbol'])} {r['template_id']}"
    if status == "error":
        err = (job.get("error") or r["error"] or "").strip().splitlines()
        return notify(conn, "job", f"{label} #{r['id']} gagal: {what}", (err[-1] if err else "")[:300] or None,
                      f"/lab/runs/{r['id']}", f"job:{job['id']}:error")
    bits = []
    if r["verdict"]:
        bits.append(r["verdict"])
    if r["net_return_pct"] is not None:
        bits.append(f"return {_pct(r['net_return_pct'])}")
    if r["max_dd_pct"] is not None:
        bits.append(f"DD {abs(r['max_dd_pct']):.2f}%")
    if r["trades"] is not None:
        bits.append(f"{r['trades']} trade")
    return notify(conn, "job", f"{label} #{r['id']} selesai: {what}", " · ".join(bits) or None,
                  f"/lab/runs/{r['id']}", f"job:{job['id']}:done")


def _scan_finished(conn, scan_id: int) -> Optional[int]:
    left = conn.execute("SELECT COUNT(*) FROM lab_runs WHERE scan_id=? AND status NOT IN ('done','error','cancelled')",
                        (scan_id,)).fetchone()[0]
    if left:
        return None
    s = conn.execute("SELECT template_id, mode FROM lab_scans WHERE id=?", (scan_id,)).fetchone()
    c = conn.execute("SELECT COUNT(*) AS n, SUM(status='done') AS done, SUM(status='error') AS err, "
                     "SUM(status='cancelled') AS canc, SUM(verdict='PASS') AS pass FROM lab_runs WHERE scan_id=?",
                     (scan_id,)).fetchone()
    body = f"{c['done'] or 0}/{c['n']} sel selesai"
    if s and s["mode"] != "backtest":
        body += f" · {c['pass'] or 0} PASS"
    if c["err"]:
        body += f" · {c['err']} gagal"
    if c["canc"]:
        body += f" · {c['canc']} dibatalkan"
    tpl = f" {s['template_id']}" if s else ""
    return notify(conn, "job", f"Scan #{scan_id} selesai:{tpl}", body, f"/lab/scan?id={scan_id}",
                  f"scan:{scan_id}:finished")


# ── paper presets ─────────────────────────────────────────────────────────

def _preset_name(conn, watch_id: int) -> Optional[str]:
    have = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN "
                        "('lab_presets','lab_preset_links')").fetchone()[0]
    if have < 2:
        return None
    r = conn.execute("SELECT p.name FROM lab_preset_links l JOIN lab_presets p ON p.id = l.preset_id "
                     "WHERE l.kind='watch' AND l.ref_id=?", (watch_id,)).fetchone()
    return r["name"] if r else None


def _px(v) -> str:
    return "—" if v is None else f"{float(v):.6g}"


@_safe
def paper_position(conn, pos: dict, event: str) -> Optional[int]:
    """event = open | close. Only automatic positions of a watch (the preset paper mirrors);
    manual paper orders are the admin's own action and Universal has its own rebalance log."""
    if not pos or pos.get("source") != "paper_auto" or pos.get("watch_id") is None:
        return None
    name = _preset_name(conn, int(pos["watch_id"])) or f"watch {pos['watch_id']}"
    side = (pos.get("side") or "").upper()
    if event == "open":
        body = f"{side} {pos['symbol']} @ {_px(pos.get('entry_price'))} · SL {_px(pos.get('sl'))}" + (
            f" · TP {_px(pos.get('tp'))}" if pos.get("tp") else "")
        return notify(conn, "paper", f"Paper {name}: buka {side}", body, "/lab/presets",
                      f"paper:{pos['id']}:open")
    pnl = pos.get("pnl")
    r_mult = (pnl / pos["risk_amount"]) if pnl is not None and pos.get("risk_amount") else None
    body = f"{side} {pos['symbol']} ditutup @ {_px(pos.get('exit_price'))} · PnL " + (
        "—" if pnl is None else f"{pnl:+,.2f} USDT") + (f" ({r_mult:+.2f}R)" if r_mult is not None else "") + (
        f" · {pos['exit_reason']}" if pos.get("exit_reason") else "")
    return notify(conn, "paper", f"Paper {name}: tutup {side}", body, "/journal", f"paper:{pos['id']}:close")


# ── Signal Ledger ─────────────────────────────────────────────────────────

KV_LEDGER = "notify_ledger_verdicts"


@_safe
def ledger_verdicts(conn) -> list[int]:
    """Compare the overall 1d verdict of every signal group with the last cycle. The first
    call only records a baseline. A change notifies when either side is terbukti / negatif
    (belum cukup data <-> belum terbukti flips are noise); 4+ changes become one summary."""
    from .ledger.store import kv_get, kv_set
    from .ledger.verdicts import verdicts
    now = {v["key"]: v for v in verdicts(conn)}
    prev = kv_get(conn, KV_LEDGER)
    kv_set(conn, KV_LEDGER, {k: v["verdict"] for k, v in now.items()})
    conn.commit()
    if prev is None:
        return []
    changes = [(k, prev.get(k), v) for k, v in now.items()
               if prev.get(k) != v["verdict"] and (v["verdict"] in STRONG or prev.get(k) in STRONG)]
    if not changes:
        return []

    def name(v: dict) -> str:
        return f"{v['signal_type']} {'long' if v['direction'] > 0 else 'short'} ({v['source']})"

    def stamp(k, old, v) -> str:
        return hashlib.sha1(f"{k}|{old}|{v['verdict']}|{v['n']}".encode()).hexdigest()[:16]

    ids = []
    if len(changes) <= 3:
        for k, old, v in changes:
            body = (f"{VERDICT_LABEL.get(old, old or 'baru')} → {VERDICT_LABEL[v['verdict']]} · n={v['n']} "
                    f"({v['days']} hari) · rata-rata 1 hari {_pct(v['mean_pct'])}")
            i = notify(conn, "ledger", f"Catatan Sinyal: {name(v)} kini {VERDICT_LABEL[v['verdict']]}", body,
                       f"/lab/signals?type={v['signal_type']}", f"ledger:{stamp(k, old, v)}")
            if i:
                ids.append(i)
        return ids
    body = "; ".join(f"{name(v)}: {VERDICT_LABEL.get(old, old or 'baru')} → {VERDICT_LABEL[v['verdict']]}"
                     for _, old, v in changes[:8]) + (f"; +{len(changes) - 8} lagi" if len(changes) > 8 else "")
    key = hashlib.sha1("|".join(stamp(*c) for c in changes).encode()).hexdigest()[:16]
    i = notify(conn, "ledger", f"Catatan Sinyal: {len(changes)} vonis berubah", body, "/lab/signals",
               f"ledger:multi:{key}")
    return [i] if i else []


# ── deploys ───────────────────────────────────────────────────────────────

KV_DEPLOY = "notify_deploy_offset"


def deploy_log_path() -> str:
    return os.environ.get("LAB_DEPLOY_LOG_PATH", DEPLOY_LOG)


def redact(line: str) -> str:
    return _SECRET_RE.sub(lambda m: m.group(1) + "=***", line)


@_safe
def deploy_log_scan(conn, path: Optional[str] = None, max_bytes: int = 65536) -> list[int]:
    """Read lines appended to the deploy log since the last call (read-only); notify on
    "<backend|frontend> live @ <sha>", rollbacks and failures. First call = baseline."""
    from .ledger.store import kv_get, kv_set
    p = Path(path or deploy_log_path())
    if not p.is_file():
        return []
    size = p.stat().st_size
    off = kv_get(conn, KV_DEPLOY)
    if off is None or size < int(off):          # first run, or the log was rotated / truncated
        kv_set(conn, KV_DEPLOY, size if off is None else 0)
        conn.commit()
        if off is None:
            return []
        off = 0
    off = int(off)
    if size == off:
        return []
    start = max(off, size - max_bytes)
    with p.open("rb") as fh:
        fh.seek(start)
        chunk = fh.read(size - start)
    end = chunk.rfind(b"\n")
    if end < 0:
        return []                                 # partial line: wait for the newline
    kv_set(conn, KV_DEPLOY, start + end + 1)
    conn.commit()
    ids = []
    for raw in chunk[:end].decode("utf-8", "replace").splitlines():
        m = DEPLOY_RE.search(raw)
        if not m or "dry-run" in raw:
            continue
        line = redact(raw.strip())
        msg = re.sub(r"^\[[^\]]+\]\s*", "", line)
        if m.group(1):
            title = f"Deploy {m.group(1)} live @ {m.group(2)[:7]}"
        else:
            title = "Deploy gagal: " + msg.replace("GAGAL:", "").strip()[:110]
        i = notify(conn, "deploy", title, msg[:400], "/lab/report",
                   "deploy:" + hashlib.sha1(raw.encode()).hexdigest()[:20])
        if i:
            ids.append(i)
    return ids

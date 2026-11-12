"""Turn Lab events into in-web notifications (stdlib). Each function is called from
one hook point with a single additive line and never raises:

  job_finished      src/lab/queue.py finish() / reap()   (run: backtest / validate / optimize, whole scans)
  paper_position    src/lab/paper.py open_position() / close_position()   (preset paper watches)
  ledger_verdicts   src/lab/ledger/jobs.py execute_cycle()   (after scoring)
  deploy_log_scan   src/lab/weekly/schedule.py tick()   (worker scheduler; /var/log/bmtm-deploy.log)
  report_ready      src/lab/weekly/schedule.py snapshot_week()   (weekly snapshot frozen)

Copy rules (same as the web UI, glossary in docs/riset-2026-11-12/02-audit-ux.md §4):
Indonesian, one name per concept (Uji jujur, Cari setting terbaik, Lolos / Gagal, Rekam jejak
sinyal, Pembaruan sistem), exchange-style numbers ``1,234.56`` with a real minus sign, times
in WIB with Indonesian month names, and every paper message says it is a simulation.
Dedupe keys and links are part of the contract with the bell UI; titles and bodies are not.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from .notify import notify

log = logging.getLogger("lab.notify")

MODE_LABEL = {"backtest": "Uji historis cepat", "validate": "Uji jujur", "optimize": "Cari setting terbaik"}
RUN_VERDICT_LABEL = {"PASS": "Lolos", "FAIL": "Gagal"}
TEMPLATE_LABEL = {"rosyade_family": "Rosyade", "donchian_breakout": "Donchian breakout",
                  "mean_reversion_range": "Mean reversion (range)"}
TF_LABEL = {"1m": "1 menit", "5m": "5 menit", "15m": "15 menit", "30m": "30 menit", "1h": "1 jam", "2h": "2 jam",
            "4h": "4 jam", "6h": "6 jam", "12h": "12 jam", "1d": "1 hari", "1w": "1 minggu"}
VERDICT_LABEL = {"terbukti": "terbukti", "negatif": "negatif", "belum_terbukti": "belum terbukti",
                 "belum_cukup_data": "belum cukup data"}
SIGNAL_TYPE_LABEL = {"komposit": "Komposit", "komposit_high": "Komposit keyakinan tinggi", "tier_a": "Tier A",
                     "tier_c": "Tier C", "momentum": "Momentum 30 hari", "funding": "Funding", "oi": "OI × harga",
                     "tv_open": "Alert TradingView", "universal_v0": "Universal v0"}
SIGNAL_SOURCE_LABEL = {"screener": "screener", "screener_rekon": "rekonstruksi screener", "lab_watch": "pantau Lab",
                       "universal": "Universal, arsip", "webhook": "webhook"}
EXIT_LABEL = {"hard_tp": "kena target (TP)", "hard_sl": "kena batal jika (SL)", "manual_close": "ditutup manual",
              "strategy_reverse": "strategi berbalik arah", "universal_rebalance": "rebalance Universal"}
MONTHS = ("Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des")
WIB = timezone(timedelta(hours=7))
MINUS = "−"
PAPER_NOTE = "simulasi, bukan order sungguhan"
STRONG = ("terbukti", "negatif")
DEPLOY_LOG = "/var/log/bmtm-deploy.log"
DEPLOY_RE = re.compile(r"\b(backend|frontend) live @ ([0-9a-f]{6,40})|GAGAL:")   # bmtm-deploy.sh: die() = "GAGAL: ..."
_SECRET_RE = re.compile(r"(?i)(pass(phrase|word)?|secret|token|api[_-]?key|authorization)\s*[=:]\s*\S+")


# ── formatting (pure) ─────────────────────────────────────────────────────

def _coin(symbol: str) -> str:
    s = (symbol or "").upper()
    return s[:-4] if s.endswith("USDT") else s


def _tf(tf: str) -> str:
    return TF_LABEL.get((tf or "").lower(), tf or "")


def _strategy(template_id: str) -> str:
    if template_id in TEMPLATE_LABEL:
        return TEMPLATE_LABEL[template_id]
    s = (template_id or "").replace("_", " ").strip()
    return s[:1].upper() + s[1:]


def _signed(v, digits: int = 2) -> str:
    """+1,234.56 / −1,234.56 / 0.00 (exchange style, real minus sign)."""
    x = round(float(v), digits)
    body = f"{abs(x):,.{digits}f}"
    return f"+{body}" if x > 0 else f"{MINUS}{body}" if x < 0 else body


def _pct(v, digits: int = 2) -> str:
    return "tidak tersedia" if v is None else f"{_signed(v, digits)}%"


def _px(v) -> str:
    """Price, exchange style: 2,000.00 / 1.50 / 0.00001234."""
    if v is None:
        return "tidak tersedia"
    x = float(v)
    if abs(x) >= 1000:
        return f"{x:,.2f}"
    s = (f"{x:,.4f}" if abs(x) >= 1 else f"{x:.8f}").rstrip("0")
    whole, _, frac = s.partition(".")
    return f"{whole}.{frac.ljust(2, '0')}"


def _signal_type(t: str) -> str:
    if t in SIGNAL_TYPE_LABEL:
        return SIGNAL_TYPE_LABEL[t]
    m = re.match(r"^(.*)_(\d+[mhdw])$", t or "")            # lab watch: "<template>_<tf>"
    if m:
        return f"{_strategy(m.group(1))} {_tf(m.group(2))}"
    return _strategy(t)


def _exit(reason: Optional[str]) -> Optional[str]:
    if not reason:
        return None
    if reason in EXIT_LABEL:
        return EXIT_LABEL[reason]
    if reason.startswith("strategy_exit"):
        why = reason.partition(":")[2]
        return "strategi keluar (tidak lagi berposisi)" if why in ("", "flat") else f"strategi keluar ({why})"
    return reason


def _wib(iso_ts: str) -> tuple[datetime, str]:
    dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00")).astimezone(WIB)
    return dt, f"{dt.day} {MONTHS[dt.month - 1]} {dt:%H:%M} WIB"


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
    what = f"{_coin(r['symbol'])} {_tf(r['timeframe'])} · {_strategy(r['template_id'])}"
    if status == "error":
        err = (job.get("error") or r["error"] or "").strip().splitlines()
        detail = (err[-1] if err else "").strip()[:300]
        return notify(conn, "job", f"{label} #{r['id']} gagal dijalankan · {what}",
                      f"Detail teknis: {detail}" if detail else None, f"/lab/runs/{r['id']}", f"job:{job['id']}:error")
    bits = []
    if r["verdict"]:
        bits.append(RUN_VERDICT_LABEL.get(r["verdict"], r["verdict"]))
    elif r["mode"] == "backtest":
        bits.append("tanpa rapor")
    if r["net_return_pct"] is not None:
        bits.append(f"hasil bersih {_pct(r['net_return_pct'])}")
    if r["max_dd_pct"] is not None:
        bits.append(f"turun terdalam {_pct(-abs(r['max_dd_pct']))}")
    if r["trades"] is not None:
        bits.append(f"{r['trades']:,} trade")
    return notify(conn, "job", f"{label} #{r['id']} selesai · {what}", " · ".join(bits) or None,
                  f"/lab/runs/{r['id']}", f"job:{job['id']}:done")


def _scan_finished(conn, scan_id: int) -> Optional[int]:
    left = conn.execute("SELECT COUNT(*) FROM lab_runs WHERE scan_id=? AND status NOT IN ('done','error','cancelled')",
                        (scan_id,)).fetchone()[0]
    if left:
        return None
    s = conn.execute("SELECT template_id, mode FROM lab_scans WHERE id=?", (scan_id,)).fetchone()
    c = conn.execute("SELECT COUNT(*) AS n, SUM(status='done') AS done, SUM(status='error') AS err, "
                     "SUM(status='cancelled') AS canc, SUM(verdict='PASS') AS pass, SUM(verdict='FAIL') AS fail "
                     "FROM lab_runs WHERE scan_id=?", (scan_id,)).fetchone()
    body = f"{c['done'] or 0} dari {c['n']} kombinasi koin × timeframe selesai"
    if s and s["mode"] != "backtest":
        body += f" · {c['pass'] or 0} lolos · {c['fail'] or 0} gagal"
    if c["err"]:
        body += f" · {c['err']} error"
    if c["canc"]:
        body += f" · {c['canc']} dibatalkan"
    tpl = f" · {_strategy(s['template_id'])}" if s else ""
    return notify(conn, "job", f"Uji banyak koin #{scan_id} selesai{tpl}", body, f"/lab/scan?id={scan_id}",
                  f"scan:{scan_id}:finished")


# ── paper presets ─────────────────────────────────────────────────────────

def _preset_of(conn, watch_id: int) -> Optional[dict]:
    have = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN "
                        "('lab_presets','lab_preset_links')").fetchone()[0]
    if have < 2:
        return None
    r = conn.execute("SELECT p.id, p.name FROM lab_preset_links l JOIN lab_presets p ON p.id = l.preset_id "
                     "WHERE l.kind='watch' AND l.ref_id=?", (watch_id,)).fetchone()
    return {"id": r["id"], "name": r["name"]} if r else None


@_safe
def paper_position(conn, pos: dict, event: str) -> Optional[int]:
    """event = open | close. Only automatic positions of a watch (the preset paper mirrors);
    manual paper orders are the admin's own action and Universal has its own rebalance log."""
    if not pos or pos.get("source") != "paper_auto" or pos.get("watch_id") is None:
        return None
    preset = _preset_of(conn, int(pos["watch_id"]))
    name = preset["name"] if preset else f"pantau #{pos['watch_id']}"
    side = (pos.get("side") or "").upper()
    coin = _coin(pos.get("symbol") or "")
    if event == "open":
        body = f"Masuk di {_px(pos.get('entry_price'))} · batal jika (SL) {_px(pos.get('sl'))}" + (
            f" · target (TP) {_px(pos.get('tp'))}" if pos.get("tp") else "") + f" · {PAPER_NOTE}"
        link = f"/lab/arena?highlight={preset['id']}" if preset else "/lab/arena"
        return notify(conn, "paper", f"Paper {name}: buka {side} {coin}", body, link, f"paper:{pos['id']}:open")
    pnl = pos.get("pnl")
    r_mult = (pnl / pos["risk_amount"]) if pnl is not None and pos.get("risk_amount") else None
    result = "hasil bersih tidak tersedia" if pnl is None else f"hasil bersih {_signed(pnl)} USDT" + (
        f" ({_signed(r_mult)}R)" if r_mult is not None else "")
    reason = _exit(pos.get("exit_reason"))
    body = f"Keluar di {_px(pos.get('exit_price'))} · {result}" + (f" · {reason}" if reason else "") + \
        f" · {PAPER_NOTE}"
    link = f"/journal?account_id={pos['account_id']}" if pos.get("account_id") is not None else "/journal"
    return notify(conn, "paper", f"Paper {name}: tutup {side} {coin}", body, link, f"paper:{pos['id']}:close")


# ── Signal Ledger (Rekam jejak sinyal) ────────────────────────────────────

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
        src = SIGNAL_SOURCE_LABEL.get(v["source"], v["source"])
        return f"{_signal_type(v['signal_type'])} {'long' if v['direction'] > 0 else 'short'} ({src})"

    def was(old) -> str:
        return VERDICT_LABEL.get(old, old) if old else "baru"

    def stamp(k, old, v) -> str:
        return hashlib.sha1(f"{k}|{old}|{v['verdict']}|{v['n']}".encode()).hexdigest()[:16]

    ids = []
    if len(changes) <= 3:
        for k, old, v in changes:
            body = (f"{was(old)} → {VERDICT_LABEL[v['verdict']]} · {v['n']:,} sinyal dinilai di {v['days']} hari "
                    f"· rata-rata gerak searah sinyal setelah 1 hari {_pct(v['mean_pct'])}")
            i = notify(conn, "ledger", f"Rekam jejak sinyal: {name(v)} kini {VERDICT_LABEL[v['verdict']]}", body,
                       f"/lab/signals?type={v['signal_type']}", f"ledger:{stamp(k, old, v)}")
            if i:
                ids.append(i)
        return ids
    body = "; ".join(f"{name(v)}: {was(old)} → {VERDICT_LABEL[v['verdict']]}"
                     for _, old, v in changes[:8]) + (f"; dan {len(changes) - 8} lagi" if len(changes) > 8 else "")
    key = hashlib.sha1("|".join(stamp(*c) for c in changes).encode()).hexdigest()[:16]
    i = notify(conn, "ledger", f"Rekam jejak sinyal: {len(changes)} vonis berubah", body, "/lab/signals",
               f"ledger:multi:{key}")
    return [i] if i else []


# ── weekly report ─────────────────────────────────────────────────────────

@_safe
def report_ready(conn, week: str, start: str, end: str) -> Optional[int]:
    """The worker froze the snapshot of ``week`` ([start, end) in UTC ISO)."""
    a, a_txt = _wib(start)
    b, b_txt = _wib(end)
    span = f"{a.day}–{b.day} {MONTHS[b.month - 1]}" if a.month == b.month else \
        f"{a.day} {MONTHS[a.month - 1]} – {b.day} {MONTHS[b.month - 1]}"
    body = (f"Senin {a_txt} s/d Senin {b_txt} (minggu {week}). "
            "Angkanya sudah dibekukan dan tidak berubah lagi.")
    return notify(conn, "report", f"Laporan mingguan siap: {span}", body, f"/lab/report?week={week}",
                  f"report:{week}")


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
            title = f"Pembaruan sistem: {m.group(1)} terpasang @ {m.group(2)[:7]}"
        else:
            title = "Pembaruan sistem gagal: " + msg.replace("GAGAL:", "").strip()[:100]
        i = notify(conn, "deploy", title, msg[:400], "/lab/report",
                   "deploy:" + hashlib.sha1(raw.encode()).hexdigest()[:20])
        if i:
            ids.append(i)
    return ids

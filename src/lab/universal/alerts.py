"""Telegram outbox for Universal paper signals. Stdlib only.

The engine child only INSERTs rows into lab_alerts. The lab worker's scheduler
(screener venv, has httpx) sends them through the existing BMTM notifier
(src/trading/notifier.py, loaded read-only by file path so the worker does not
import the whole trading package), with:
  * coalescing: only the newest pending alert per ref is sent, older ones are 'superseded'
  * per-ref minimum interval (LAB_TELEGRAM_MIN_INTERVAL_S, default 300 s)
  * global cap per rolling hour (LAB_TELEGRAM_MAX_PER_HOUR, default 12)
  * expiry: pending alerts older than LAB_TELEGRAM_MAX_AGE_S (default 6 h) are dropped
  * kill switch: LAB_TELEGRAM_ENABLED=0
The bot token is never logged or stored in lab.db.
"""
from __future__ import annotations

import asyncio
import importlib.util
import logging
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from ..db import utcnow
from ..settings import REPO_ROOT, LabSettings

log = logging.getLogger("lab.alerts")
_notifier_cls = None


def enqueue(conn, ref: str, text: str, channel: str = "telegram") -> int:
    cur = conn.execute("INSERT INTO lab_alerts (channel, ref, text, status, created_at) VALUES (?, ?, ?, 'pending', ?)",
                       (channel, ref, text[:4000], utcnow()))
    conn.commit()
    return int(cur.lastrowid)


def _load_notifier():
    """TelegramNotifier from src/trading/notifier.py without running src/trading/__init__."""
    global _notifier_cls
    if _notifier_cls is None:
        path = REPO_ROOT / "src" / "trading" / "notifier.py"
        spec = importlib.util.spec_from_file_location("bmtm_lab_tg_notifier", path)
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)
        _notifier_cls = mod.TelegramNotifier
    return _notifier_cls


def default_sender(s: LabSettings) -> Callable[[str], None]:
    notifier = _load_notifier()(s.telegram_bot_token)

    def send(text: str) -> None:
        asyncio.run(notifier.send_alert(s.telegram_chat_id, text))
    return send


def _ts(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def send_pending(conn, s: LabSettings, sender: Optional[Callable[[str], None]] = None,
                 now: Optional[datetime] = None) -> int:
    """Deliver due alerts. Returns how many were sent."""
    now = now or datetime.now(timezone.utc)
    pending = [dict(r) for r in conn.execute(
        "SELECT * FROM lab_alerts WHERE status='pending' AND channel='telegram' ORDER BY id")]
    if not pending:
        return 0
    if not s.telegram_enabled or not s.telegram_bot_token or not s.telegram_chat_id:
        reason = "telegram disabled" if not s.telegram_enabled else "telegram not configured"
        conn.execute("UPDATE lab_alerts SET status='skipped', error=? WHERE status='pending' AND channel='telegram'",
                     (reason,))
        conn.commit()
        return 0
    expire_before = _iso(now - timedelta(seconds=s.telegram_max_age_s))
    conn.execute("UPDATE lab_alerts SET status='expired' WHERE status='pending' AND created_at < ?", (expire_before,))
    newest: dict[str, dict] = {}
    for a in pending:
        if a["created_at"] < expire_before:
            continue
        old = newest.get(a["ref"])
        if old is not None:
            conn.execute("UPDATE lab_alerts SET status='superseded' WHERE id=?", (old["id"],))
        newest[a["ref"]] = a
    conn.commit()
    hour_ago = _iso(now - timedelta(hours=1))
    sent_last_hour = conn.execute("SELECT COUNT(*) FROM lab_alerts WHERE status='sent' AND sent_at >= ?",
                                  (hour_ago,)).fetchone()[0]
    sent = 0
    for ref, a in newest.items():
        if sent_last_hour >= s.telegram_max_per_hour:
            break
        last = conn.execute("SELECT MAX(sent_at) FROM lab_alerts WHERE status='sent' AND ref=?", (ref,)).fetchone()[0]
        if last and _ts(last) > now - timedelta(seconds=s.telegram_min_interval_s):
            continue  # rate-limited: stays pending (a newer alert will supersede it)
        try:
            (sender or default_sender(s))(a["text"])
        except Exception as e:  # noqa: BLE001
            conn.execute("UPDATE lab_alerts SET status='error', error=? WHERE id=?", (f"{type(e).__name__}", a["id"]))
            conn.commit()
            log.warning("telegram alert %s failed: %s", a["id"], type(e).__name__)
            continue
        conn.execute("UPDATE lab_alerts SET status='sent', sent_at=? WHERE id=?", (_iso(now), a["id"]))
        conn.commit()
        sent += 1
        sent_last_hour += 1
    return sent


def fmt_pct(v: float) -> str:
    return f"{v:.1f}%"


def rebalance_text(watch: dict, bar_close: str, targets: list[dict], orders: list[dict],
                   equity: Optional[float], autopaper: bool) -> str:
    """Indonesian, plain text (no markup) for the BMTM group."""
    name = watch.get("name") or f"Universal #{watch['id']}"
    lines = [f"[PAPER] {name} - rebalance", f"Candle close: {bar_close.replace('T', ' ').replace('Z', '')} UTC", ""]
    if targets:
        lines.append("Target portofolio:")
        for t in targets:
            side = "LONG" if t["weight_pct"] > 0 else "SHORT"
            lines.append(f"  {t['symbol']:<14} {side:<5} {fmt_pct(abs(t['weight_pct']))}")
    else:
        lines.append("Target portofolio: KOSONG (tidak ada koin yang lolos filter tren) - semua posisi ditutup.")
    if autopaper:
        lines.append("")
        if orders:
            lines.append("Order paper:")
            for o in orders:
                lines.append(f"  {o['action'].upper():<6} {o['symbol']:<14} {o['side']:<5} "
                             f"qty {o['qty']:.6g} @ {o['price']:.6g}")
        else:
            lines.append("Order paper: tidak ada (perubahan bobot di bawah batas minimum).")
        if equity is not None:
            lines.append(f"Equity paper: {equity:,.2f} USDT")
    lines += ["", "Simulasi (paper trading) - BUKAN order nyata, bukan saran finansial."]
    return "\n".join(lines)

"""Deliveries + expected signals -> one classified row per 4H bar event (pure, stdlib).

Statuses
  cocok           expected and executed (fill within ``price_bps`` of the expected price
                  or no fill price recorded)
  harga_beda      expected and executed, fill differs from the expected price by more
                  than ``price_bps``
  gagal           expected, delivered, not executed (rejected / failed / outcome unknown)
  tidak_terkirim  expected, no delivery seen while the logs covered that time
  tak_terduga     a TradingView delivery the Lab did not expect
  menunggu        too recent to judge (alert or outcome may still arrive)
  tanpa_log       expected, but no log covers that time (cannot be checked)
  diabaikan       a non-TradingView client hit the webhook (manual test), shown for completeness

``perlu_dicek`` marks rows where the Lab may legitimately differ from Pine (causes in
``causes``; see docs/lab/live-check.md), and every ``gagal`` row: a delivered live order
that did not execute leaves the bot away from the strategy (audit 2026-11-13 K1: the
9 Nov ETH short was rejected and nobody was asked to look). Matching is done in passes: same bar, then one
bar off (``beda_bar``), then - for exits only - anywhere within the same trade
(``beda_waktu_exit``), so a timing difference is shown as one paired row instead of a
"missing" plus an "unexpected" row.
"""
from __future__ import annotations

from typing import Iterable, Optional

from .logs import covered

FILLED = {"success", "filled", "ok", "done", "executed"}
FAILED = {"rejected", "failed", "error", "cancelled"}
BAR_CLOSE_GRACE_S = 1800          # an alert this long after a 4H close still counts as "at the close"

STATUS_TEXT = {
    400: "kredensial exchange tidak ada / tidak valid (400)",
    401: "passphrase salah atau webhook tidak aktif (401)",
    403: "ditolak: trading dihentikan atau leverage di atas batas (403)",
    409: "ditolak: duplikat atau posisi sudah ada (409)",
    413: "payload terlalu besar (413)",
    422: "payload tidak valid (422)",
    429: "terkena rate limit (429)",
    499: "TradingView memutus koneksi sebelum server menjawab (>3 dtk, 499)",
    500: "error di server (500)",
    502: "error dari exchange (502)",
    503: "layanan tidak tersedia (503)",
    504: "timeout ke backend (504)",
}


def reason_text(raw: Optional[str]) -> Optional[str]:
    """Known bot rejection messages -> short Indonesian text; anything else passes through."""
    if not raw:
        return None
    r = raw.lower()
    if "already exists on the exchange" in r:
        return ("ditolak: akun sudah punya posisi ETH yang tidak dibuka sinyal ini "
                "(posisi manual, di luar bot)")
    if "not opened by the bot" in r:
        return "close dilewati: posisi di exchange bukan dibuka bot (posisi manual dibiarkan)"
    if "no open position" in r:
        return "close ditolak: tidak ada posisi terbuka di exchange"
    if "but the bot opened" in r:
        return "close dilewati: sisi posisi di exchange beda dengan yang dibuka bot"
    if "trading is halted" in r:
        return "ditolak: trading dihentikan (TRADING_HALT)"
    if "leverage above limit" in r:
        return "ditolak: leverage di atas batas"
    if "-2015" in r or "invalid api-key" in r:
        return "gagal: API key Binance ditolak exchange (-2015)"
    if "duplicate" in r:
        return "ditolak: kiriman duplikat"
    if "lock" in r and "timeout" in r:
        return "ditolak: posisi sedang diproses sinyal lain (lock timeout)"
    return raw


def trade_dir(action: Optional[str], side: Optional[str]) -> Optional[int]:
    """+1 = the order buys (open long / close short), -1 = it sells."""
    a, s = (action or "").lower(), (side or "").lower()
    base = 1 if s == "long" else -1 if s == "short" else 0
    if not base or a not in ("open", "close"):
        return None
    return base if a == "open" else -base


# ── deliveries ───────────────────────────────────────────────────────────────

def build_deliveries(evidence: list[dict], trade_logs: list[dict], symbol: str, nginx_cov: list[list],
                     now: float, pending_s: int = 600) -> list[dict]:
    """Group log facts and trade_logs rows into deliveries (one per webhook request)."""
    ev = sorted(evidence, key=lambda e: e["ts"])
    used: set[int] = set()
    tl_used: set[int] = set()

    def take(kind: Iterable[str], lo: float, hi: float, source: str = "app", nearest: Optional[float] = None,
             many: bool = True) -> list[dict]:
        kinds = set(kind)
        hits = [(i, e) for i, e in enumerate(ev) if i not in used and e["source"] == source
                and e["kind"] in kinds and lo <= e["ts"] <= hi]
        if nearest is not None:
            hits.sort(key=lambda x: abs(x[1]["ts"] - nearest))
        if not many:
            hits = hits[:1]
        for i, _ in hits:
            used.add(i)
        return [e for _, e in hits]

    def take_tl(lo: float, hi: float) -> list[dict]:
        out = []
        for i, r in enumerate(trade_logs):
            if i not in tl_used and lo <= r["ts"] <= hi:
                tl_used.add(i)
                out.append(r)
        return out

    def assemble(anchor_ts: float, base: dict) -> dict:
        d = {"arrival": anchor_ts, "sources": [], "nginx_status": None, "tv": None, "ip": None,
             "app_status": None, "app_ms": None, "orders": [], "fails": [], "dup": False, "symbols": set(),
             "trade_logs": [], **base}
        return d

    FACTS = ["order", "fail", "dup", "timing", "sym"]
    anchors: list[dict] = []
    # 1) nginx hits from non-local clients (nginx logs the END of the request)
    for i, e in enumerate(ev):
        if e["source"] != "nginx" or e["kind"] != "hit" or i in used:
            continue
        used.add(i)
        t = e["ts"]
        d = assemble(t, {"nginx_status": e["data"].get("status"), "tv": bool(e["data"].get("tv")),
                         "ip": e["data"].get("ip"), "ua": e["data"].get("ua")})
        d["sources"].append("nginx")
        done = take(["done"], t - 3, t + 40, nearest=t, many=False)
        if done:
            d["app_status"], d["app_ms"] = done[0]["data"].get("status"), done[0]["data"].get("ms")
            d["arrival"] = min(t, done[0]["ts"] - (done[0]["data"].get("ms") or 0) / 1000.0)
            d["sources"].append("app")
        anchors.append(d)
    # 2) app-log requests at times nginx has no record of (older periods; client IP unknown)
    for i, e in enumerate(ev):
        if e["source"] != "app" or e["kind"] != "done" or i in used or covered(e["ts"], nginx_cov, 60):
            continue
        used.add(i)
        d = assemble(e["ts"] - (e["data"].get("ms") or 0) / 1000.0,
                     {"app_status": e["data"].get("status"), "app_ms": e["data"].get("ms")})
        d["sources"].append("app")
        anchors.append(d)
    # facts and trade_logs rows belong to the request they follow, never past the next request
    anchors.sort(key=lambda d: d["arrival"])
    for k, d in enumerate(anchors):
        lo = d["arrival"] - 2
        hi = d["arrival"] + 180
        if k + 1 < len(anchors):
            hi = min(hi, anchors[k + 1]["arrival"] - 0.5)
        _attach_app(d, take(FACTS, lo, hi))
        _attach_tl(d, take_tl(lo, hi))
    deliveries: list[dict] = list(anchors)
    # 3) trade_logs rows without a request line (log rotated away / local request)
    for i, r in enumerate(trade_logs):
        if i in tl_used:
            continue
        tl_used.add(i)
        d = assemble(r["ts"], {})
        _attach_tl(d, [r] + take_tl(r["ts"], r["ts"] + 30))
        _attach_app(d, take(FACTS, r["ts"] - 90, r["ts"] + 5))
        deliveries.append(d)
    # 4) orders / failures in the app log with no request line at all
    for i, e in enumerate(ev):
        if e["source"] != "app" or e["kind"] not in ("order", "fail") or i in used:
            continue
        if covered(e["ts"], nginx_cov, 60):
            continue
        used.add(i)
        d = assemble(e["ts"], {})
        _attach_app(d, [e] + take(FACTS, e["ts"] - 5, e["ts"] + 30))
        deliveries.append(d)

    out = []
    for d in deliveries:
        syms = {s for s in d.pop("symbols") if s}
        if syms and symbol not in syms:
            continue                      # another coin's alert (e.g. BTC tests in October)
        _outcome(d, now, pending_s)
        out.append(d)
    out.sort(key=lambda d: d["arrival"])
    return out


def _norm(sym: Optional[str]) -> Optional[str]:
    if not sym:
        return None
    s = str(sym).upper().split(":")[0].replace("/", "")
    return s[:-2] if s.endswith(".P") else s


def _attach_app(d: dict, facts: list[dict]) -> None:
    for f in facts:
        if "app" not in d["sources"]:
            d["sources"].append("app")
        data = f["data"]
        d["symbols"].add(_norm(data.get("symbol")))
        if f["kind"] == "order":
            d["orders"].append(data.get("trade_dir"))
        elif f["kind"] == "fail":
            d["fails"].append(data.get("reason"))
        elif f["kind"] == "dup":
            d["dup"] = True
        elif f["kind"] == "timing":
            d["timing"] = True


def _attach_tl(d: dict, rows: list[dict]) -> None:
    for r in rows:
        if "trade_logs" not in d["sources"]:
            d["sources"].append("trade_logs")
        d["trade_logs"].append({k: r.get(k) for k in ("ts", "action", "side", "status", "fill_price", "fill_qty",
                                                      "reason")})


def _outcome(d: dict, now: float, pending_s: int) -> None:
    tls = d["trade_logs"]
    d["action"] = next((r["action"] for r in tls if r.get("action")), None)
    d["side"] = next((r["side"] for r in tls if r.get("side")), None)
    dirs = [x for x in d["orders"] if x] or ([trade_dir(d["action"], d["side"])] if d["action"] else [])
    d["trade_dir"] = dirs[0] if dirs and dirs[0] else None
    fills = [(r["fill_price"], r.get("fill_qty") or 1.0) for r in tls
             if r.get("fill_price") and r.get("status") in FILLED]
    qty = sum(q for _, q in fills)
    d["fill_price"] = sum(p * q for p, q in fills) / qty if qty else None
    executed = bool(d["orders"]) or bool(d.get("timing")) or any(r.get("status") in FILLED for r in tls)
    status = d["app_status"] or d["nginx_status"]
    reason = None
    if not executed:
        raw = next((r["reason"] for r in tls if r.get("status") in FAILED and r.get("reason")), None) \
            or next((x for x in d["fails"] if x), None)
        reason = reason_text(raw)
        if reason is None and d["dup"]:
            reason = "ditolak: kiriman duplikat"
        if reason is None and status is not None and status not in (200, 202):
            reason = STATUS_TEXT.get(status, f"respons HTTP {status}")
            if status == 499 and d["app_status"] is None:
                reason += "; tidak ada catatan di log aplikasi / trade_logs, hasil tidak diketahui"
    d["executed"] = executed
    d["pending"] = (not executed and reason is None and now - d["arrival"] < pending_s)
    if not executed and reason is None and not d["pending"]:
        reason = ("diterima (202) tapi tidak ada catatan eksekusi" if status == 202
                  else "tidak ada catatan eksekusi")
    d["reason"] = reason
    note = None
    if executed and status is not None and status >= 400:
        note = f"order tereksekusi walau respons HTTP {status}"
        if status == 500:
            note += " (bug log audit lama, diperbaiki 2026-11-06)"
    d["note"] = note


# ── matching ─────────────────────────────────────────────────────────────────

def merge_variants(variants: dict[str, list[dict]]) -> tuple[list[dict], list[dict]]:
    """(primary events with ``variants`` + ``causes``, alternative-only events)."""
    names = list(variants)
    by_key: dict[str, dict] = {}
    for name in names:
        for e in variants[name]:
            x = by_key.setdefault(e["key"], {**e, "variants": []})
            x["variants"].append(name)
    primary, alt = [], []
    for e in by_key.values():
        causes = []
        if "utama" in e["variants"]:
            if "pendek" in names and "pendek" not in e["variants"]:
                causes.append("warmup")
            if "biaya" in names and "biaya" not in e["variants"]:
                causes.append("biaya")
            if e["alert"] == "intrabar":
                causes.append("intrabar")
            primary.append({**e, "causes": causes})
        else:
            alt.append(e)
    primary.sort(key=lambda e: (e["bar_open"], 0 if e["action"] == "close" else 1))
    alt.sort(key=lambda e: e["bar_open"])
    return primary, alt


def _compatible(e: dict, d: dict, need_known: bool = False) -> bool:
    if d.get("action") and d.get("side"):
        return d["action"] == e["action"] and d["side"] == e["side"]
    if d.get("trade_dir"):
        return d["trade_dir"] == trade_dir(e["action"], e["side"])
    return not need_known


def _alert_at(e: dict, step: int) -> float:
    return e["bar_open"] + (step if e["alert"] == "close" else step / 2)


def _window(e: dict, step: int, extra: float) -> tuple[float, float]:
    if e["alert"] == "close":
        t = e["bar_open"] + step
        return t - 120 - extra, t + BAR_CLOSE_GRACE_S + extra
    return e["bar_open"] - 60 - extra, e["bar_open"] + step + BAR_CLOSE_GRACE_S + extra


def delivery_bar(t: float, step: int) -> float:
    """Open time of the 4H bar a delivery belongs to: right after a close -> the bar that
    just closed; mid-bar -> the bar it arrived in."""
    boundary = t - t % step
    return boundary - step if t - boundary <= BAR_CLOSE_GRACE_S else boundary


def match(primary: list[dict], alt: list[dict], deliveries: list[dict], *, step: int, coverage: list[list],
          now: float, data_last_bar: Optional[float], price_bps: float) -> list[dict]:
    pairs: dict[int, tuple[int, list[str], Optional[str]]] = {}     # event idx -> (delivery idx, causes, note)
    taken: set[int] = set()

    def best(e: dict, lo: float, hi: float, need_known: bool = False) -> Optional[int]:
        target = _alert_at(e, step)
        cands = [(abs(d["arrival"] - target), j) for j, d in enumerate(deliveries)
                 if j not in taken and lo <= d["arrival"] <= hi and d.get("tv") is not False
                 and _compatible(e, d, need_known)]
        if not cands:
            return None
        # prefer: direction known to fit > unknown; for bar-close signals a delivery that came
        # right after a 4H close > one mid-bar (manual tests); then the nearest
        def mid_bar(j: int) -> int:
            t = deliveries[j]["arrival"]
            return int(e["alert"] == "close" and t - (t - t % step) > BAR_CLOSE_GRACE_S)
        cands.sort(key=lambda c: (0 if deliveries[c[1]].get("trade_dir") else 1, mid_bar(c[1]), c[0]))
        return cands[0][1]

    for i, e in enumerate(primary):                                   # pass 1: same bar
        j = best(e, *_window(e, step, 0))
        if j is not None:
            pairs[i] = (j, [], None)
            taken.add(j)
    for i, e in enumerate(primary):                                   # pass 2: one bar off
        if i in pairs:
            continue
        j = best(e, *_window(e, step, step))
        if j is not None:
            diff = (deliveries[j]["arrival"] - _alert_at(e, step)) / 3600.0
            pairs[i] = (j, ["beda_bar"], f"terkirim {diff:+.1f} jam dari waktu sinyal Lab")
            taken.add(j)
    for i, e in enumerate(primary):                                   # pass 3: exit anywhere in the trade
        if i in pairs or e["action"] != "close":
            continue
        opens = [x for x in primary if x["action"] == "open" and x["side"] == e["side"] and x["bar_open"] <= e["bar_open"]]
        nxt = [x for x in primary if x["action"] == "open" and x["bar_open"] > e["bar_open"]]
        lo = (opens[-1]["bar_open"] + step + 60) if opens else e["bar_open"] - 6 * step
        hi = (nxt[0]["bar_open"] + step - 60) if nxt else now
        j = best(e, lo, hi, need_known=True)
        if j is not None:
            diff = (deliveries[j]["arrival"] - _alert_at(e, step)) / 3600.0
            pairs[i] = (j, ["beda_waktu_exit"], f"exit live {diff:+.1f} jam dari exit Lab (posisi yang sama)")
            taken.add(j)

    rows: list[dict] = []
    for i, e in enumerate(primary):
        exp = _exp_json(e, step)
        if i in pairs:
            j, extra, note = pairs[i]
            d = deliveries[j]
            causes = e["causes"] + extra
            rows.append(_paired_row(e, d, causes, note, exp, price_bps))
            continue
        alert_t = _alert_at(e, step)
        if alert_t > now - BAR_CLOSE_GRACE_S:
            status, reason = "menunggu", "sinyal baru; kiriman mungkin masih diproses"
        elif covered(alert_t, coverage, 600):
            status, reason = "tidak_terkirim", "tidak ada kiriman TradingView untuk sinyal ini"
        else:
            status, reason = "tanpa_log", "tidak ada log yang mencakup waktu ini; tidak bisa dicek"
        rows.append(_row(e["bar_open"], step, status, bool(e["causes"]) and status == "tidak_terkirim",
                         e["causes"], e["action"], e["side"], reason, None, exp, None))
    for j, d in enumerate(deliveries):
        if j in taken:
            continue
        bar = delivery_bar(d["arrival"], step)
        dj = _dlv_json(d)
        if d.get("tv") is False:
            rows.append(_row(bar, step, "diabaikan", False, [], d.get("action"), d.get("side"),
                             f"bukan dari TradingView (klien {d.get('ua') or '?'}); kemungkinan uji manual",
                             None, None, dj))
            continue
        causes, hints = [], []
        for a in alt:
            if abs(a["bar_open"] - bar) <= step and _compatible(a, d):
                causes.append("varian_lain")
                hints.append(f"varian Lab '{'/'.join(a['variants'])}' punya sinyal {a['action']} {a['side']} "
                             f"di bar ini")
                break
        if data_last_bar is not None and bar > data_last_bar:
            causes.append("data_belum")
            hints.append("data Lab belum sampai bar ini")
        if d["arrival"] - (d["arrival"] - d["arrival"] % step) > BAR_CLOSE_GRACE_S:
            causes.append("tengah_bar")
            hints.append("tiba di tengah bar (SL/TP intrabar Pine, atau alert manual)")
        what = "tereksekusi" if d["executed"] else (d["reason"] or "tidak tereksekusi")
        rows.append(_row(bar, step, "tak_terduga", True, causes, d.get("action"), d.get("side"),
                         "kiriman tanpa sinyal Lab: " + what + ("; " + "; ".join(hints) if hints else ""),
                         None, None, dj))
    rows.sort(key=lambda r: (r["bar_open"], r["action"] or ""))
    return rows


def _paired_row(e: dict, d: dict, causes: list[str], note: Optional[str], exp: dict, price_bps: float) -> dict:
    dj = _dlv_json(d)
    bps = None
    if d["executed"]:
        if d.get("fill_price") and e.get("price"):
            sign = trade_dir(e["action"], e["side"]) or 1
            bps = sign * (d["fill_price"] - e["price"]) / e["price"] * 1e4
        if bps is not None and abs(bps) > price_bps:
            status = "harga_beda"
            reason = f"fill {d['fill_price']:.2f} vs harga Lab {e['price']:.2f} ({bps:+.0f} bps)"
        else:
            status = "cocok"
            reason = "tereksekusi" + ("" if d.get("fill_price") else " (harga fill tidak tercatat)")
    elif d["pending"]:
        status, reason = "menunggu", "kiriman diterima, hasil eksekusi belum tercatat"
    else:
        status, reason = "gagal", d["reason"] or "tidak tereksekusi"
    if d.get("note"):
        reason += f"; {d['note']}"
    if note:
        reason += f"; {note}"
    perlu = bool(causes) or status == "gagal"     # rejected / failed / outcome unknown: always ask someone
    return _row(e["bar_open"], exp["step"], status, perlu, causes, e["action"], e["side"], reason, bps, exp, dj)


def _row(bar_open: float, step: int, status: str, perlu: bool, causes: list[str], action, side, reason,
         bps, exp, dlv) -> dict:
    return {"bar_open": bar_open, "bar_close": bar_open + step, "status": status, "perlu_dicek": bool(perlu),
            "causes": causes, "action": action, "side": side, "reason": reason, "price_diff_bps": bps,
            "expected": exp, "delivery": dlv}


def _exp_json(e: dict, step: int) -> dict:
    return {"action": e["action"], "side": e["side"], "alert": e["alert"], "alert_at": _alert_at(e, step)
            if e["alert"] == "close" else None, "price": e.get("price"), "exit_reason": e.get("reason"),
            "variants": e.get("variants"), "step": step}


DLV_KEYS = ("arrival", "sources", "nginx_status", "tv", "ip", "app_status", "app_ms", "action", "side",
            "trade_dir", "executed", "pending", "fill_price", "reason", "note", "dup")
TL_KEYS = ("ts", "action", "side", "status", "fill_price", "reason")


def _dlv_json(d: dict) -> dict:
    out = {k: d.get(k) for k in DLV_KEYS}
    out["trade_logs"] = [{k: r.get(k) for k in TL_KEYS} for r in d.get("trade_logs", [])]
    return out

#!/usr/bin/env python3
"""Seed the pre-registered basket paper strategies into the Strategy Lab (idempotent).

Reads ``lab_baskets_seed.json`` (next to this file). For every basket:
  1. checks   the entry equals the pre-registration (docs/research/basket/prereg-basket-2026-11-12.json):
              name, template, timeframe, full params, coins, sizing and account. Any difference refuses.
  2. data     every coin has >= 1300 closed 4h bars in the Lab perp cache (prereg coin rule 3); the
              cache is only READ here (never fetched). Missing data refuses --apply.
  3. capacity the new watches fit under LAB_WATCH_MAX_ACTIVE.
  4. basket   one paper account "Paper <name>" (simulated money only), the basket row, one auto-paper
              watch per coin through the API's watch insert (same validation and initial job as
              POST /api/v1/lab/watches) and the member links, in ONE transaction. A basket whose
              name exists is left untouched ("exists").

Paper only: no exchange keys, no orders, nothing under src/trading. Lab watches never send
Telegram; this script also forces LAB_TELEGRAM_ENABLED=0 for its own process and never edits .env.

Dry-run by default; pass --apply to write.

    /root/crypto-screener/.venv/bin/python ops/lab_seed_baskets.py --repo /root/crypto-screener          # plan
    /root/crypto-screener/.venv/bin/python ops/lab_seed_baskets.py --repo /root/crypto-screener --apply  # write
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MIN_BARS = 1300            # prereg coin rule 3: 1000-bar watch window + 300 warm-up
PREREG_REL = "docs/research/basket/prereg-basket-2026-11-12.json"
KEYS = ("name", "label", "template_id", "timeframe", "params", "costs", "symbols", "sizing", "account")


def _args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--repo", default=str(HERE.parent), help="crypto-screener checkout whose src/ to use")
    ap.add_argument("--manifest", default=str(HERE / "lab_baskets_seed.json"))
    ap.add_argument("--db", default=None, help="lab.db path (default: LAB_DB_PATH from the repo .env)")
    ap.add_argument("--data-dir", default=None, help="perp cache dir (default: LAB_DATA_DIR from the repo .env)")
    ap.add_argument("--only", default="", help="comma list of basket names (default: all in the manifest)")
    ap.add_argument("--apply", action="store_true", help="write (default: dry-run)")
    return ap.parse_args(argv)


def prereg_diff(entry: dict, prereg: dict) -> list[str]:
    """Fields where the manifest entry differs from the pre-registered basket of the same name."""
    ref = next((b for b in prereg.get("baskets", []) if b.get("name") == entry.get("name")), None)
    if ref is None:
        return ["name not in the pre-registration"]
    return [k for k in KEYS if entry.get(k) != ref.get(k)]


def data_report(symbols: list[str], tf: str, cached: dict) -> dict:
    """{ok: [...], short: {sym: rows}, missing: [...]} from the cache index (read-only)."""
    out: dict = {"ok": [], "short": {}, "missing": []}
    for s in symbols:
        v = cached.get(f"{s}_{tf}")
        rows = (v or {}).get("rows")
        if v is None:
            out["missing"].append(s)
        elif rows is not None and rows < MIN_BARS:
            out["short"][s] = rows
        else:
            out["ok"].append(s)
    return out


def main(argv=None) -> int:
    a = _args(argv)
    os.environ["LAB_TELEGRAM_ENABLED"] = "0"
    if a.db:
        os.environ["LAB_DB_PATH"] = a.db
    if a.data_dir:
        os.environ["LAB_DATA_DIR"] = a.data_dir
    repo = Path(a.repo).resolve()
    sys.path.insert(0, str(repo))
    from src.api import lab_routes
    from src.lab import db as labdb
    from src.lab.basket import store
    from src.lab.data_cache import cached_datasets
    from src.lab.settings import get_lab_settings
    from src.lab.templates import get_template
    from fastapi import HTTPException

    s = get_lab_settings()
    manifest = json.loads(Path(a.manifest).read_text())
    prereg_path = repo / PREREG_REL
    prereg = json.loads(prereg_path.read_text()) if prereg_path.exists() else None
    only = {x.strip() for x in a.only.split(",") if x.strip()}
    entries = [e for e in manifest["baskets"] if not only or e["name"] in only]
    if only - {e["name"] for e in entries}:
        print(f"unknown names in --only: {sorted(only - {e['name'] for e in entries})}", file=sys.stderr)
        return 2
    print(f"lab.db: {s.db_path}  data: {s.data_dir}  mode: {'APPLY' if a.apply else 'dry-run'}  "
          f"lab telegram enabled: {s.telegram_enabled} (watches never alert)")
    conn = labdb.connect()
    cached = cached_datasets()
    n_active = conn.execute("SELECT COUNT(*) FROM watches WHERE active=1").fetchone()[0]
    report, rc = [], 0
    for e in entries:
        name, row = e["name"], {"name": e["name"]}
        # ── 1. pre-registration ──
        if prereg is None:
            row["prereg"], rc = f"MISSING {PREREG_REL}", 1
            report.append(row)
            continue
        diff = prereg_diff(e, prereg)
        if diff:
            row["prereg"], rc = f"DIFFERS from the pre-registration: {diff}", 1
            report.append(row)
            continue
        row["prereg"] = f"matches {prereg.get('id')}"
        t = get_template(e["template_id"])
        if t is None:
            raise SystemExit(f"{name}: unknown template {e['template_id']}")
        try:
            params = lab_routes._validate(t, e["timeframe"], e["params"])
        except HTTPException as ex:
            raise SystemExit(f"{name}: {ex.detail}")
        if params != e["params"]:
            row["params"], rc = "manifest params are not the full validated set", 1
            report.append(row)
            continue
        if hasattr(t, "is_mtf") and t.is_mtf(params):
            raise SystemExit(f"{name}: MTF entry cannot be watched live")
        # ── 2. data (read-only) ──
        d = data_report(e["symbols"], e["timeframe"], cached)
        row["data"] = {"ok": len(d["ok"]), "short": d["short"], "missing": d["missing"]}
        # ── 3. existing basket / capacity ──
        b = store.by_name(conn, name)
        if b is not None:
            mem = store.members(conn, b["id"])
            row.update(basket="exists", basket_id=b["id"], account_id=b["account_id"], watches=len(mem),
                       active=b["active"], expect="set" if b.get("expect") else "not set")
            report.append(row)
            continue
        need = len(e["symbols"])
        row["capacity"] = f"{n_active} active + {need} new <= {s.watch_max_active}"
        if n_active + need > s.watch_max_active:
            row["basket"], rc = f"REFUSED: active watch cap {s.watch_max_active} would be exceeded", 1
            report.append(row)
            continue
        if d["missing"] or d["short"]:
            row["basket"], rc = "REFUSED: coins without enough 4h data (prefetch first)", 1
            report.append(row)
            continue
        row.update(account=f"Paper {name}", balance=e["account"]["starting_balance"],
                   sizing=e["sizing"]["mode"], expect="set" if e.get("expect") else "NOT SET")
        if not a.apply:
            row["basket"] = f"would create ({need} watches, auto-paper on)"
            report.append(row)
            n_active += need
            continue
        spec = {**{k: e[k] for k in KEYS}, "title": e.get("title"), "notes": e.get("notes"),
                "expect": e.get("expect"),
                "prereg": {"id": prereg.get("id"), "doc": prereg.get("doc"), "json": PREREG_REL,
                           "commit": manifest.get("prereg", {}).get("commit")}}
        try:
            out = store.create(conn, spec, insert_watch=lab_routes._insert_watch)
        except HTTPException as ex:
            row["basket"], rc = f"ERROR {ex.status_code}: {ex.detail} (nothing written)", 1
        except store.BasketError as ex:
            row["basket"], rc = f"ERROR {ex.status}: {ex} (nothing written)", 1
        else:
            mem = store.members(conn, out["id"])
            row.update(basket="created", basket_id=out["id"], account_id=out["account_id"], watches=len(mem),
                       start=out["created_at"])
            n_active += need
        report.append(row)
    conn.close()
    for row in report:
        print(json.dumps(row, ensure_ascii=False))
    if not a.apply:
        print("dry-run only: nothing written. Re-run with --apply.")
    return rc


if __name__ == "__main__":
    sys.exit(main())

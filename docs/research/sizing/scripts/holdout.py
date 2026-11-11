"""ONE holdout evaluation per pre-registered rule x preset through the normal Lab pipeline
(validate mode) on the /tmp lab.db copy. Run with the screener venv:

    nice -n 10 /root/crypto-screener/.venv/bin/python holdout.py ../prereg.json

Holdout locks are pinned to the starts every earlier look used, before any run.
"""
import json
import os
import sys

EXP = os.environ.get("SIZING_EXP", "/tmp/sizing/exp")
os.environ.update({"LAB_ENGINE_PATH": "/tmp/sizing/engine", "LAB_ENGINE_PYTHON": "/root/bmtm-v2/venv/bin/python",
                   "LAB_DATA_DIR": f"{EXP}/data", "LAB_DB_PATH": f"{EXP}/lab.db", "LAB_ARTIFACTS_DIR": f"{EXP}/artifacts",
                   "LAB_DATA_OFFLINE": "1", "LAB_TELEGRAM_ENABLED": "0", "LAB_MAX_CONCURRENT_JOBS": "3",
                   "LAB_FAST_LANE": "0", "LAB_STRENGTH_REFRESH": "0", "LAB_JOB_NICE": "10", "LAB_LEDGER_ENABLED": "0",
                   "PYTHONDONTWRITEBYTECODE": "1"})
sys.dont_write_bytecode = True
sys.path.insert(0, "/tmp/sizing/crypto-screener")
from src.api.lab_routes import _run_detail, _snooping, _validate, create_run  # noqa: E402
from src.lab import db as labdb  # noqa: E402
from src.lab.settings import get_lab_settings  # noqa: E402
from src.lab.templates import rosyade_family as T  # noqa: E402
from src.lab.worker import Worker  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
pre = json.load(open(sys.argv[1]))
man = {e["name"]: e for e in json.load(open("/tmp/sizing/crypto-screener/ops/lab_presets_seed.json"))["presets"]}
SYM = {"4H-ETH-Basic": "ETHUSDT", "4H-ETH-v2": "ETHUSDT", "4H-BTC-Opt": "BTCUSDT", "4H-SOL-Opt": "SOLUSDT"}
conn = labdb.connect()
conn.execute("UPDATE lab_jobs SET status='cancelled' WHERE status='queued'")  # this COPY only runs our jobs
for sym, hs in pre["holdout_starts"].items():
    lock = conn.execute("SELECT holdout_start FROM holdout_locks WHERE template_id='rosyade_family' AND symbol=? "
                        "AND timeframe='4h'", (sym,)).fetchone()
    if lock is None:
        conn.execute("INSERT INTO holdout_locks (template_id, symbol, timeframe, holdout_start, touches, created_at) "
                     "VALUES ('rosyade_family', ?, '4h', ?, 0, ?)", (sym, hs, labdb.utcnow()))
    elif lock["holdout_start"] != hs:
        raise SystemExit(f"unexpected {sym} 4h lock {lock['holdout_start']}")
conn.commit()
ids = {}
for rkey in ("R1_fixed_1x", "R2_vol_target_60"):
    over = pre["rules"][rkey]["params_override"]
    for name, sym in SYM.items():
        e = man[name]
        base = T.defaults() if e.get("live_reference") else e["params"]
        params = _validate(T, "4h", {**base, **over})
        rid, _ = create_run(conn, template_id="rosyade_family", symbol=sym, timeframe="4h", mode="validate",
                            params=params, costs=pre["costs"], start="2020-01-01", end="2026-11-09")
        ids[f"{name} | {rkey}"] = rid
conn.commit()
print("runs", ids, flush=True)
Worker(get_lab_settings()).run_until_idle(timeout_s=4 * 3600)
out = {}
for key, rid in ids.items():
    r = conn.execute("SELECT * FROM lab_runs WHERE id=?", (rid,)).fetchone()
    d = _run_detail(r)
    o, m = d.get("oos_metrics") or {}, d.get("metrics") or {}
    out[key] = {"run_id_tmp_db": rid, "status": r["status"], "verdict": d.get("verdict"),
                "holdout_start": d.get("holdout_start"), "holdout_touches_after_run": r["holdout_touches"],
                "snooping": _snooping(conn, r),
                "failed_checks": [c["name"] for c in (d.get("checks") or []) if not c["passed"]],
                "checks": d.get("checks"), "holdout": o, "monte_carlo": m.get("monte_carlo"),
                "sensitivity": m.get("sensitivity"), "dev_in_sample": {k: m.get(k) for k in (
                    "net_return_pct", "profit_factor", "max_dd_pct", "sharpe", "trades")},
                "full_range": m.get("full_range"), "error": d.get("error")}
    print(key, r["status"], d.get("verdict"), "net", o.get("net_return_pct"), "pf", o.get("profit_factor"),
          "dd", o.get("max_dd_pct"), "sh", o.get("sharpe"), "n", o.get("trades"), "2x", o.get("stress_net_return_pct"),
          "mc", (m.get("monte_carlo") or {}).get("dd_p95"), "fail", out[key]["failed_checks"],
          "err", (d.get("error") or "")[:200], flush=True)
json.dump({"note": "ONE validate run per pre-registered rule x preset (prereg.json), normal Lab pipeline on a /tmp "
                   "copy of production lab.db; engine feat/sizing-research (a259ceb + sizing modes). The 4h holdouts "
                   "were viewed several times before (contaminated): weak evidence.", "results": out},
          open(f"{EXP}/out/holdout_results.json", "w"), indent=1, default=str)

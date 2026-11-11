"""ONE holdout evaluation per pre-registered config, through the normal Lab pipeline
(validate mode) on the /tmp lab.db copy. Run with the screener venv."""
import json, os, sys
EXP = os.environ.get("MTF_EXP", "/tmp/mtf/exp")
os.environ.update({"LAB_ENGINE_PATH": "/tmp/mtf/Automate_Execution", "LAB_ENGINE_PYTHON": "/root/bmtm-v2/venv/bin/python",
                   "LAB_DATA_DIR": f"{EXP}/data", "LAB_DB_PATH": f"{EXP}/lab.db", "LAB_ARTIFACTS_DIR": f"{EXP}/artifacts",
                   "LAB_DATA_OFFLINE": "1", "LAB_TELEGRAM_ENABLED": "0", "LAB_MAX_CONCURRENT_JOBS": "3",
                   "LAB_FAST_LANE": "0", "LAB_STRENGTH_REFRESH": "0", "LAB_JOB_NICE": "10"})
sys.path.insert(0, "/tmp/mtf/crypto-screener")
from src.lab import db as labdb
from src.lab.worker import Worker
from src.lab.settings import get_lab_settings
from src.api.lab_routes import create_run, _run_detail, _snooping, _validate
from src.lab.templates import rosyade_family as T

pre = json.load(open(sys.argv[1]))
conn = labdb.connect()
ids = {}
for name, spec in pre["configs"].items():
    params = _validate(T, pre["timeframe"], spec["params"])
    rid, _ = create_run(conn, template_id="rosyade_family", symbol=spec["symbol"], timeframe=pre["timeframe"],
                        mode="validate", params=params, costs=pre["costs"], start=pre["start"], end=pre["end"])
    ids[name] = rid
conn.commit()
print("runs", ids, flush=True)
Worker(get_lab_settings()).run_until_idle(timeout_s=6 * 3600)
out = {}
for name, rid in ids.items():
    r = conn.execute("SELECT * FROM lab_runs WHERE id=?", (rid,)).fetchone()
    d = _run_detail(r)
    d["snooping"] = _snooping(conn, r)
    out[name] = d
    o = d.get("oos_metrics") or {}
    print(name, r["status"], d.get("verdict"), "hs", d.get("holdout_start"), "net", o.get("net_return_pct"),
          "pf", o.get("profit_factor"), "dd", o.get("max_dd_pct"), "sh", o.get("sharpe"), "n", o.get("trades"),
          "2x", o.get("stress_net_return_pct"), "err", (d.get("error") or "")[:200], flush=True)
json.dump(out, open(f"{EXP}/out/holdout_results.json", "w"), indent=1, default=str)

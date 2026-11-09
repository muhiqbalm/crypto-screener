"""Engine child process entry point: ``python -m src.lab.runner <job_id>``.

Started by the worker with the bmtm-v2 interpreter (LAB_ENGINE_PYTHON), under
nice + RLIMIT_AS + timeout. Reads its job from lab.db, does the heavy work,
writes results/artifacts and marks the job done. Exit code != 0 means the
worker records the error.
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
import traceback
from dataclasses import replace
from pathlib import Path

from . import db as labdb
from . import honesty
from . import queue as q
from .settings import get_lab_settings


def artifacts_dir(run_id: int) -> Path:
    p = Path(get_lab_settings().artifacts_dir) / "runs" / str(run_id)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _write_json(path: Path, obj) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(labdb.dumps(obj))
    os.replace(tmp, path)


class Progress:
    def __init__(self, conn, job_id: int):
        self.conn, self.job_id, self._last = conn, job_id, 0.0

    def __call__(self, stage: str, done: int = 0, total: int = 0, force: bool = False):
        now = time.time()
        if force or now - self._last > 2.0:
            q.set_progress(self.conn, self.job_id, {"stage": stage, "done": done, "total": total})
            self._last = now


def _months_add(ts, months: int):
    import pandas as pd
    return ts + pd.DateOffset(months=months)


def walk_forward_reopt(ea, dev_df, warmup: int, params: dict, tf: str, costs: dict,
                       n_trials: int, holdout_start, progress: Progress) -> dict:
    """Rolling walk-forward on the development segment; params are RE-OPTIMISED
    on every train window and evaluated once on the following test window."""
    import pandas as pd
    ts = dev_df["timestamp"]
    first, last = ts.iloc[warmup], ts.iloc[-1]
    span_m = (last - first).days / 30.44
    train_m, test_m = (12, 3) if span_m >= 18 else (6, 3)
    windows = []
    t = _months_add(first, train_m)
    while _months_add(t, test_m) <= last + pd.Timedelta(days=1):
        windows.append((_months_add(t, -train_m), t, _months_add(t, test_m)))
        t = _months_add(t, test_m)
    windows = windows[-6:]
    per_fold = max(8, n_trials // 3)
    folds, growth, pfs = [], 1.0, []
    for k, (a, b, c) in enumerate(windows):
        progress(f"walk-forward fold {k + 1}/{len(windows)}", k, len(windows), force=True)
        train_df, tw = ea.window(dev_df, a, b, warmup)
        test_df, sw = ea.window(dev_df, b, c, warmup)
        if len(train_df) - tw < 50 or len(test_df) - sw < 20:
            continue
        opt = ea.optimize(train_df, tw, params, tf, costs, per_fold, holdout_start, seed=42 + k)
        cfg, ecfg = ea.build_configs(opt["best_params"], tf, costs)
        res_test, _ = ea.run(test_df, cfg, ecfg, warmup=sw)
        mt = ea.metrics(res_test)
        growth *= 1 + (mt["net_return_pct"] or 0.0) / 100.0
        if mt["profit_factor"] is not None:
            pfs.append(mt["profit_factor"])
        folds.append({
            "fold": k, "train_start": honesty.iso(a), "train_end": honesty.iso(b), "test_start": honesty.iso(b),
            "test_end": honesty.iso(c),
            "train": opt["best_metrics"], "test": mt,
            "best_params": {s: opt["best_params"][s] for s in (x["key"] for x in ea.T.tunable_params())},
        })
    prof = sum(1 for f in folds if (f["test"]["net_return_pct"] or 0) > 0)
    return {
        "scheme": f"rolling train {train_m}m / test {test_m}m, re-optimised per fold ({per_fold} trials)",
        "folds": folds,
        "oos_compounded_net_pct": (growth - 1.0) * 100.0 if folds else None,
        "oos_avg_pf": sum(pfs) / len(pfs) if pfs else None,
        "oos_trades": sum(f["test"]["trades"] for f in folds),
        "consistency": prof / len(folds) if folds else None,
    }


def execute_run(conn, job: dict) -> None:
    from . import data_cache as dc
    from . import engine_adapter as ea

    s = get_lab_settings()
    run = dict(conn.execute("SELECT * FROM lab_runs WHERE id=?", (job["ref_id"],)).fetchone())
    run_id, tf, symbol, mode = run["id"], run["timeframe"], run["symbol"], run["mode"]
    params = labdb.loads(run["params_json"], {})
    costs = labdb.loads(run["costs_json"], {})
    payload = labdb.loads(job.get("payload_json"), {}) or {}
    prog = Progress(conn, job["id"])
    conn.execute("UPDATE lab_runs SET engine_commit=? WHERE id=?", (ea.engine_commit(), run_id))
    conn.commit()

    prog("data", force=True)
    offline = os.environ.get("LAB_DATA_OFFLINE") == "1"
    ohlcv, fund = dc.ensure(symbol, tf, funding=bool(costs.get("funding", True)), offline=offline,
                            progress=lambda d: prog(d.get("stage", "data"), d.get("done", 0), d.get("total", 0)))
    cfg, ecfg = ea.build_configs(params, tf, costs)
    warm = ecfg.warmup_period
    df, eval_start, eval_end, _ = ea.prepare_frame(
        ohlcv, fund, tf, run["start_date"], run["end_date"], warm, bool(costs.get("funding", True)))
    data_info = {"eval_start": honesty.iso(eval_start), "eval_end": honesty.iso(eval_end), "bars": int(len(df) - warm),
                 "warmup_bars": warm, "funding_attached": "funding_rate" in df.columns}
    out_dir = artifacts_dir(run_id)

    if mode == "backtest":
        prog("backtest", force=True)
        res, _ = ea.run(df, cfg, ecfg)
        m = ea.metrics(res)
        _write_json(out_dir / "equity.json", ea.equity_out(res))
        _write_json(out_dir / "trades.json", ea.trades_out(res))
        conn.execute(
            "UPDATE lab_runs SET metrics_json=?, extra_json=?, net_return_pct=?, profit_factor=?, max_dd_pct=?, "
            "trades=? WHERE id=?",
            (labdb.dumps({**m, "data": data_info}), labdb.dumps({}), m["net_return_pct"], m["profit_factor"],
             m["max_dd_pct"], m["trades"], run_id))
        conn.commit()
        return

    # ── validate / optimize: locked holdout ──
    bar_s = ea.TF_SECONDS[tf]
    hs = honesty.resolve_holdout(conn, run["template_id"], symbol, tf, eval_start, eval_end, bar_s)
    import pandas as pd
    hs_ts = pd.Timestamp(hs)
    dev_df = df[df["timestamp"] < hs_ts].reset_index(drop=True)
    honesty.assert_dev_only(dev_df["timestamp"].tail(1), hs)
    conn.execute("UPDATE lab_runs SET holdout_start=? WHERE id=?", (hs, run_id))
    conn.commit()

    wf, best_info = None, None
    if mode == "optimize":
        n_trials = min(int(payload.get("n_trials") or s.optuna_max_trials), s.optuna_max_trials)
        wf = walk_forward_reopt(ea, dev_df, warm, params, tf, costs, n_trials, hs, prog)
        prog("optimise on development segment", 0, n_trials, force=True)
        best_info = ea.optimize(dev_df, warm, params, tf, costs, n_trials, hs,
                                progress=lambda d, t: prog("optimise on development segment", d, t))
        params = best_info["best_params"]
        cfg, ecfg = ea.build_configs(params, tf, costs)

    prog("in-sample backtest", force=True)
    res_is, ind_is = ea.run(dev_df, cfg, ecfg, warmup=warm)
    m_is = ea.metrics(res_is)

    prog("sensitivity", force=True)
    sens = ea.sensitivity(ind_is, cfg, replace(ecfg, warmup_period=warm),
                          progress=lambda d, t: prog("sensitivity", d, t))

    # The holdout is evaluated exactly once per run, after all choices are made.
    prog("holdout", force=True)
    hold_df, pre = ea.window(df, hs_ts, None, warm)
    res_oos, ind_oos = ea.run(hold_df, cfg, ecfg, warmup=pre)
    touches = honesty.touch_holdout(conn, run["template_id"], symbol, tf)
    m_oos = ea.metrics(res_oos)
    mult = honesty.THRESHOLDS["cost_stress_mult"]
    stress_ecfg = replace(ecfg, warmup_period=pre, commission_pct=ecfg.commission_pct * mult,
                          slippage_pct=ecfg.slippage_pct * mult, slippage_bps=None)
    res_stress, _ = ea.run(hold_df, cfg, stress_ecfg, indicators=ind_oos)
    m_stress = ea.metrics(res_stress)

    prog("full range + Monte Carlo", force=True)
    res_full, _ = ea.run(df, cfg, ecfg)
    m_full = ea.metrics(res_full)
    mc = ea.monte_carlo(res_full)

    checks = honesty.build_checks(honesty.HonestyInputs(
        oos_profit_factor=res_oos.profit_factor if res_oos.total_trades else None,
        oos_net_return_pct=m_oos["net_return_pct"],
        oos_trades=m_oos["trades"],
        mc_dd_p95_pct=mc["dd_p95"],
        stress_net_return_pct=m_stress["net_return_pct"],
        unstable_params=sens["unstable"],
        liquidations=m_full["liquidations"],
    ))
    verdict = honesty.verdict(checks)

    _write_json(out_dir / "equity.json", ea.equity_out(res_full, holdout_start=hs))
    _write_json(out_dir / "trades.json", ea.trades_out(res_full))
    # metrics = IN-SAMPLE (development segment); oos_metrics = locked holdout.
    metrics = {**m_is, "segment": "in_sample", "start": data_info["eval_start"], "end": hs,
               "data": data_info, "full_range": m_full, "monte_carlo": mc,
               "sensitivity": {"unstable": sens["unstable"], "tested": len(sens["params"])},
               "walk_forward": wf}
    oos = {**m_oos, "start": hs, "end": honesty.iso(eval_end), "stress_net_return_pct": m_stress["net_return_pct"],
           "stress_multiplier": mult}
    extra = {"sensitivity": sens, "optimizer": best_info and {k: v for k, v in best_info.items()
                                                              if k != "best_params"}}
    # verdict + checks written ONCE together (trigger makes them immutable afterwards)
    conn.execute(
        "UPDATE lab_runs SET verdict=?, checks_json=?, honesty_version=?, metrics_json=?, oos_metrics_json=?, "
        "best_params_json=?, extra_json=?, holdout_touches=?, net_return_pct=?, profit_factor=?, max_dd_pct=?, "
        "trades=? WHERE id=?",
        (verdict, labdb.dumps(checks), honesty.HONESTY_VERSION, labdb.dumps(metrics), labdb.dumps(oos),
         labdb.dumps(params) if mode == "optimize" else None, labdb.dumps(extra), touches,
         m_is["net_return_pct"], m_is["profit_factor"], m_is["max_dd_pct"], m_is["trades"], run_id))
    conn.commit()


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    job_id = int(argv[0])
    conn = labdb.connect()
    job = conn.execute("SELECT * FROM lab_jobs WHERE id=?", (job_id,)).fetchone()
    if job is None:
        print(f"job {job_id} not found", file=sys.stderr)
        return 2
    job = dict(job)
    try:
        if job["kind"] == "run":
            execute_run(conn, job)
        elif job["kind"] == "watch_eval":
            from .watch_eval import execute_watch
            execute_watch(conn, job)
        else:
            raise ValueError(f"unknown job kind {job['kind']}")
        q.finish(conn, job_id, "done")
        return 0
    except Exception as e:  # noqa: BLE001
        tb = traceback.format_exc()
        print(tb, file=sys.stderr)
        msg = f"{type(e).__name__}: {e}"
        q.finish(conn, job_id, "error", msg)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())

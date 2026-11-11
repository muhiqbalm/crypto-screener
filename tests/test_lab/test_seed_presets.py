"""ops/lab_seed_presets.py: research presets + paper watches, dry-run by default, idempotent."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "ops" / "lab_seed_presets.py"
MANIFEST = ROOT / "ops" / "lab_presets_seed.json"


@pytest.fixture
def seed_mod(lab_env, monkeypatch):
    monkeypatch.setenv("LAB_TELEGRAM_ENABLED", "0")  # restored after the test (main() forces it to 0)
    spec = importlib.util.spec_from_file_location("lab_seed_presets", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _counts(conn):
    from src.lab import presets as pr
    pr.ensure_schema(conn)
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("lab_presets", "paper_accounts", "watches", "lab_preset_links")}


def test_manifest_is_valid_and_paper_only():
    from src.lab import presets as pr
    from src.lab.templates import get_template
    m = json.loads(MANIFEST.read_text())
    names = [e["name"] for e in m["presets"]]
    assert names[:3] == ["4H-ETH-Basic", "4H-BTC-Opt", "4H-SOL-Opt"] and len(set(names)) == len(names)
    t = get_template("rosyade_family")
    for e in m["presets"]:
        assert e["paper"]["balance"] == 10000.0
        if e.get("live_reference"):
            continue
        assert pr.make_name(e["timeframe"], e["symbol"], e["label"]) == e["name"]
        full = t.validate_params(e["params"])                         # valid; complete except keys the
        assert {k: full[k] for k in e["params"]} == e["params"]        # template gained later with their
        assert all(full[k] == t.defaults()[k] for k in set(full) - set(e["params"]))  # live defaults
        assert set(full) - set(e["params"]) <= t.SIZING_KEYS
        assert not t.is_mtf(e["params"])                              # watchable live
        assert e["source_run_id"] is None and e["source_mode"] == "research"
        assert e["holdout"]["trades"] > 0 and e["snooping"]["holdout_viewed"] is True
        assert len(e["notes"]) <= 2000


def test_dry_run_writes_nothing(seed_mod, conn):
    before = _counts(conn)
    assert seed_mod.main(["--manifest", str(MANIFEST)]) == 0
    assert _counts(conn) == before


def test_apply_is_idempotent(seed_mod, conn):
    from src.lab import presets as pr
    assert seed_mod.main(["--manifest", str(MANIFEST), "--apply"]) == 0
    n = len(json.loads(MANIFEST.read_text())["presets"])
    first = _counts(conn)
    assert first == {"lab_presets": n, "paper_accounts": n, "watches": n, "lab_preset_links": n}
    assert seed_mod.main(["--manifest", str(MANIFEST), "--apply"]) == 0
    assert _counts(conn) == first

    btc = next(p for p in pr.list_presets(conn) if p["name"] == "4H-BTC-Opt")
    assert btc["verdict"] == "FAIL" and btc["source_run_id"] is None and btc["source_mode"] == "research"
    assert btc["holdout"]["trades"] == 17 and btc["snooping"]["holdout_viewed"] is True
    assert btc["usage"] == {"runs": 0, "watches": 1}
    live = next(p for p in pr.list_presets(conn) if p["name"] == "4H-ETH-Basic")
    assert live["live_reference"] and live["readonly"]
    for r in conn.execute("SELECT a.name, a.starting_balance, a.risk_pct, a.leverage_max, w.autopaper_enabled, "
                          "w.symbol, p.name AS preset FROM watches w JOIN lab_preset_links l ON l.kind='watch' "
                          "AND l.ref_id=w.id JOIN lab_presets p ON p.id=l.preset_id "
                          "JOIN paper_accounts a ON a.id=w.autopaper_account_id"):
        assert r["name"] == f"Paper {r['preset']}" and r["starting_balance"] == 10000.0
        assert (r["risk_pct"], r["leverage_max"], r["autopaper_enabled"]) == (100.0, 2.0, 1)
    jobs = conn.execute("SELECT COUNT(*) FROM lab_jobs WHERE kind='watch_eval' AND status='queued'").fetchone()[0]
    assert jobs == n


def test_conflicting_preset_is_left_untouched(seed_mod, conn, tmp_path):
    from src.lab import presets as pr
    m = json.loads(MANIFEST.read_text())
    assert seed_mod.main(["--manifest", str(MANIFEST), "--apply", "--only", "4H-BTC-Opt"]) == 0
    m["presets"][1]["params"] = dict(m["presets"][1]["params"], swing_len=9)
    alt = tmp_path / "alt.json"
    alt.write_text(json.dumps(m))
    assert seed_mod.main(["--manifest", str(alt), "--apply", "--only", "4H-BTC-Opt"]) == 1
    btc = next(p for p in pr.list_presets(conn) if p["name"] == "4H-BTC-Opt")
    assert btc["params"]["swing_len"] == 8


def test_mirror_sizing_matches_backtest_notional(seed_mod):
    assert seed_mod.paper_sizing({}, {"leverage": 4.0, "portfolio_risk": 50.0}) == (100.0, 2.0)
    assert seed_mod.paper_sizing({"paper": {"sizing": "risk", "risk_pct": 1.0, "leverage_max": 3.0}},
                                 {"leverage": 4.0, "portfolio_risk": 50.0}) == (1.0, 3.0)


def test_mirror_sizing_modes(seed_mod):
    assert seed_mod.paper_sizing({}, {"leverage": 4.0, "portfolio_risk": 25.0}) == (100.0, 1.0)
    assert seed_mod.paper_sizing({}, {"sizing_mode": "risk", "risk_per_trade_pct": 1.5, "max_notional_mult": 2.0,
                                      "leverage": 4.0, "portfolio_risk": 50.0}) == (1.5, 2.0)
    assert seed_mod.paper_sizing({}, {"sizing_mode": "vol_target", "max_notional_mult": 2.0, "leverage": 4.0,
                                      "portfolio_risk": 50.0}) == (100.0, 2.0)
    for bad in ({"sizing_mode": "margin", "dd_derisk_pct": 20.0}, {"sizing_mode": "kelly"}):
        with pytest.raises(SystemExit):
            seed_mod.paper_sizing({"name": "x"}, {"leverage": 4.0, "portfolio_risk": 50.0, **bad})


def test_stored_preset_without_new_template_keys_is_not_a_conflict(seed_mod, conn):
    """Presets stored before a template gained keys (e.g. sizing) must still match their manifest entry."""
    from src.lab import db as labdb
    from src.lab.templates import rosyade_family as T
    assert seed_mod.main(["--manifest", str(MANIFEST), "--apply", "--only", "4H-BTC-Opt"]) == 0
    r = conn.execute("SELECT id, params_json FROM lab_presets WHERE name='4H-BTC-Opt'").fetchone()
    old = {k: v for k, v in labdb.loads(r["params_json"]).items() if k not in T.SIZING_KEYS}
    conn.execute("UPDATE lab_presets SET params_json=? WHERE id=?", (labdb.dumps(old), r["id"]))
    conn.commit()
    assert seed_mod.main(["--manifest", str(MANIFEST), "--apply", "--only", "4H-BTC-Opt"]) == 0


SIZING = {"1x": ROOT / "ops" / "lab_presets_sizing_1x_seed.json", "vt": ROOT / "ops" / "lab_presets_sizing_vt_seed.json"}


@pytest.mark.parametrize("kind", ["1x", "vt"])
def test_sizing_manifests_are_variants_of_the_paper_presets(kind):
    from src.lab import presets as pr
    from src.lab.templates import rosyade_family as T
    base = {e["name"]: e for e in json.loads(MANIFEST.read_text())["presets"]}
    m = json.loads(SIZING[kind].read_text())
    for e in m["presets"]:
        parent = e["name"].rsplit("_", 1)[0]
        assert parent in base and pr.make_name(e["timeframe"], e["symbol"], e["label"]) == e["name"]
        pp = T.defaults() if base[parent].get("live_reference") else T.validate_params(base[parent]["params"])
        p = T.validate_params(e["params"])
        changed = {k for k in p if p[k] != pp[k]}
        if kind == "1x":   # deploy-free: only keys the pre-sizing template knows, margin 25% x 4 = 1x
            assert not set(e["params"]) & T.SIZING_KEYS and changed == {"portfolio_risk"}
            assert p["portfolio_risk"] * p["leverage"] / 100 == 1.0
        else:
            assert changed == {"sizing_mode", "vol_target_pct"}            # lookback 60 / cap 2x = defaults
            assert p["sizing_mode"] == "vol_target" and p["max_notional_mult"] == 2.0
        assert e["paper"] == {"balance": 10000.0, "sizing": "mirror"} and not e.get("live_reference")
        assert e["holdout"]["contaminated"] is True and e["snooping"]["holdout_viewed"] is True
        assert len(e["notes"]) <= 2000


def test_sizing_manifests_seed_idempotently_next_to_the_parents(seed_mod, conn):
    assert seed_mod.main(["--manifest", str(MANIFEST), "--apply"]) == 0
    before = _counts(conn)
    for path in SIZING.values():
        assert seed_mod.main(["--manifest", str(path)]) == 0                 # dry-run writes nothing
        assert _counts(conn) == before
    for path in SIZING.values():
        assert seed_mod.main(["--manifest", str(path), "--apply"]) == 0
        assert seed_mod.main(["--manifest", str(path), "--apply"]) == 0      # idempotent
    after = _counts(conn)
    assert after["lab_presets"] == before["lab_presets"] + 6 and after["watches"] == before["watches"] + 6
    acc = {r["name"]: (r["risk_pct"], r["leverage_max"]) for r in conn.execute("SELECT * FROM paper_accounts")}
    assert acc["Paper 4H-ETH-v2_1x"] == (100.0, 1.0) and acc["Paper 4H-ETH-v2_VT60"] == (100.0, 2.0)
    assert acc["Paper 4H-ETH-v2"] == (100.0, 2.0)                             # parent untouched

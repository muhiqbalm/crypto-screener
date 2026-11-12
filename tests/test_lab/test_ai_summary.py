"""Ringkasan AI (src/lab/ai): config / off paths, facts, number validation, budget cap, cache,
client handling and the API permissions. The Anthropic client is ALWAYS a fake: no network,
and the ``anthropic`` package is never imported (the deploy runs these tests before pip install)."""
import json
import sys
import types
from datetime import datetime, timezone

import pytest

from src.lab.ai import JOB_KIND, LABEL
from src.lab.ai import client as C
from src.lab.ai import config as CF
from src.lab.ai import facts as F
from src.lab.ai import job as J
from src.lab.ai import schedule as SCH
from src.lab.ai import store as AS
from src.lab.ai import validate as V
from src.lab.outlook import logic as L
from src.lab.outlook import store as S

from .test_lab_api import client_for  # noqa: F401  (pytest fixture)

KEY = "sk-ant-test-" + "x" * 24
BAR = "2026-11-12T08:00:00Z"
BAR_CLOSE = "2026-11-12T12:00:00Z"
NOW_TS = datetime(2026, 11, 12, 12, 10, tzinfo=timezone.utc).timestamp()


# ── fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def ai_env(lab_env, monkeypatch):
    """Feature switched on with a fake key; .env is never read (REPO_ROOT has none in tests)."""
    for k in ("LAB_AI_MODEL", "LAB_AI_EFFORT", "LAB_AI_DAILY_BUDGET_USD"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("LAB_AI_ENABLED", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    monkeypatch.setattr(CF, "sdk_available", lambda: True)
    monkeypatch.setattr(CF, "_dotenv_key", lambda *_: "")
    monkeypatch.setattr(CF, "_read_dotenv", lambda *_: {})
    CF.reset_cache()
    yield lab_env
    CF.reset_cache()


def _strategy(side="short", fresh=False, verdict=None):
    st = {"side": side, "fresh": fresh, "name": "Rosyade default 4H", "template_id": "rosyade_family",
          "timeframe": "4h", "entry_price": 73143.41 if side else None, "sl": 75337.71 if side else None,
          "tp": 64000.48 if side else None, "entry_at": "2026-11-10T16:00:00Z" if side else None,
          "last_bar": BAR, "last_bar_close": BAR_CLOSE,
          "preset": {"id": 1, "name": "4H-ETH-v2_1x", "verdict": verdict} if verdict else None}
    return st


CAL = {"computed_at": "2026-11-12T03:00:00Z", "buckets": {
    "belum_diuji|short|*|berjalan": {"n_cases": 24176, "n_pos": 2832, "p_tp": 0.19, "p_sl": 0.26, "p_batal": 0.55,
                                     "p_expired": 0.0, "mean_r": 0.027, "lo95_r": -0.035, "se_r": 0.03,
                                     "median_r": -0.36, "ev_shrunk_r": 0.0268, "win_rate": 0.32,
                                     "median_mfe_r": 0.7, "median_bars": 7.0},
    "pool|short|*|berjalan": {"n_cases": 25205, "n_pos": 2906, "p_tp": 0.19, "p_sl": 0.26, "p_batal": 0.55,
                              "p_expired": 0.0, "mean_r": 0.029, "lo95_r": -0.03, "se_r": 0.03, "median_r": -0.35,
                              "ev_shrunk_r": 0.029, "win_rate": 0.32, "median_mfe_r": 0.69, "median_bars": 7.0}}}
SCREENER = {"signal": "NEUTRAL", "tier": "B", "funding_rate_signal": "BEARISH", "oi_signal": "NEUTRAL",
            "funding_rate": 0.031, "long_short_ratio": 3.24, "bar": "2026-11-12T11:00:00Z"}
STRENGTH = {"funding_7d_apr_pct": 25.0, "trend": "down"}


def _row(symbol="BTCUSDT", side="short", fresh=False, screener=SCREENER, oi=-0.55, regime_dir=-1, bar=BAR):
    st = _strategy(side, fresh)
    ctx = {"strategy": st, "mtf": {"tren_1d": {"direction": -1, "dist_pct": -6.2, "slope_pct": -1.8},
                                   "momentum_1h": {"direction": -1, "ret_24h_pct": -1.4}},
           "regime": {"label": "turun" if regime_dir < 0 else "datar", "label_text": "Pasar turun" if regime_dir < 0
                      else "Pasar datar / transisi", "dist_ema_slow_pct": -3.1, "slope_pct": -1.8, "days_in_label": 13},
           "regime_dir_at_call": regime_dir, "lifts": None, "screener": screener, "track": {},
           "strength": STRENGTH, "oi": {"change_24h_pct": oi} if oi is not None else None,
           "headlines": [], "fear_greed": {"value": 28, "classification": "Fear"}}
    factors = L.build_factors(ctx)
    bias = L.combine(factors, st, CAL, now_iso="2026-11-12T12:05:00Z", price=72930.0)
    row = {"symbol": symbol, "coin": symbol.replace("USDT", ""), "price": 72930.0, "last_bar": bar,
           "last_bar_close": BAR_CLOSE if bar == BAR else bar, "strategy": st, "factors": factors, "bias": bias,
           "market": {"screener": screener, "strength": STRENGTH,
                      "oi": {"change_24h_pct": oi, "source": "Binance"} if oi is not None else None}}
    row["plan"] = L.plan(st, row["price"], bias, now_iso="2026-11-12T12:05:00Z")
    row["peluang"] = L.peluang(row)
    return row


HEADLINES = [{"title": "Bitcoin slumps as ETF outflows hit $2B", "published_at": "2026-11-12T08:06:48Z",
              "source": "CoinTelegraph", "url": "https://cointelegraph.com/x"},
             {"title": "Bitcoin hovers near $74K as stocks rise", "published_at": "2026-11-11T16:26:00Z",
              "source": "CoinTelegraph", "url": "https://cointelegraph.com/y"}]
WHALES = {"status": "live", "topTraderRatios": [{"symbol": "BTCUSDT", "longPct": 61.2, "shortPct": 38.8, "lsRatio": 1.58}],
          "largeTradeBuyUsd": 2_150_000.0, "largeTradeSellUsd": 3_400_000.0, "largeTradeNetUsd": -1_250_000.0,
          "largeTradeWindowSeconds": 412.0, "largeTradeMinUsd": 50_000}


def _store_outlook(conn, rows, headlines=None, fear_greed={"value": 28, "classification": "Fear"}):
    for r in rows:
        S.save_row(conn, r["symbol"], r, {"headlines": (headlines or {}).get(r["symbol"], []), "candles": []})
    S.kv_set(conn, S.META_KEY, {"last_bar": max(r["last_bar"] for r in rows), "computed_at": "2026-11-12T12:04:00Z",
                                "fear_greed": fear_greed})
    conn.commit()


def _facts_of(params) -> dict:
    content = params["messages"][0]["content"]
    assert content.startswith("FACTS:\n")
    return json.loads(content[len("FACTS:\n"):])


def good_answer(facts: dict) -> dict:
    """A well-behaved model: copies numbers from the facts, follows efek_sistem."""
    fk = facts["faktor"]
    out = []
    if "funding" in fk:
        out.append({"factor": "funding", "value": f"funding {fk['funding'].get('funding_sekarang', '')} long ramai",
                    "effect": fk["funding"]["efek_sistem"]})
    if "open_interest" in fk:
        out.append({"factor": "open_interest", "value": f"OI 24 jam {fk['open_interest'].get('perubahan_24_jam', '')}",
                    "effect": fk["open_interest"]["efek_sistem"]})
    if "fear_greed" in fk:
        out.append({"factor": "fear_greed", "value": f"{fk['fear_greed']['nilai']} ({fk['fear_greed']['kategori']})",
                    "effect": "netral"})
    arah = facts["outlook"]["arah"]
    return {"sentence": f"Outlook {arah} dengan keyakinan {facts['outlook'].get('keyakinan', '-')}; funding cenderung "
                        f"searah dan Fear & Greed {fk.get('fear_greed', {}).get('nilai', '')} netral.",
            "factors": out}


def _msg(answer, model="claude-opus-5-5", stop="end_turn", usage=None):
    usage = usage or {"input_tokens": 600, "output_tokens": 400, "cache_read_input_tokens": 1000,
                      "cache_creation_input_tokens": 0}
    return types.SimpleNamespace(model=model, stop_reason=stop, usage=usage, content=[
        types.SimpleNamespace(type="thinking", thinking=""),
        types.SimpleNamespace(type="text", text=json.dumps(answer) if not isinstance(answer, str) else answer)])


class FakeClient:
    """Stands in for anthropic.Anthropic: records every request, answers with ``responder``."""

    def __init__(self, responder=None):
        self.calls = []
        self.responder = responder or (lambda params: _msg(good_answer(_facts_of(params))))
        outer = self

        class _M:
            def create(self, **params):
                outer.calls.append(params)
                r = outer.responder(params)
                if isinstance(r, Exception):
                    raise r
                return r

        self.messages = _M()
        self.beta = types.SimpleNamespace(messages=self.messages)


def _run(conn, fake, **kw):
    return J.execute(conn, None, client_factory=lambda cfg: fake, whales_fetcher=lambda: WHALES, **kw)


# ── config: off by default, reasons, key never shown ─────────────────────

def test_off_by_default_and_reasons(lab_env, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("LAB_AI_ENABLED", raising=False)
    monkeypatch.setattr(CF, "_dotenv_key", lambda *_: "")
    monkeypatch.setattr(CF, "_read_dotenv", lambda *_: {})
    cfg = CF.ai_config(fresh=True)
    assert cfg.enabled is False and cfg.key_present is False and cfg.model == "claude-opus-5-5"
    assert cfg.effort == "low" and cfg.daily_budget_usd == 5.0
    assert CF.off_reason(cfg) == "no_key"                                  # key missing wins over the flag
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    assert CF.off_reason(CF.ai_config(fresh=True)) == "disabled"
    monkeypatch.setenv("LAB_AI_ENABLED", "1")
    monkeypatch.setattr(CF, "sdk_available", lambda: False)
    assert CF.off_reason(CF.ai_config(fresh=True)) == "sdk_missing"
    monkeypatch.setattr(CF, "sdk_available", lambda: True)
    cfg = CF.ai_config(fresh=True)
    assert CF.off_reason(cfg) is None
    assert KEY not in repr(cfg)                                            # never printed
    CF.reset_cache()


def test_config_reads_dotenv_and_rejects_bad_values(lab_env, monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY='%s'\nexport LAB_AI_ENABLED=1\nLAB_AI_MODEL=claude-sonnet-5-5\n"
                   "LAB_AI_EFFORT=turbo\nLAB_AI_DAILY_BUDGET_USD=abc\nOTHER_SECRET=nope\n" % KEY)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("LAB_AI_ENABLED", raising=False)
    monkeypatch.setattr(CF, "REPO_ROOT", tmp_path)
    cfg = CF.ai_config(fresh=True)
    assert cfg.api_key == KEY and cfg.enabled and cfg.model == "claude-sonnet-5-5"
    assert cfg.effort == "low" and cfg.daily_budget_usd == 5.0             # invalid values fall back
    monkeypatch.setenv("LAB_AI_MODEL", "x; rm -rf /")
    assert CF.ai_config(fresh=True).model == "claude-opus-5-5"
    CF.reset_cache()


def test_sdk_is_never_imported_outside_the_client_factory(ai_env, conn, monkeypatch):
    monkeypatch.setitem(sys.modules, "anthropic", None)                   # import anthropic -> ImportError
    _store_outlook(conn, [_row()])
    meta = _run(conn, FakeClient())
    assert meta["counts"]["ok"] == 1                                       # the whole pipeline ran without it


def test_job_and_scheduler_do_nothing_while_off(lab_env, conn, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(CF, "_dotenv_key", lambda *_: "")
    CF.reset_cache()
    _store_outlook(conn, [_row()])
    fake = FakeClient()
    made = []
    meta = J.execute(conn, None, client_factory=lambda cfg: made.append(1) or fake, whales_fetcher=lambda: WHALES)
    assert meta["stopped"] == "no_key" and not made and not fake.calls
    assert SCH.tick(conn, None, NOW_TS) is None
    assert conn.execute("SELECT COUNT(*) FROM lab_jobs").fetchone()[0] == 0
    CF.reset_cache()


# ── facts: market data only, exchange-style numbers, own rules ───────────

def test_facts_are_market_data_only_with_system_effects():
    f = F.build(_row(), HEADLINES, {"value": 28, "classification": "Fear"}, WHALES)
    js = f.json()
    for word in ("email", "@", "passphrase", "api_key", "user", "positions", "sk-ant"):
        assert word not in js.lower()
    fk = f.facts["faktor"]
    assert f.facts["outlook"]["arah"] == "SHORT" and f.facts["outlook"]["keyakinan"] == "rendah"
    assert f.facts["outlook"]["kasus_serupa"] == "rata-rata +0.03R dari 2,832 posisi"
    assert fk["funding"]["funding_sekarang"] == "+0.0310%" and fk["funding"]["rata_rata_7_hari"] == "+25.0% per tahun"
    assert fk["funding"]["efek_sistem"] == "mendukung"                    # BEARISH (longs crowded) supports SHORT
    assert fk["open_interest"] == {"sinyal_screener": "NEUTRAL", "perubahan_24_jam": "−0.6%", "efek_sistem": "netral"}
    assert fk["rezim_btc"]["efek_sistem"] == "mendukung"                  # BTC regime down supports SHORT
    assert fk["arus_whale"]["posisi_top_trader"] == "61.2% long, 38.8% short"
    assert "net −$1.25M dalam 7 menit" in fk["arus_whale"]["transaksi_besar_gabungan_btc_eth_sol"]
    assert fk["berita"]["jumlah"].startswith("2 headline: 0 bullish, 1 bearish, 1 netral")
    assert f.gaps == [] and f.available == set(F.FACTOR_KEYS)
    assert f.input_hash("v", "m", "low") == F.build(_row(), HEADLINES, {"value": 28, "classification": "Fear"},
                                                    WHALES).input_hash("v", "m", "low")


def test_facts_gaps_and_flat_coin_is_all_netral():
    row = _row("INJUSDT", side=None, screener={"funding_rate_signal": "BULLISH", "funding_rate": -0.01}, oi=None)
    f = F.build(row, None, None, WHALES)
    assert f.facts["outlook"]["arah"] == "TUNGGU"
    assert any("Arus whale: tidak tersedia untuk koin ini" in g for g in f.gaps)
    assert "Fear & Greed: tidak tersedia." in f.gaps and "Berita: sumber berita tidak bisa dimuat." in f.gaps
    assert "arus_whale" not in f.available and "fear_greed" not in f.available
    assert f.facts["outlook"]["condong"].startswith("turun") and f.ref_dir == -1      # TUNGGU judged vs condong
    row = _row("INJUSDT", side=None)
    row["bias"]["condong"] = None
    flat = F.build(row, [], None, None)
    assert flat.ref_dir == 0 and set(flat.system_effects.values()) == {"netral"}
    assert all(v["efek_sistem"] == "netral" for v in flat.facts["faktor"].values())
    assert any(g.startswith("Berita: tidak ada headline") for g in flat.gaps)
    assert F.build({"symbol": "X", "unavailable": True}, None, None, None) is None


# ── number validation ────────────────────────────────────────────────────

def test_number_parsing_styles():
    nums = [str(v) for _, v in V.numbers_in("BTC 72,930 turun −0.6%, funding +0.0042%, $74K, 1,5 dan 2.832.000 di 4H")]
    assert nums == ["72930", "0.6", "0.0042", "74", "1.5", "2832000", "4"]
    assert [str(v) for _, v in V.numbers_in("1000PEPE ETH-v2_1x")] == ["1000"]


def test_validation_accepts_grounded_numbers_and_rejects_invented_ones():
    f = F.build(_row(), HEADLINES, {"value": 28, "classification": "Fear"}, WHALES)
    ok, out, rep = V.check({"sentence": "SHORT keyakinan rendah; funding +0.0310% dan OI −0.6% dalam 24 jam, ETF outflow $2B.",
                            "factors": [{"factor": "funding", "value": "+0.0310%, rata-rata 25.0% per tahun",
                                         "effect": "melemahkan"},
                                        {"factor": "open_interest", "value": "OI naik 9.9%", "effect": "netral"},
                                        {"factor": "fear_greed", "value": "28 (Fear)", "effect": "netral"},
                                        {"factor": "fear_greed", "value": "28", "effect": "netral"}]}, f)
    assert ok == "ok"
    assert [x["factor"] for x in out["factors"]] == ["funding", "fear_greed"]
    assert out["factors"][0]["effect"] == "mendukung"                     # our rule wins over the model
    assert rep["effects_overridden"] == [{"factor": "funding", "model": "melemahkan", "aturan": "mendukung"}]
    assert {d["reason"].split(":")[0] for d in rep["dropped_factors"]} == {"angka tidak ada di data", "faktor ganda"}
    assert out["factors"][0]["source"] == F.SOURCES["funding"] and out["data_gaps"] == []
    bad, none, rep = V.check({"sentence": "SHORT, harga bisa turun 12% ke 65,000.", "factors": []}, f)
    assert bad == "rejected" and none is None and rep["sentence_ungrounded"] == ["12", "65,000"]


def test_validation_drops_factors_that_are_not_in_the_data():
    f = F.build(_row("INJUSDT", side=None, oi=None), None, None, None)
    status, out, rep = V.check({"sentence": "Tidak ada arah.", "factors": [
        {"factor": "arus_whale", "value": "whale beli besar", "effect": "mendukung"},
        {"factor": "funding", "value": "funding positif", "effect": "mendukung"}]}, f)
    assert status == "ok" and [x["factor"] for x in out["factors"]] == ["funding"]
    assert rep["dropped_factors"][0]["reason"] == "faktor tidak ada di data (data kosong)"
    assert V.check({"sentence": "x", "factors": [{"factor": "arus_whale", "value": "y", "effect": "netral"}]}, f)[0] == "rejected"
    assert V.check("not json", f)[0] == "rejected"
    assert V.check({"sentence": "a" * 500, "factors": []}, f)[0] == "rejected"


# ── job: cache, budget cap, errors ───────────────────────────────────────

def test_job_summarises_validates_stores_and_caches_per_bar(ai_env, conn):
    _store_outlook(conn, [_row("BTCUSDT"), _row("ETHUSDT")], {"BTCUSDT": HEADLINES})
    fake = FakeClient()
    meta = _run(conn, fake)
    assert meta["counts"]["ok"] == 2 and meta["done"] == 2 and meta["stopped"] is None and meta["whales"] is True
    p = fake.calls[0]
    assert p["model"] == "claude-opus-5-5" and p["output_config"]["effort"] == "low"
    assert p["output_config"]["format"]["type"] == "json_schema" and "tools" not in p and "tool_choice" not in p
    assert p["system"][0]["cache_control"] == {"type": "ephemeral"} and p["system"][0]["text"] == C.SYSTEM_PROMPT
    assert p["fallbacks"] == "default" and p["betas"] == [CF.FALLBACK_BETA]
    assert "temperature" not in p
    rec = AS.get(conn, "BTCUSDT", BAR)
    assert rec["status"] == "ok" and rec["output"]["sentence"].startswith("Outlook SHORT")
    assert rec["input_tokens"] == 600 and rec["cache_read_tokens"] == 1000
    assert rec["cost_usd"] == pytest.approx((600 * 4 + 400 * 20 + 1000 * 0.2) / 1e6)
    assert len(rec["input_hash"]) == 64 and rec["facts"]["koin"] == "BTC"
    assert KEY not in json.dumps(rec)
    again = _run(conn, fake)                                              # same bar: served from the cache
    assert again["done"] == 0 and again["skipped_cached"] == 2 and len(fake.calls) == 2
    _store_outlook(conn, [_row("BTCUSDT", bar="2026-11-12T12:00:00Z")])   # next bar: summarised again
    nxt = _run(conn, fake)
    assert nxt["done"] == 1 and len(fake.calls) == 3


def test_budget_cap_stops_the_job_and_the_scheduler(ai_env, conn, monkeypatch):
    rows = [_row(s) for s in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT")]
    _store_outlook(conn, rows)
    monkeypatch.setenv("LAB_AI_DAILY_BUDGET_USD", "0.05")
    CF.reset_cache()
    big = {"input_tokens": 1500, "output_tokens": 1000, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    fake = FakeClient(lambda params: _msg(good_answer(_facts_of(params)), usage=big))   # $0.026 per call
    meta = _run(conn, fake)
    assert meta["stopped"] == "over_budget" and 1 <= meta["done"] < 5
    assert AS.spent_today(conn) <= 0.05 + 1e-9
    monkeypatch.setenv("LAB_AI_DAILY_BUDGET_USD", "0")
    CF.reset_cache()
    zero = FakeClient()
    assert _run(conn, zero)["stopped"] == "over_budget" and not zero.calls
    S.kv_set(conn, SCH.BAR_KEY, None)
    conn.commit()
    assert SCH.tick(conn, None, NOW_TS) is None                           # nothing queued over budget


def test_refusal_truncation_and_bad_json_are_stored_not_shown(ai_env, conn):
    _store_outlook(conn, [_row("BTCUSDT"), _row("ETHUSDT"), _row("SOLUSDT")])
    replies = {"BTC": _msg({}, stop="refusal"), "ETH": _msg({}, stop="max_tokens"), "SOL": _msg("{oops")}
    fake = FakeClient(lambda params: replies[_facts_of(params)["koin"]])
    meta = _run(conn, fake)
    assert meta["counts"] == {"ok": 0, "rejected": 0, "refused": 1, "error": 2}
    assert AS.get(conn, "BTCUSDT", BAR)["cost_usd"] > 0                    # a refusal can still cost tokens
    assert AS.get(conn, "ETHUSDT", BAR)["error"] == "jawaban terpotong (max_tokens)"


class _HttpErr(Exception):
    def __init__(self, status_code, message="boom"):
        super().__init__(message)
        self.status_code, self.message = status_code, message


def test_invalid_key_is_fatal_and_stops_after_the_first_call(ai_env, conn):
    _store_outlook(conn, [_row("BTCUSDT"), _row("ETHUSDT"), _row("SOLUSDT")])
    fake = FakeClient(lambda params: _HttpErr(401))
    with pytest.raises(RuntimeError, match="API key ditolak"):
        _run(conn, fake)
    assert len(fake.calls) == 1 and AS.get(conn, "BTCUSDT", BAR)["status"] == "error"
    assert C.CallResult("error", error_kind="bad_request").fatal and not C.CallResult("error", error_kind="server").fatal


def test_fallback_beta_rejected_is_retried_without_it(ai_env, conn):
    _store_outlook(conn, [_row("BTCUSDT")])

    def responder(params):
        if "fallbacks" in params:
            return _HttpErr(400, "fallbacks: unknown parameter")
        return _msg(good_answer(_facts_of(params)))
    fake = FakeClient(responder)
    assert _run(conn, fake)["counts"]["ok"] == 1
    assert len(fake.calls) == 2 and "fallbacks" not in fake.calls[1] and "betas" not in fake.calls[1]


def test_transient_error_does_not_stop_other_coins(ai_env, conn):
    _store_outlook(conn, [_row("BTCUSDT"), _row("ETHUSDT")])
    fake = FakeClient(lambda p: _HttpErr(529) if _facts_of(p)["koin"] == "BTC" else _msg(good_answer(_facts_of(p))))
    meta = _run(conn, fake)
    assert meta["counts"]["error"] == 1 and meta["counts"]["ok"] == 1 and meta["stopped"] is None


def test_usage_cost_prices_each_fallback_attempt_at_its_model():
    cost, tok = CF.usage_cost({"input_tokens": 9, "output_tokens": 9, "iterations": [
        {"type": "message", "input_tokens": 1000, "output_tokens": 0, "cache_read_input_tokens": 0,
         "cache_creation_input_tokens": 0},
        {"type": "fallback_message", "model": "claude-opus-5", "input_tokens": 1000, "output_tokens": 1000,
         "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}]}, "claude-opus-5-5", "claude-opus-5")
    assert cost == pytest.approx((1000 * 4 + 1000 * 5 + 1000 * 25) / 1e6) and tok["input_tokens"] == 2000
    assert CF.price_for("claude-unknown-9")[1] == "fallback_max"
    assert CF.usage_cost({"input_tokens": 1_000_000}, "claude-haiku-5-5")[0] == pytest.approx(0.10)


# ── scheduling + worker wiring ───────────────────────────────────────────

def test_scheduler_queues_once_per_bar_after_the_outlook(ai_env, conn):
    _store_outlook(conn, [_row()])
    from src.lab import queue as q
    oj = q.enqueue(conn, "outlook_refresh", None, {"bar": BAR})
    conn.commit()
    assert SCH.tick(conn, None, NOW_TS) is None                           # outlook still queued
    conn.execute("UPDATE lab_jobs SET status='done' WHERE id=?", (oj,))
    conn.commit()
    jid = SCH.tick(conn, None, NOW_TS)
    assert jid and conn.execute("SELECT kind, priority FROM lab_jobs WHERE id=?", (jid,)).fetchone()[0] == JOB_KIND
    assert SCH.tick(conn, None, NOW_TS) is None                           # once per bar
    conn.execute("UPDATE lab_jobs SET status='done' WHERE id=?", (jid,))
    S.kv_set(conn, SCH.BAR_KEY, None)
    conn.commit()
    assert SCH.tick(conn, None, NOW_TS + 3 * 86400) is None               # stale outlook: never
    assert conn.execute("SELECT COUNT(*) FROM lab_jobs WHERE kind=?", (JOB_KIND,)).fetchone()[0] == 1


def test_worker_runs_the_job_in_the_screener_venv_and_fast_lane():
    from src.lab import worker as W
    assert JOB_KIND in W.SCREENER_VENV_KINDS and JOB_KIND in W.FAST_KINDS
    src = open(W.__file__.replace("worker.py", "runner.py"), encoding="utf-8").read()
    assert '"ai_factor_summary"' in src and "from .ai.job import execute" in src


def test_ai_package_has_no_path_to_trading_or_orders():
    """No import of anything that can trade, notify or change Lab state; no tools declared."""
    import ast
    import pathlib
    root = pathlib.Path(F.__file__).parent
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in node.names] + [getattr(node, "module", None) or ""]
                for n in names:
                    for banned in ("trading", "ccxt", "exchange", "notify", "telegram", "paper", "presets", "watch"):
                        assert banned not in n.lower(), (path.name, n)
    params = C.request_params(CF.AiConfig(enabled=True, api_key=KEY), "{}")
    assert "tools" not in params and "tool_choice" not in params and "mcp_servers" not in params


# ── API: read for every team account, details for admins ─────────────────

def _seed_summary(conn, symbol="BTCUSDT", bar=BAR, status="ok"):
    f = F.build(_row(symbol, bar=bar), HEADLINES, {"value": 28, "classification": "Fear"}, WHALES)
    st, out, rep = V.check(good_answer(f.facts), f) if status == "ok" else (status, None, {})
    AS.save(conn, {"symbol": symbol, "bar": bar, "bar_close": BAR_CLOSE, "input_hash": "h" * 64,
                   "model": "claude-opus-5-5", "served_model": "claude-opus-5-5", "effort": "low", "status": st,
                   "tokens": {"input_tokens": 600, "output_tokens": 400}, "cost_usd": 0.0105, "output": out,
                   "validation": rep, "facts": f.facts, "error": "boom" if status == "error" else None})
    conn.commit()


def test_api_requires_login(client_for):
    c = client_for(None)
    assert c.get("/api/v1/lab/ai/factors?symbol=BTC").status_code == 401
    assert c.get("/api/v1/lab/ai/status").status_code == 401


def test_api_off_member_sees_nothing_admin_sees_one_line(client_for, conn, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(CF, "_dotenv_key", lambda *_: "")
    CF.reset_cache()
    _store_outlook(conn, [_row()])
    _seed_summary(conn)                                                    # old rows are hidden while off
    member = client_for("u-plain").get("/api/v1/lab/ai/factors?symbol=btc").json()
    assert member == {"symbol": "BTCUSDT", "enabled": False, "label": LABEL, "summary": None, "reason": None,
                      "note": None}
    admin = client_for("u-admin").get("/api/v1/lab/ai/factors?symbol=BTC").json()
    assert admin["note"] == "AI belum aktif — perlu API key" and admin["reason"] == "no_key"
    st = client_for("u-plain").get("/api/v1/lab/ai/status").json()
    assert st == {"enabled": False, "active": False, "label": LABEL}
    sa = client_for("u-admin").get("/api/v1/lab/ai/status").json()
    assert sa["reason"] == "no_key" and sa["key_present"] is False and sa["budget"]["daily_usd"] == 5.0
    CF.reset_cache()


def test_api_on_shows_current_summary_to_members_without_admin_meta(client_for, ai_env, conn):
    _store_outlook(conn, [_row("BTCUSDT"), _row("ETHUSDT")])
    _seed_summary(conn, "BTCUSDT")
    _seed_summary(conn, "ETHUSDT", status="error")
    m = client_for("u-plain")
    body = m.get("/api/v1/lab/ai/factors?symbol=BTCUSDT").json()
    s = body["summary"]
    assert body["enabled"] and s["bar"] == BAR and s["sentence"].startswith("Outlook SHORT") and "meta" not in s
    assert {f["effect"] for f in s["factors"]} <= {"mendukung", "melemahkan", "netral"} and s["data_gaps"] == []
    assert m.get("/api/v1/lab/ai/factors?symbol=ETH").json()["note"] is None   # members never see errors
    a = client_for("u-admin")
    assert a.get("/api/v1/lab/ai/factors?symbol=BTC").json()["summary"]["meta"]["model"] == "claude-opus-5-5"
    eth = a.get("/api/v1/lab/ai/factors?symbol=ETH").json()
    assert eth["summary"] is None and eth["reason"] == "error" and eth["note"].endswith(": boom")
    assert a.get("/api/v1/lab/ai/factors?symbol=SOL").json()["reason"] == "pending"
    assert m.get("/api/v1/lab/ai/factors?symbol=../etc").status_code == 422
    st = a.get("/api/v1/lab/ai/status").json()
    assert st["active"] and st["model"] == "claude-opus-5-5" and st["budget"]["spent_today_usd"] == pytest.approx(0.021)
    assert KEY not in json.dumps(st) and "api_key" not in json.dumps(st)


def test_api_hides_a_summary_from_an_older_bar(client_for, ai_env, conn):
    _store_outlook(conn, [_row("BTCUSDT", bar="2026-11-12T12:00:00Z")])
    _seed_summary(conn, "BTCUSDT", bar=BAR)                               # summary of the previous close
    body = client_for("u-plain").get("/api/v1/lab/ai/factors?symbol=BTC").json()
    assert body["enabled"] and body["summary"] is None

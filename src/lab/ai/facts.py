"""The market facts the model may use, built ONLY from data our system already computed:

  * the stored Outlook row of the coin (direction, fase, keyakinan, evidence, BTC regime,
    funding + open interest from the screener snapshot / Binance), its headlines;
  * Fear & Greed from the last outlook_refresh (outlook_meta);
  * the whale snapshot of the /whales page (intel_service: Binance top-trader ratio for
    BTC/ETH/SOL/DOGE, large taker trades for BTC+ETH+SOL), fetched once per job.

No user data, e-mails, positions or keys. Every number is pre-formatted in exchange style
(1,234.56) so the model can copy it and the validator can find it. ``efek_sistem`` is our own
rule (the Outlook factor's direction vs the Outlook direction); the model must follow it.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Optional

from ..outlook import logic as L

FACTOR_KEYS = ("rezim_btc", "funding", "open_interest", "arus_whale", "fear_greed", "berita")
LABELS = {"rezim_btc": "Kondisi pasar (BTC)", "funding": "Funding", "open_interest": "Open interest",
          "arus_whale": "Arus whale", "fear_greed": "Fear & Greed", "berita": "Berita"}
SOURCES = {"rezim_btc": "Regime BTC harian (Outlook BMTM)", "funding": "Binance via screener BMTM",
           "open_interest": "Binance", "arus_whale": "Binance Futures (top trader, transaksi besar)",
           "fear_greed": "alternative.me", "berita": "CoinTelegraph RSS"}
EFFECTS = ("mendukung", "melemahkan", "netral")
PELUANG_TEXT = {"positif": "terbukti positif", "belum_jelas": "belum jelas", "negatif": "tanpa keunggulan",
                "tidak_ada_sinyal": "tidak ada sinyal", "belum_terukur": "belum terukur", "basi": "data basi",
                "tidak_valid": "harga sudah melewati SL"}
CLASS_TEXT = {"lolos_uji": "lolos uji holdout", "gagal_uji": "gagal uji holdout",
              "belum_diuji": "belum diuji untuk koin ini"}
SIGNAL_DIR = {"BULLISH": 1, "BUY": 1, "BEARISH": -1, "SELL": -1}
WHALE_RATIO_COINS = ("BTC", "ETH", "SOL", "DOGE")      # intel_service.RATIO_SYMBOLS
WHALE_FLOW_COINS = ("BTC", "ETH", "SOL")               # intel_service.LARGE_TRADE_SYMBOLS


@dataclass
class Facts:
    symbol: str
    coin: str
    bar: str
    bar_close: Optional[str]
    facts: dict
    gaps: list[str]
    available: set[str] = field(default_factory=set)
    system_effects: dict[str, str] = field(default_factory=dict)
    ref_dir: int = 0

    def json(self) -> str:
        """Canonical JSON sent to the model (sorted keys = stable bytes = stable hash)."""
        return json.dumps(self.facts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def input_hash(self, *parts: str) -> str:
        return hashlib.sha256("|".join([*parts, self.json()]).encode("utf-8")).hexdigest()


def coin_symbol(row: dict) -> str:
    return row.get("coin") or str(row.get("symbol") or "").replace("USDT", "")


def _effect(direction: Optional[int], ref_dir: int) -> str:
    if not ref_dir or not direction:
        return "netral"
    return "mendukung" if direction == ref_dir else "melemahkan"


def _usd(x: float, signed: bool = False) -> str:
    a = abs(x)
    s = f"${a / 1e6:,.2f}M" if a >= 1e6 else f"${a / 1e3:,.1f}K" if a >= 1e3 else f"${a:,.0f}"
    if signed and x > 0:
        return "+" + s
    return (L.MINUS + s) if x < 0 else s


def _factor(row: dict, key: str) -> Optional[dict]:
    return next((f for f in row.get("factors") or [] if f.get("key") == key), None)


def _whale_facts(coin: str, symbol: str, whales: Optional[dict]) -> tuple[Optional[dict], Optional[str]]:
    if coin not in WHALE_RATIO_COINS:
        return None, ("Arus whale: tidak tersedia untuk koin ini (data whale BMTM hanya BTC, ETH, SOL, DOGE).")
    if not whales or whales.get("status") not in ("live", "partial"):
        return None, "Arus whale: sumber Binance tidak bisa dimuat saat ringkasan dibuat."
    out: dict[str, Any] = {}
    ratio = next((r for r in whales.get("topTraderRatios") or [] if r.get("symbol") == symbol), None)
    if ratio and ratio.get("longPct") is not None and ratio.get("shortPct") is not None:
        lp, sp = float(ratio["longPct"]), float(ratio["shortPct"])
        out["posisi_top_trader"] = f"{L.fnum(lp, 1)}% long, {L.fnum(sp, 1)}% short"
        out["condong_top_trader"] = "condong long" if lp > 55 else "condong short" if lp < 45 else "seimbang"
    net, win = whales.get("largeTradeNetUsd"), whales.get("largeTradeWindowSeconds")
    if coin in WHALE_FLOW_COINS and net is not None and win:
        mins = max(1, round(float(win) / 60))
        out["transaksi_besar_gabungan_btc_eth_sol"] = (
            f"beli {_usd(float(whales.get('largeTradeBuyUsd') or 0))}, jual {_usd(float(whales.get('largeTradeSellUsd') or 0))}, "
            f"net {_usd(float(net), signed=True)} dalam {mins} menit terakhir "
            f"(transaksi taker ≥ {_usd(float(whales.get('largeTradeMinUsd') or 50_000))})")
    if not out:
        return None, "Arus whale: data Binance untuk koin ini kosong saat ringkasan dibuat."
    return out, None


def _headline_facts(headlines: Optional[list]) -> tuple[Optional[dict], Optional[str]]:
    if headlines is None:
        return None, "Berita: sumber berita tidak bisa dimuat."
    if not headlines:
        return None, "Berita: tidak ada headline terbaru yang menyebut koin ini."
    from src.services.intel_service import classify_headline
    words = {"BULLISH": "bullish", "BEARISH": "bearish"}
    items, n = [], {"bullish": 0, "bearish": 0, "netral": 0}
    for h in headlines[:5]:
        title = str(h.get("title") or "").strip()[:200]
        if not title:
            continue
        s = words.get(classify_headline(title)["sentiment"], "netral")
        n[s] += 1
        items.append({"judul": title, "sentimen_kata_kunci": s})
    if not items:
        return None, "Berita: tidak ada headline terbaru yang menyebut koin ini."
    return {"jumlah": f"{len(items)} headline: {n['bullish']} bullish, {n['bearish']} bearish, {n['netral']} netral "
                      "(menurut kata kunci)", "headline": items}, None


def build(row: dict, headlines: Optional[list], fear_greed: Optional[dict], whales: Optional[dict]) -> Optional[Facts]:
    """Facts for one stored Outlook row; None when the row has nothing to summarise."""
    if not row or row.get("unavailable") or not row.get("last_bar") or not row.get("strategy"):
        return None
    st, bias = row["strategy"], row.get("bias") or {}
    if st.get("error"):
        return None
    symbol = row.get("symbol") or ""
    coin = coin_symbol(row)
    side = st.get("side")
    condong = bias.get("condong") if not side else None
    ref_dir = L.SIDE_SIGN.get(side or "", 0) or {"naik": 1, "turun": -1}.get(condong or "", 0)
    outlook: dict[str, Any] = {"arah": side.upper() if side else "TUNGGU",
                               "strategi": st.get("name") or "Rosyade default 4H"}
    cls = bias.get("cls") or L.strategy_evidence(st)
    outlook["bukti_strategi"] = CLASS_TEXT.get(cls, cls)
    if side:
        outlook["fase"] = "posisi baru" if st.get("fresh") else "menyusul posisi yang sudah berjalan"
        if bias.get("keyakinan"):
            outlook["keyakinan"] = bias["keyakinan"]
        lab = (row.get("peluang") or {}).get("label")
        if lab:
            outlook["peluang"] = PELUANG_TEXT.get(lab, lab.replace("_", " "))
        cal = ((bias.get("calib") or {}).get("stats")) or {}
        if cal.get("n_pos"):
            outlook["kasus_serupa"] = f"rata-rata {L.fr(cal.get('mean_r'))} dari {L.fnum(cal['n_pos'], 0)} posisi"
    elif condong:
        outlook["condong"] = f"{condong} (dari faktor konteks, belum terbukti sebagai sinyal)"

    faktor: dict[str, dict] = {}
    gaps: list[str] = []
    sys_eff: dict[str, str] = {}
    mk = row.get("market") or {}
    sc, sr, oi = mk.get("screener") or {}, mk.get("strength") or {}, mk.get("oi") or {}

    rg = _factor(row, "regime")
    if rg and rg.get("available"):
        word = {1: "naik", -1: "turun"}.get(rg.get("direction"), "datar")
        faktor["rezim_btc"] = {"kondisi": rg.get("value"), "arah": word}
        sys_eff["rezim_btc"] = _effect(rg.get("direction"), ref_dir)
    else:
        gaps.append("Kondisi pasar BTC: tidak tersedia.")

    rate, apr = sc.get("funding_rate"), sr.get("funding_7d_apr_pct")
    if rate is not None or apr is not None:
        f: dict[str, Any] = {}
        if rate is not None:
            f["funding_sekarang"] = f"{L.fnum(rate, 4, True)}%"
        if apr is not None:
            f["rata_rata_7_hari"] = f"{L.fpct(apr)} per tahun"
        f["sinyal_screener"] = sc.get("funding_rate_signal") or "tidak ada"
        faktor["funding"] = f
        # same reading as the Outlook factor: the screener's funding signal is already contrarian
        # (positive funding = longs crowded = BEARISH)
        sys_eff["funding"] = _effect(SIGNAL_DIR.get(sc.get("funding_rate_signal") or ""), ref_dir)
    else:
        gaps.append("Funding: tidak tersedia.")

    chg, osig = oi.get("change_24h_pct"), sc.get("oi_signal")
    if chg is not None or osig:
        f = {"sinyal_screener": osig or "tidak ada"}
        if chg is not None:
            f["perubahan_24_jam"] = L.fpct(chg)
        faktor["open_interest"] = f
        sys_eff["open_interest"] = _effect(SIGNAL_DIR.get(osig or ""), ref_dir)
    else:
        gaps.append("Open interest: tidak tersedia.")

    wf, gap = _whale_facts(coin, symbol, whales)
    if wf:
        faktor["arus_whale"] = wf
    else:
        gaps.append(gap)

    if fear_greed and fear_greed.get("value") is not None:
        faktor["fear_greed"] = {"nilai": str(int(fear_greed["value"])),
                                "kategori": str(fear_greed.get("classification") or "tidak tersedia"),
                                "cakupan": "seluruh pasar kripto"}
    else:
        gaps.append("Fear & Greed: tidak tersedia.")

    hf, gap = _headline_facts(headlines)
    if hf:
        faktor["berita"] = hf
    else:
        gaps.append(gap)

    if not ref_dir:   # TUNGGU without a lean: there is no direction to support or weaken
        sys_eff = {k: "netral" for k in faktor}
    for k, eff in sys_eff.items():
        faktor[k]["efek_sistem"] = eff
    facts = {"koin": coin, "outlook": outlook, "faktor": faktor, "data_kosong": gaps}
    return Facts(symbol=symbol, coin=coin, bar=row["last_bar"], bar_close=row.get("last_bar_close"), facts=facts,
                 gaps=gaps, available=set(faktor), system_effects=sys_eff, ref_dir=ref_dir)


def fetch_whales(timeout_s: float = 20.0) -> Optional[dict]:
    """The /whales snapshot (intel_service, public Binance endpoints, 7 requests). Fail-soft."""
    try:
        import asyncio

        from src.services.intel_service import intel_service

        async def go():
            return await asyncio.wait_for(intel_service.get_whales_data(), timeout=timeout_s)

        data = asyncio.run(go())
        return data if isinstance(data, dict) and data.get("status") in ("live", "partial") else None
    except Exception:  # noqa: BLE001 - whale data is optional context
        return None

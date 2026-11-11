"""Mean reversion in a range (counter-trend), engine strategy_family "mean_reversion".

Trades only while the regime filter says the market is ranging (ADX below a
threshold and/or Choppiness Index above a threshold). Fades a Bollinger or
Keltner extreme: trigger "reenter" = the first close back inside the band after
a close outside it (still on the extreme side of the mean); trigger "outside" =
a close outside the band. Optional RSI-extreme confirmation and optional HTF
EMA filter. Exits: take-profit at the band mean (a resting limit that follows
the mean every bar), a fixed hard stop entry -/+ k x ATR, and a time stop.

Built to have low correlation with trend-following templates. Shared engine
machinery for fills / costs / funding / sizing / MTF. Strictly causal (bands,
ADX, CHOP, RSI and ATR at a bar use bars <= that bar; orders act from the next
bar). Defaults were chosen on development data only (before the holdout); the Choppiness
regime was the only one with a positive zero-cost dev edge (see docs/research/templates/).
"""
from __future__ import annotations

from . import _family as B

G_REG, G_SIG, G_EXIT = "Filter regime (range)", "Sinyal fade", "Exit"
REGIMES = ["adx", "chop", "adx_chop", "off"]

PARAMS: list[dict] = [
    *B.direction_params(),
    B.c("mr_regime", "Filter regime", "chop", REGIMES, G_REG,
        help="adx = ADX di bawah batas; chop = Choppiness Index di atas batas; adx_chop = keduanya; off = tanpa filter."),
    B.i("mr_adx_len", "Panjang ADX", 14, 5, 50, G_REG),
    B.f("mr_adx_max", "ADX maksimum (range)", 20.0, 5.0, 50.0, 0.5, G_REG),
    B.i("mr_chop_len", "Panjang Choppiness", 14, 5, 100, G_REG),
    B.f("mr_chop_min", "Choppiness minimum (range)", 55.0, 30.0, 80.0, 0.5, G_REG, tunable=True),
    B.c("mr_band", "Jenis band", "bb", ["bb", "kc"], G_SIG,
        help="bb = Bollinger (SMA +/- k x stdev); kc = Keltner (EMA +/- k x ATR)."),
    B.i("mr_len", "Panjang band (mean)", 20, 5, 200, G_SIG, tunable=True),
    B.f("mr_mult", "Lebar band (k)", 2.0, 0.5, 5.0, 0.1, G_SIG, tunable=True),
    B.c("mr_trigger", "Pemicu entry", "reenter", ["reenter", "outside"], G_SIG,
        help="reenter = close pertama kembali ke dalam band setelah close di luar band; outside = close di luar band."),
    B.b("mr_use_rsi", "Konfirmasi RSI ekstrem", False, G_SIG),
    B.i("mr_rsi_len", "Panjang RSI", 14, 2, 50, G_SIG),
    B.f("mr_rsi_os", "RSI oversold (long)", 30.0, 5.0, 50.0, 1.0, G_SIG),
    B.f("mr_rsi_ob", "RSI overbought (short)", 70.0, 50.0, 95.0, 1.0, G_SIG),
    B.i("mr_atr_len", "Panjang ATR (stop)", 14, 2, 100, G_EXIT),
    B.f("mr_stop_atr_mult", "Stop keras (x ATR)", 2.0, 0.25, 10.0, 0.25, G_EXIT, tunable=True,
        help="Stop tetap = harga entry -/+ k x ATR saat entry."),
    B.i("mr_max_bars", "Time stop (bar)", 20, 0, 500, G_EXIT, tunable=True,
        help="Tutup di close setelah sekian bar bila TP (mean) / stop belum kena. 0 = mati."),
    *B.htf_params(False, 200, "same", tunable_len=False),
    *B.risk_params(),
    *B.sizing_params(),
    *B.mtf_params(),
    *B.engine_params(),
]


def _cross(p: dict) -> list[str]:
    errs = []
    if p["mr_rsi_os"] >= p["mr_rsi_ob"]:
        errs.append("mr_rsi_os must be < mr_rsi_ob")
    return errs


def _lookbacks(p: dict) -> int:
    return max(p["mr_len"] * (3 if p["mr_band"] == "kc" else 1), p["mr_adx_len"] * 6, p["mr_chop_len"],
               p["mr_rsi_len"] * 3, p["mr_atr_len"] * 3)


_T = B.FamilyTemplate(
    template_id="mean_reversion_range",
    name="Mean reversion (range)",
    description=(
        "Counter-trend: hanya aktif saat filter regime menyatakan pasar sideways (ADX rendah dan/atau "
        "Choppiness tinggi). Fade ekstrem Bollinger/Keltner (opsional konfirmasi RSI) kembali ke rata-rata. "
        "Exit: TP di mean band (limit yang mengikuti mean), stop keras k x ATR, dan time stop. Tujuannya "
        "korelasi rendah dengan strategi trend. Mesin fill/biaya/funding/ukuran posisi sama dengan Rosyade. "
        "Default (regime Choppiness > 55, BB 20x2 re-enter, stop 2 ATR, time "
        "stop 20 bar) dipilih di data development saja."),
    family="mean_reversion", params=PARAMS, cross_check=_cross, lookbacks=_lookbacks)
_T.export(globals())

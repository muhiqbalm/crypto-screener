"""Donchian breakout template (trend following), engine strategy_family "donchian".

Long on a close above the highest high of the previous N bars, short on a close
below the lowest low of the previous N bars (fill at the signal-bar close, like
Rosyade). Exits: a close beyond the opposite M-bar channel (at that close) and a
chandelier ATR trailing stop (highest high since entry - k x ATR for a long, a
resting stop that only ratchets in the trade's favour; its value at entry is the
initial hard stop). Optional HTF EMA trend filter on closed higher-TF bars.

Fills, costs, funding, liquidation, sizing (margin / risk / vol_target) and MTF
entry timing are the shared engine machinery. Strictly causal: the channels
exclude the signal bar, stops set at a bar close only act from the next bar.
Defaults were chosen on development data only (before the holdout): 29 coins x 4H,
2020-03 .. min(2025-07-06, own 80% point), median Sharpe across coins; see
docs/research/templates/README.md. Sizing default = risk 1% of equity per trade at the
initial ATR stop (cap 2x notional): at a fixed 2x notional the dev drawdowns were ~-95%.
"""
from __future__ import annotations

from . import _family as B

G_SIG, G_EXIT = "Sinyal breakout", "Exit & trailing stop"

PARAMS: list[dict] = [
    *B.direction_params(),
    B.i("dc_entry_len", "Channel entry N (bar)", 100, 5, 300, G_SIG, tunable=True,
        help="Long saat close > high tertinggi N bar sebelumnya; short saat close < low terendah N bar sebelumnya."),
    B.i("dc_exit_len", "Channel exit M (bar)", 50, 2, 200, G_EXIT, tunable=True,
        help="Long ditutup saat close < low terendah M bar sebelumnya (short: close > high tertinggi M bar)."),
    B.i("dc_atr_len", "Panjang ATR", 20, 2, 100, G_EXIT),
    B.f("dc_atr_mult", "Trailing stop (x ATR)", 4.0, 0.5, 10.0, 0.1, G_EXIT, tunable=True,
        help="Stop = ekstrem sejak entry -/+ k x ATR, hanya bergerak searah profit. Nilai saat entry = stop awal."),
    *B.htf_params(True, 50, "1d", tunable_len=True),
    *B.risk_params(),
    *B.sizing_params(sizing_mode="risk", risk_per_trade_pct=1.0, max_notional_mult=2.0),
    *B.mtf_params(),
    *B.engine_params(),
]


def _cross(p: dict) -> list[str]:
    return []


def _lookbacks(p: dict) -> int:
    return max(p["dc_entry_len"], p["dc_exit_len"], p["dc_atr_len"] * 3)


_T = B.FamilyTemplate(
    template_id="donchian_breakout",
    name="Donchian breakout",
    description=(
        "Trend following klasik (Turtle). Long saat close menembus high tertinggi N bar sebelumnya, short saat "
        "close menembus low terendah N bar sebelumnya; opsional filter trend EMA timeframe besar. Exit saat "
        "close menembus channel lawan M bar, atau kena trailing stop ATR (chandelier). Fill, biaya, funding, "
        "ukuran posisi dan timing entry MTF memakai mesin yang sama dengan Rosyade. Default (N100/M50, stop 4 "
        "ATR, filter EMA-50 1D, risiko 1%/trade) dipilih di data development saja."),
    family="donchian", params=PARAMS, cross_check=_cross, lookbacks=_lookbacks)
_T.export(globals())

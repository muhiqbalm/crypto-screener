# New Lab templates: Donchian breakout + Mean reversion (range), 2026-11-11

Both templates run on engine `strategy_family` (`feat/new-templates`, on top of 20c5e29). They share the Rosyade
machinery: fills, costs, funding, liquidation, resting stops/limits, sizing modes and MTF entry timing.

**Nothing here touched a holdout.** Every number is development data only. No `validate` was run and no
production `lab.db` was written. The work ran in `/tmp/templates` on a copy of the Lab cache.

- **Dev cutoff** per coin and TF = min(2025-07-06T04:00Z, the start of the last 20% of the coin's own range).
  - 2025-07-06 is the holdout start of every earlier ETH/BTC look.
  - The second term is the Lab rule.
- **Evaluation** starts 2020-03 (or at listing + warm-up). Coins with less than 365 dev days are skipped:
  HYPE, RENDER, and on 1D also TIA and WIF.
- **Costs:** 0.05% fee + 0.05% slippage per side, with funding.

## Rosyade bit-identity

`bitident-base-20c5e29.txt` (base backend + production engine 20c5e29) and `bitident-new.txt` (new backend + new
engine) are byte-identical.

- Range: full 2020-01 → 2026-11-09.
- SHA-256 covers every trade (times, prices, qty, reason, PnL, fees, funding) and every equity point.
- Nine cases:
  - 4H-ETH-Basic, 4H-ETH-v2, 4H-BTC-Opt, 4H-SOL-Opt;
  - two VT60 sized presets;
  - an MTF `ltf_pullback` variant;
  - a `risk` sizing variant;
  - 1D SOL.

## Choosing defaults (dev only, cross-sectional)

`grid.json` and `grid2.json` hold 27 coins × 4H per candidate. The pick was by **median Sharpe across coins**,
not by any single coin.

- **Donchian.** Longer channels were better: N100/M50/k4 gave median Sharpe 0.28, against −0.14 for N55/M20/k3
  and 0.08 for N20/M10.
  - **The HTF filter is mixed.** Without the HTF filter, median Sharpe was 0.38 (vs 0.28 with it), but median
    DD and the share of positive coins were about the same. The 1D EMA-50 filter is kept as the default
    because it is the classic choice.
  - **2x notional is fatal.** At a fixed 2x notional, median dev DD was about −96% for every Donchian variant,
    even at zero cost (median Sharpe 0.42).
  - **Risk sizing fixes the drawdown.** Risk 1% per trade at the initial ATR stop (cap 2x) has median DD −8%,
    PF 1.26, and 67% of coins with positive CAGR. This is the default sizing.
  - **Leverage default is 2.** That puts liquidation near −50%; at 4x it is about −25%, which a 4-ATR stop on
    volatile alts can exceed.
- **Mean reversion.** Every ADX-regime variant lost even at zero cost (M1 zero-cost median Sharpe −0.24).
  - **Choppiness > 55 is the only regime with a positive gross edge.** Zero-cost median Sharpe was 0.21 and PF
    1.06. Costs remove it: net median Sharpe 0.05, PF 0.98.
  - **Tighter filters trade too little.** CHOP > 60 and Keltner bands had better Sharpe on fewer than 20
    trades per coin in five years, which can never reach the Lab's 30-holdout-trade bar.
  - **Default:** Choppiness > 55, BB 20×2, re-enter, 2-ATR stop, 20-bar time stop, 1x notional.

## Dev scan with the defaults (`scan.json`)

| template | TF | coins | median Sharpe | IQR | CAGR > 0 | median CAGR | median maxDD | median PF | median trades |
|---|---|---|---|---|---|---|---|---|---|
| Donchian | 4H | 27 | 0.38 | −0.07 … 0.74 | 67% | +1.9% | −8.4% | 1.26 | 101 |
| Donchian | 1D | 25 | 0.18 | −0.20 … 0.49 | 60% | +0.4% | −4.0% | 1.39 | 12 |
| Mean rev. | 4H | 27 | 0.05 | −0.35 … 0.14 | 37% | −0.3% | −30.2% | 0.98 | 59 |
| Mean rev. | 1D | 25 | −0.10 | −0.55 … 0.34 | 40% | −1.4% | −22.6% | 0.52 | 6 |

For reference, 4H-ETH-Basic (Rosyade, 2x) on ETH 4H over the same dev window had Sharpe 2.20, CAGR +305% and
DD −37%.

- **Donchian returns are small.** At risk 1% the notional is usually 0.25–0.5x. Scale with
  `risk_per_trade_pct`. Sharpe and PF are the comparable numbers.
- There was one liquidation (AAVE 4H). There were none on 1D.

### Daily-return correlation with 4H-ETH-Basic (ETH 4H), dev

| template / coin | 4H | 1D |
|---|---|---|
| Donchian ETH | 0.50 | 0.13 |
| Donchian BTC | 0.27 | 0.09 |
| Mean reversion ETH | −0.02 | −0.04 |
| Mean reversion BTC | −0.03 | −0.15 |

Donchian vs mean reversion on the same coin (4H): median correlation is −0.03 across 27 coins.

## Read

- **Donchian** is a weak but broad positive trend edge on dev: 18 of 27 coins positive, PF 1.26.
  - It correlates with Rosyade on ETH 4H (0.50), as two trend systems should.
  - On BTC it is lower (0.27), and on 1D it is low.
- **Mean reversion in range** is nearly uncorrelated with Rosyade and with Donchian. It has no net edge on dev
  with the defaults: it is cost-bound, and only a handful of coins (PEPE, INJ, XRP, DOT, NEAR) look positive.
  - Treat it as a diversifier to research, not a candidate.
- Validation (holdout, walk-forward, MC, cost stress, sensitivity) is left to the team. Every Lab mode supports
  both templates.

## Re-run

```
cd /tmp/templates/scripts   # VPS; engine = feat/new-templates, backend = feat/new-templates
LAB_ENGINE_PATH=/tmp/templates/engine nice -n 10 /root/bmtm-v2/venv/bin/python devscan.py grid|grid2|scan
LAB_ENGINE_PATH=<engine> TPL_REPO=<backend> nice -n 10 /root/bmtm-v2/venv/bin/python bitident.py
```

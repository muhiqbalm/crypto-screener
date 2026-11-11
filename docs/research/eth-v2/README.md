# 4H-ETH-v2: more robust ETH 4H params, same Rosyade-family logic (2026-11-11)

This folder is research only. No template logic was added, and the live Pine, the webhook and `src/trading/` are untouched.

## Files

- `prereg.json`: the pre-registration, committed in 740b001 **before** the holdout look. It holds the selection rules, dev statistics, search effort and exact params.
- `dev/`: development-period outputs, all before 2025-07-06:
  - `wf_*.json`: walk-forward runs for 5 search variants.
  - `grid.json`: the plateau grid.
  - `final.json`: the ATR-gate check and sensitivity results.
- `holdout-results.json`: one Lab `validate` run each for Basic (reference) and 4H-ETH-v2, run on a /tmp copy of the production lab.db.
- `scripts/`: everything that produced the above. They run on the VPS under /tmp/ethv2 with engine a259ceb. `make_manifest.py` builds `ops/lab_presets_seed.json`.

## Method (dev only)

1. **Five search variants.** Each variant got a 16-fold rolling walk-forward re-optimisation using the Lab optimiser:
   - 12-month train and 3-month test windows; the test windows tile 2021-07 → 2025-07.
   - 30 TPE trials per fold, then a 120-trial final optimisation.
   - 3,000 optimiser trials in total.

   The variants:

   | Variant | Search space | HTF EMA |
   |---|---|---|
   | A | Lab tunables | 4h |
   | B | Lab tunables | 1d |
   | C | 6-param "lite" | 1d |
   | D | 6-param "lite" | 4h |
   | E | lite + the template's ATR% volatility gate | 1d |

2. **Robust rank for fixed param sets.**
   - Gates: at least 110 trades, no liquidation, net return at 2× costs above 0, and at most 3 fragile params.
   - Score: (share of positive quarters, all and last 8) × Sharpe at 2× costs, halved when the Monte Carlo 95th-percentile DD is beyond −50%.
   - A plateau rule picks the cell with the best **minimum** score over its neighbourhood.
3. **Findings on dev.**
   - Inside every variant, the robust rank picks Basic itself. Dev is in-sample for Basic, whose defaults were hand-tuned on this history, so dev cannot show Basic's decay.
   - Fold winners agree only on `entry_vol_mult`, `adx_strong_threshold` and `chop_limit` (CV ≤ 0.26). Every other parameter drifts heavily (CV 0.4–1.5).
   - The later folds and the non-Basic robust trials in A and B point the same way: a stricter volume filter and a wider short stop.
   - Grid of `entry_vol_mult` × `short_sl_pct` × HTF:
     - Plateau at vol 1.8–2.2 × short SL 5–9%: every cell passes the gates and beats Basic.
     - The pick is the centre, **vol 2.0 / short SL 7%**.
     - 1d EMA-32 gives the same results as 4h EMA-194, so it is not used.
     - Vol ≥ 2.4 scores higher but gives fewer than 110 trades, so it was not registered.
   - The ATR% gate does not form a plateau. The rule picks 0.6, which filters nothing, so there is no second candidate.

## Results

Costs are 0.05% commission plus 0.05% slippage per side, with funding on. Sizing is the template's: 4× leverage at 50% margin.

| | 4H-ETH-Basic | 4H-ETH-v2 |
|---|---|---|
| Change vs Basic | – | `entry_vol_mult` 1.6→2.0, `short_sl_pct` 3→7 |
| Dev WF OOS (procedure, variant A, 16 folds) | +2,202% · 2×: +1,288% · 14/16 folds + · worst fold −14.3% | same procedure |
| Dev fixed params 2021-07→2025-07: trades | 174 | 130 |
| Dev: PF / Sharpe | 1.58 / 1.86 | 1.61 / 1.95 |
| Dev: net at 2× costs / Sharpe at 2× | +3,703% / 1.64 | +4,878% / 1.77 |
| Dev: positive quarters, all / last 8 | 15/16 · 8/8 | 15/16 · 8/8 |
| Dev: last-8-quarter net at 2× | **+390%** | +278% |
| Dev: worst quarter | −22.6% | −26.3% |
| Dev: MC DD95 | −63.1% | −59.9% |
| Dev: fragile params / mean stability | 0 / 0.954 | 0 / 0.972 |
| **Holdout** 2025-07-06 → 2026-11-09 (contaminated): net | +18.8% | **+153.7%** |
| Holdout: PF / Sharpe | 1.03 / 0.52 | 1.32 / 1.36 |
| Holdout: max DD | −73.8% | −52.9% |
| Holdout: trades / win rate | 72 / 29% | 50 / 38% |
| Holdout: net at 2× costs | −9.6% | +109.1% |
| Holdout: zero-cost net | +68.5% | +188.8% |
| Full-range MC DD95 | −68.1% | −62.7% |
| Lab verdict | FAIL (PF, MC DD, 2× cost) | FAIL (MC DD only) |

## Reading

- **The holdout is contaminated.** The ETH 4h holdout has been viewed at least 5 times, and the earlier README told this research that costs ate Basic's holdout edge. That knowledge may have pushed the criteria toward cost robustness. Treat +153.7% as weak evidence, not as an expected return.
- **What is credible.**
  - v2 is a two-parameter change from Basic and sits in the centre of a broad dev plateau, with 0 fragile params.
  - Its mechanism is plausible:
    - Fewer, better-confirmed entries cut cost drag; holdout trades fell from 72 to 50.
    - A 7% short stop sits above ETH 4h noise, where the 3% stop is about 1.6× the average bar range.
  - It passed all of its pre-registered "not worse than Basic" criteria on the holdout.
- **What is not credible.**
  - Dev does not favour v2 on recent returns: its last-8-quarter net at 2× costs is lower than Basic's.
  - MC DD95 is still beyond −50% because the sizing is 2× notional. That is a sizing question and was not tested here.
- **Real test: forward paper.** `ops/lab_seed_presets.py` adds 4H-ETH-v2 with a 10k paper watch next to 4H-ETH-Basic, 4H-BTC-Opt and 4H-SOL-Opt, all with the same mirror sizing. Review after at least 30 paper trades per preset.

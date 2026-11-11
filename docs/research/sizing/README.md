# Position sizing for the 4H Rosyade-family paper presets (2026-11-11)

Research and paper only. The live Pine strategy, the webhook, `src/trading/` and the live sizing are untouched.

**Question.** Which sizing rule makes the four paper presets (4H-ETH-Basic, 4H-ETH-v2, 4H-BTC-Opt, 4H-SOL-Opt) pass the Lab honesty checks, especially MC DD95 ≥ −50%, while keeping as much risk-adjusted return as possible?

**Short answer.**

- The drawdown is a sizing property, not a signal property. With fixed notional, the Sharpe barely moves with size: ETH-Basic dev Sharpe is 1.86 at 0.5×, 1.89 at 1× and 1.92 at 2×. MC DD95 scales almost linearly with size: −21%, −38% and −63%.
- At 2× notional, the trade-order Monte Carlo falls below −50% in 35–59% of reshuffles for ETH and SOL. At 1× it does so in 0–1%.
- Both pre-registered rules pass the MC DD95 check on every preset: R1 is 1× fixed notional, R2 is a 60% vol target.
  - **4H-ETH-v2 passes the full Lab verdict** under both rules. It is the first PASS in the Lab.
  - 4H-ETH-Basic still fails on holdout PF (1.12 under R1, 1.18 under R2).
  - BTC-Opt and SOL-Opt still fail on fewer than 30 holdout trades. Sizing cannot fix either problem.
- By the pre-registered tie-break, **R2 (vol target 60%) is the formal pick.** It beat R1 on holdout Sharpe for both ETH presets (0.93 vs 0.63 and 1.55 vs 1.46), and both passed MC DD.
- The margin is small. On dev the two rules are equal within noise, and the holdout is contaminated, so this is weak evidence.
- R1 needs no deploy, because the paper engine mirrors it natively. R2 needs the sizing engine and the backend deployed.

## Files

- `prereg.json`: rules, selection rule, dev statistics and decision criteria. Committed in a912561 **before** the holdout look.
- `dev/dev_grid.json`: 37 sizing rules × 4 presets, at 1× and 2× costs, dev only.
- `dev/dev_years.json`: per-year stability of the leading rules.
- `dev/bitident_*.txt`: the default sizing is bit-identical to the production engine a259ceb.
- `holdout-results.json` and `holdout-log.txt`: 8 Lab `validate` runs (4 presets × R1/R2) on a /tmp copy of production lab.db.
- `tables.md`: all result tables. They are also below.
- `scripts/`:
  - `common.py`, `dev_grid.py`, `dev_years.py`: the dev research.
  - `bitident.py`: the bit-identity check.
  - `make_prereg.py`, `holdout.py`: pre-registration and the holdout runs.
  - `check_watch_mirror.py`: on real data, the paper mirror's notional multiple matches the engine's vol-target rule on all 148 trades.
  - `make_manifest.py`: builds `ops/lab_presets_sizing_{1x,vt}_seed.json`.
  - `make_tables.py`: builds the tables.

## How sizing works today

| Where | Rule | The 4 presets |
|---|---|---|
| Engine `strategy/state.py` `open_position` | notional = equity × `portfolio_risk`% × `leverage`. It ignores the stop distance. Liquidation is isolated margin = notional / leverage. | 50% × 4 = **2× equity**. 1× is margin 25% at 4×; the liquidation price is unchanged. |
| Paper `src/lab/paper.py` `open_position` | qty = balance × `risk_pct`% / \|fill − SL\|, capped at balance × `leverage_max` / fill | The seed's "mirror" uses risk_pct 100 with leverage_max = 2.0, so the cap always binds and paper notional is 2×. |

The hard SLs are wide on one side: ETH long 13%, SOL long 29%, BTC short 26%. At 2×, a single long stopped out on ETH costs about 26% of equity, before gaps.

## Sizing families tested on dev

Development data runs from 2020 to the day before each holdout start: 2025-07-06 for ETH and BTC, 2025-08-26 for SOL. The engine gained these options on branch `feat/sizing-research` (20c5e29). They are all causal, and the default is bit-identical:

| Family | Engine params | Notes |
|---|---|---|
| Fixed notional 0.5–2× | `portfolio_risk` 12.5–50 at leverage 4 | Uses existing params; no new code. |
| Fixed-fractional | `sizing_mode=risk`, `risk_per_trade_pct` 0.5–8, cap `max_notional_mult` 2 | Equity × risk% / hard-SL distance. |
| Vol target | `sizing_mode=vol_target`, `vol_target_pct` 10–80, `vol_lookback` 30/60/120, cap 2 | Realised vol of the base-TF closes up to the decision bar. An MTF fill uses bar i−1. |
| DD de-risk | `dd_derisk_pct` 20, `dd_derisk_mult` 0.5, on top of any mode | Uses closed equity against its running peak. |

What dev says:

1. **Fixed notional.** Sharpe is flat in size, and MC DD95 is roughly proportional to it. The limit is crossed between 1.25× and 1.5× for the ETH presets. With a 10 pp buffer, the largest passing size is **1×**.
2. **Fixed-fractional on the hard stop is worse** for ETH (Sharpe 1.64 vs 1.89) and for SOL (1.24 vs 1.37).
   - The long stop (13% or 29%) is far from the risk actually realised, because trailing and structure exits come first. Longs therefore get under-sized.
   - Only BTC gains slightly.
   - It is the paper engine's native rule, but not a good one for these presets.
3. **Vol target 60% (lookback 60)** is close to 1× fixed: ETH-Basic Sharpe 1.90 vs 1.89, v2 1.89 vs 1.80, SOL 1.40 vs 1.37, BTC 1.01 vs 1.05.
   - Per year the wins are split. VT trims the high-vol bull years (2021–22) and adds in quiet years (2023–25).
   - Lookback 120 looked better on ETH. It was not selected on that basis, and 60 was fixed a priori.
4. **The DD de-risk rule** (1.5×, halved below a −20% closed-equity DD) has the best *rule-aware* MC DD95 per unit of CAGR.
   - On the real dev path it cut return (Sharpe 1.82 vs 1.91) and did not reduce the realised max DD (−28.6% vs −28.8%).
   - Its benefit exists only under the iid reshuffle. The Lab's MC (an ROE reshuffle) cannot evaluate it, and paper cannot mirror it. **Not registered.**

Selection rule, pre-registered: per family, the largest level whose **worst** dev MC DD95 over the four presets is ≥ −40%. This gave R1 = fixed 1× and R2 = VT 60%.

Decision criterion, also pre-registered: R2 replaces R1 only if, on the holdout, R2 has a higher Sharpe than R1 on **both** ETH presets **and** passes MC DD95 on both.

## Results

### Development period (before the holdout), per preset x sizing rule

Costs 0.05% + 0.05% per side, funding on. CAGR and Sharpe from the mark-to-market equity curve. MC DD95 = 5th percentile of 1,000 trade-order reshuffles (rule-aware for the DD rule). P(DD≥50%) = share of reshuffles that ever fall 50% (risk of ruin proxy). CAGR/|MC DD95| = return per unit of tail drawdown. **Bold** = the two pre-registered rules.

#### 4H-ETH-Basic

| Sizing rule | Avg notional | CAGR % | Max DD % | MC DD95 % | P(DD≥50%) | Sharpe | Sharpe 2× cost | Calmar | CAGR/\|MC DD95\| |
|---|---|---|---|---|---|---|---|---|---|
| 0.5x notional | 0.50× | 41.5 | -10.6 | -21.0 | 0.0% | 1.86 | 1.64 | 3.91 | 1.98 |
| **1x notional** | 1.00× | 92.8 | -20.0 | -38.1 | 0.0% | 1.89 | 1.67 | 4.63 | 2.43 |
| 1.5x notional | 1.50× | 152.6 | -28.8 | -52.0 | 7.2% | 1.91 | 1.68 | 5.30 | 2.94 |
| 2x notional (current) | 2.00× | 220.1 | -36.9 | -63.1 | 34.2% | 1.92 | 1.69 | 5.97 | 3.49 |
| 1% risk/trade | 0.22× | 15.2 | -5.7 | -11.5 | 0.0% | 1.64 | 1.43 | 2.66 | 1.33 |
| 2% risk/trade | 0.44× | 31.5 | -11.2 | -21.8 | 0.0% | 1.64 | 1.43 | 2.82 | 1.45 |
| 4% risk/trade | 0.87× | 67.2 | -21.4 | -38.9 | 0.2% | 1.65 | 1.44 | 3.14 | 1.73 |
| 6% risk/trade | 1.31× | 104.9 | -30.6 | -53.3 | 9.9% | 1.64 | 1.42 | 3.42 | 1.97 |
| VT 30% | 0.54× | 41.4 | -15.2 | -20.1 | 0.0% | 1.89 | 1.65 | 2.73 | 2.06 |
| **VT 60%** | 1.05× | 88.5 | -27.7 | -36.2 | 0.0% | 1.90 | 1.66 | 3.20 | 2.44 |
| VT 80% | 1.34× | 122.8 | -31.5 | -44.4 | 1.4% | 1.94 | 1.69 | 3.90 | 2.77 |
| 1.5x notional +DD20/0.5 | 1.46× | 134.4 | -28.6 | -39.5 | 0.0% | 1.82 | 1.58 | 4.70 | 3.40 |
| 2x notional +DD20/0.5 | 1.73× | 134.7 | -36.7 | -47.2 | 2.1% | 1.62 | 1.33 | 3.67 | 2.85 |

#### 4H-ETH-v2

| Sizing rule | Avg notional | CAGR % | Max DD % | MC DD95 % | P(DD≥50%) | Sharpe | Sharpe 2× cost | Calmar | CAGR/\|MC DD95\| |
|---|---|---|---|---|---|---|---|---|---|
| 0.5x notional | 0.50× | 36.1 | -11.2 | -20.7 | 0.0% | 1.78 | 1.61 | 3.21 | 1.74 |
| **1x notional** | 1.00× | 78.9 | -21.0 | -37.3 | 0.3% | 1.80 | 1.63 | 3.76 | 2.12 |
| 1.5x notional | 1.50× | 127.3 | -29.8 | -51.3 | 6.3% | 1.81 | 1.64 | 4.27 | 2.48 |
| 2x notional (current) | 2.00× | 179.9 | -37.8 | -62.8 | 35.2% | 1.82 | 1.65 | 4.76 | 2.87 |
| 1% risk/trade | 0.11× | 7.3 | -2.8 | -5.7 | 0.0% | 1.70 | 1.54 | 2.60 | 1.29 |
| 2% risk/trade | 0.23× | 15.0 | -5.6 | -11.2 | 0.0% | 1.70 | 1.54 | 2.69 | 1.34 |
| 4% risk/trade | 0.45× | 31.1 | -10.8 | -21.3 | 0.0% | 1.70 | 1.54 | 2.87 | 1.46 |
| 6% risk/trade | 0.68× | 48.3 | -15.8 | -30.5 | 0.0% | 1.70 | 1.54 | 3.06 | 1.58 |
| VT 30% | 0.56× | 38.3 | -17.5 | -20.1 | 0.0% | 1.85 | 1.67 | 2.18 | 1.90 |
| **VT 60%** | 1.08× | 83.0 | -29.2 | -35.3 | 0.1% | 1.89 | 1.70 | 2.84 | 2.35 |
| VT 80% | 1.38× | 110.3 | -33.0 | -43.4 | 1.4% | 1.89 | 1.70 | 3.34 | 2.54 |
| 1.5x notional +DD20/0.5 | 1.42× | 118.4 | -29.8 | -39.4 | 0.1% | 1.76 | 1.51 | 3.98 | 3.00 |
| 2x notional +DD20/0.5 | 1.82× | 146.6 | -34.9 | -47.3 | 2.5% | 1.69 | 1.52 | 4.20 | 3.10 |

#### 4H-BTC-Opt

| Sizing rule | Avg notional | CAGR % | Max DD % | MC DD95 % | P(DD≥50%) | Sharpe | Sharpe 2× cost | Calmar | CAGR/\|MC DD95\| |
|---|---|---|---|---|---|---|---|---|---|
| 0.5x notional | 0.50× | 6.6 | -8.3 | -7.7 | 0.0% | 1.03 | 0.91 | 0.79 | 0.86 |
| **1x notional** | 1.00× | 13.1 | -15.3 | -14.9 | 0.0% | 1.05 | 0.92 | 0.85 | 0.88 |
| 1.5x notional | 1.50× | 19.5 | -21.3 | -21.8 | 0.0% | 1.06 | 0.93 | 0.92 | 0.89 |
| 2x notional (current) | 2.00× | 25.8 | -26.6 | -28.5 | 0.0% | 1.07 | 0.94 | 0.97 | 0.91 |
| 1% risk/trade | 0.17× | 3.7 | -3.8 | -3.2 | 0.0% | 0.99 | 0.92 | 0.98 | 1.15 |
| 2% risk/trade | 0.34× | 7.4 | -7.0 | -6.4 | 0.0% | 1.00 | 0.93 | 1.05 | 1.16 |
| 4% risk/trade | 0.68× | 14.7 | -12.3 | -12.5 | 0.0% | 1.03 | 0.96 | 1.20 | 1.18 |
| 6% risk/trade | 1.02× | 21.9 | -16.4 | -18.4 | 0.0% | 1.06 | 0.98 | 1.34 | 1.20 |
| VT 30% | 0.68× | 6.7 | -10.7 | -10.7 | 0.0% | 0.95 | 0.79 | 0.63 | 0.63 |
| **VT 60%** | 1.32× | 13.7 | -18.2 | -18.8 | 0.0% | 1.01 | 0.85 | 0.75 | 0.73 |
| VT 80% | 1.64× | 17.9 | -19.0 | -22.4 | 0.0% | 1.06 | 0.91 | 0.94 | 0.80 |
| 1.5x notional +DD20/0.5 | 1.50× | 19.5 | -21.3 | -21.8 | 0.0% | 1.06 | 0.93 | 0.92 | 0.89 |
| 2x notional +DD20/0.5 | 2.00× | 25.8 | -26.6 | -26.6 | 0.0% | 1.07 | 0.94 | 0.97 | 0.97 |

#### 4H-SOL-Opt

| Sizing rule | Avg notional | CAGR % | Max DD % | MC DD95 % | P(DD≥50%) | Sharpe | Sharpe 2× cost | Calmar | CAGR/\|MC DD95\| |
|---|---|---|---|---|---|---|---|---|---|
| 0.5x notional | 0.50× | 19.6 | -15.6 | -16.7 | 0.0% | 1.38 | 1.33 | 1.25 | 1.17 |
| **1x notional** | 1.00× | 38.8 | -28.9 | -31.3 | 0.0% | 1.37 | 1.32 | 1.34 | 1.24 |
| 1.5x notional | 1.50× | 57.3 | -40.1 | -44.0 | 1.4% | 1.36 | 1.31 | 1.43 | 1.30 |
| 2x notional (current) | 2.00× | 74.6 | -49.8 | -55.4 | 14.7% | 1.34 | 1.29 | 1.50 | 1.35 |
| 1% risk/trade | 0.06× | 1.8 | -1.8 | -2.1 | 0.0% | 1.24 | 1.19 | 1.04 | 0.85 |
| 2% risk/trade | 0.11× | 3.6 | -3.5 | -4.2 | 0.0% | 1.24 | 1.19 | 1.05 | 0.85 |
| 4% risk/trade | 0.22× | 7.2 | -6.8 | -8.4 | 0.0% | 1.23 | 1.18 | 1.06 | 0.87 |
| 6% risk/trade | 0.34× | 10.9 | -10.1 | -12.4 | 0.0% | 1.23 | 1.18 | 1.08 | 0.88 |
| VT 30% | 0.40× | 17.1 | -14.0 | -13.0 | 0.0% | 1.41 | 1.37 | 1.23 | 1.31 |
| **VT 60%** | 0.79× | 33.0 | -25.9 | -24.8 | 0.0% | 1.40 | 1.36 | 1.27 | 1.33 |
| VT 80% | 1.06× | 43.0 | -33.0 | -32.0 | 0.0% | 1.40 | 1.35 | 1.31 | 1.35 |
| 1.5x notional +DD20/0.5 | 1.43× | 53.3 | -36.6 | -37.6 | 0.0% | 1.32 | 1.27 | 1.46 | 1.42 |
| 2x notional +DD20/0.5 | 1.83× | 63.9 | -45.7 | -45.0 | 0.6% | 1.27 | 1.15 | 1.40 | 1.42 |

### Holdout (contaminated, one Lab `validate` run per preset x rule)

Holdout 2025-07-06 → 2026-11-09 (SOL from 2025-08-26). MC DD95 and P(DD≥50%) are the Lab's full-range numbers (dev + holdout), i.e. what the verdict checks.

| Preset | Sizing | Net % | PF | Max DD % | Sharpe | Net 2× cost % | Trades | MC DD95 % | P(DD≥50%) | Lab verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| 4H-ETH-Basic | 2× (current) | 18.8 | 1.03 | -73.8 | 0.52 | -9.6 | 72 | -68.1 | 58.7% | FAIL (PF, MC DD, 2x cost) |
| 4H-ETH-Basic | **R1** fixed 1× | 23.8 | 1.12 | -47.5 | 0.63 | 7.8 | 73 | -41.7 | 0.8% | FAIL (PF) |
| 4H-ETH-Basic | **R2** VT 60% | 48.5 | 1.18 | -48.5 | 0.93 | 26.3 | 73 | -42.3 | 1.2% | FAIL (PF) |
| 4H-ETH-v2 | 2× (current) | 153.7 | 1.32 | -52.9 | 1.36 | 109.1 | 50 | -62.7 | 38.2% | FAIL (MC DD) |
| 4H-ETH-v2 | **R1** fixed 1× | 82.9 | 1.62 | -31.1 | 1.46 | 65.7 | 51 | -37.6 | 0.0% | PASS |
| 4H-ETH-v2 | **R2** VT 60% | 105.6 | 1.61 | -34.1 | 1.55 | 82.9 | 51 | -38.9 | 0.1% | PASS |
| 4H-BTC-Opt | 2× (current) | 15.4 | 1.49 | -12.7 | 0.69 | 8.1 | 17 | -34.5 | 0.0% | FAIL (trades < 30) |
| 4H-BTC-Opt | **R1** fixed 1× | 8.4 | 1.55 | -6.5 | 0.71 | 4.9 | 17 | -18.6 | 0.0% | FAIL (trades < 30) |
| 4H-BTC-Opt | **R2** VT 60% | 16.8 | 1.69 | -10.1 | 0.84 | 11.0 | 17 | -23.8 | 0.0% | FAIL (trades < 30) |
| 4H-SOL-Opt | 2× (current) | 58.5 | 1.77 | -25.7 | 1.24 | 53.0 | 10 | -66.7 | 44.4% | FAIL (MC DD, trades < 30) |
| 4H-SOL-Opt | **R1** fixed 1× | 30.0 | 2.01 | -13.7 | 1.28 | 27.7 | 10 | -39.6 | 0.1% | FAIL (trades < 30) |
| 4H-SOL-Opt | **R2** VT 60% | 25.0 | 1.95 | -13.2 | 1.18 | 22.9 | 10 | -29.5 | 0.0% | FAIL (trades < 30) |

## Reading

- **The hypothesis holds.** At equal signals:
  - Going from 2× to 1× moved the full-range MC DD95 from −68.1% to −41.7% (Basic), −62.7% to −37.6% (v2) and −66.7% to −39.6% (SOL).
  - P(DD ≥ 50%) moved from 59%, 38% and 44% to 1% or less.
  - Holdout Sharpe did not fall; it rose slightly, because there is less compounding drag on the deep losses.
- **Fixed-size return is roughly proportional to size; risk is not.** v2's holdout net fell from +153.7% to +82.9% while its max DD fell from −52.9% to −31.1%.
- **PF changes with sizing.** Basic's holdout PF went 1.03 → 1.12 (R1) → 1.18 (R2).
  - PF is computed on dollar PnL, so compounding re-weights the trades.
  - VT shrank the high-vol losers. That is still below 1.2.
- **4H-ETH-Basic's realised holdout DD is still −47.5% at 1×,** deeper than its dev MC DD95 of −38%.
  - The holdout regime is worse than dev for Basic. That is a signal problem, which sizing only dampens.
- **The holdout is contaminated.** These holdouts were viewed many times before. The R2-over-R1 call rests on two Sharpe differences: +0.30 on Basic and +0.09 on v2.
- **The real test is forward paper:** the same signals at 2×, 1× and VT side by side.

## Recommendation

1. Treat sizing as the drawdown lever: **≈1× equity notional** for these presets, instead of 2×.
2. **Formal pick (pre-registered): R2, vol target 60% (lookback 60, cap 2×).** It is the better holdout Sharpe on both ETH presets, with weak evidence. **4H-ETH-v2_VT60** is the variant to watch. It is the only preset that passes every Lab check, under either rule.
3. **Seed both variants in paper now**, as cheap controls on identical signals:
   - the deploy-free `_1x` set;
   - the `_VT60` set after the engine and backend deploy.
   - Review after ≥ 30 paper trades per preset.
4. Do not seed a sized BTC variant. Its MC DD95 already passes at 2×, and its only failure is the trade count.
5. Live sizing is not changed (production freeze). For the live bot, the low-tech equivalent would be margin 25% at 4×. That is a separate decision.

## Seeding (paper only, dry-run by default, idempotent, never edits existing presets)

The existing `ops/lab_seed_presets.py` takes a new manifest:

- `ops/lab_presets_sizing_1x_seed.json` → `4H-ETH-Basic_1x`, `4H-ETH-v2_1x`, `4H-SOL-Opt_1x`.
  - Paper accounts use risk_pct 100 and leverage_max 1.0.
  - It only uses keys the current production template knows. Tested with the production code on a /tmp copy of lab.db: dry-run, apply twice, idempotent.
- `ops/lab_presets_sizing_vt_seed.json` → `4H-ETH-Basic_VT60`, `4H-ETH-v2_VT60`, `4H-SOL-Opt_VT60`.
  - Paper accounts use leverage_max 2.0. Auto-paper copies the engine's notional multiple (`watch_eval` `position.notional_mult`).
  - **This needs the deploy first.** Before the deploy, the production code refuses it with `invalid params: unknown params: ...` and writes nothing.

Labels cannot contain `-` (`presets.LABEL_RE`), so the names use `_`, for example `4H-ETH-v2_VT60`.

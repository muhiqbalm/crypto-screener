# MTF entry timing: 4H Rosyade signal, lower-TF entry (2026-11-11)

Research only. Live Pine, webhook and `src/trading/` are untouched.

## Files

- `prereg-2026-11-11.json`: pre-registration, committed (0c9d199) before any holdout look. It holds the selection rule, the dev statistics and the exact params of every evaluated config.
- `dev/`: development-period grids (111 MTF configs per coin) and the BTC/SOL 4H optimisation (walk-forward + TPE, dev only).
- `holdout-results-2026-11-11.json`: one Lab `validate` run per pre-registered config, made on a /tmp copy of lab.db.
- `presets-2026-11-11.json`: full param sets named `{TF}-{COIN}-{Label}`.
- `scripts/`: the scripts that produced all of the above (run on the VPS under /tmp/mtf).

## Holdout results (4H, costs 0.05% + 0.05% per side, funding on, limit entries use a 0.02% maker fee)

The holdout starts on 2025-07-06 for ETH and BTC, and on 2025-08-26 for SOL. It runs to 2026-11-09.

| Config | Net % | PF | Max DD % | Sharpe | Net at 2x cost % | Trades | Fill rate | Lab verdict |
|---|---|---|---|---|---|---|---|---|
| 4H-ETH-Basic | 18.8 | 1.03 | -73.8 | 0.52 | -9.6 | 72 | – | FAIL |
| 4H15M-ETH-Pullback | 9.9 | 1.03 | -61.9 | 0.43 | -16.0 | 71 | 98.6% | FAIL |
| 4H1H-ETH-Limit | 42.3 | 1.07 | -68.0 | 0.73 | 20.2 | 70 | 97.2% | FAIL |
| 4H-BTC-Opt | 15.4 | 1.49 | -12.7 | 0.69 | 8.1 | 17 | – | FAIL (trades < 30) |
| 4H-BTC-Basic (reference) | 4.3 | 1.02 | -49.6 | 0.31 | -22.6 | 72 | – | FAIL |
| 4H15M-BTC-Pullback | 55.0 | 2.69 | -13.8 | 1.62 | 44.8 | 18 | 100% | FAIL (trades < 30) |
| 4H1H-BTC-Limit | 54.6 | 2.81 | -13.1 | 1.61 | 47.6 | 17 | 100% | FAIL (trades < 30) |
| 4H-SOL-Opt | 58.5 | 1.77 | -25.7 | 1.24 | 53.0 | 10 | – | FAIL |
| 4H-SOL-Basic (reference) | -15.2 | 0.95 | -69.8 | 0.12 | -33.9 | 68 | – | FAIL |
| 4H15M-SOL-Pullback | 24.8 | 1.35 | -31.5 | 0.66 | 20.3 | 10 | 100% | FAIL |
| 4H1H-SOL-Limit | 54.2 | 1.73 | -25.4 | 1.15 | 50.7 | 10 | 100% | FAIL |

## Reading

- **Pullback entries do not help.** On the dev period, 0 of 48 pullback configs beat the baseline Sharpe for ETH and for SOL, and 2 of 48 did for BTC. On the holdout they were worse for ETH and SOL. The BTC holdout gain rests on 18 trades.
- **The limit entry at the signal close helps through costs, not through timing.**
  - For ETH the zero-cost holdout net is the same: 68.3% with the limit entry against 68.5% for the baseline.
  - The 4H1H-ETH-Limit entry gains about 0 bps on price, but it pays the maker fee and no entry slippage. That cuts the cost-to-bar-range ratio from 0.108 to 0.065.
  - The fill model needs price to trade through the limit by at least one tick within 16 hours. This filled 97–100% of signals.
- No config passes the Lab honesty verdict:
  - For ETH, holdout PF is below 1.2 and the Monte Carlo 95th-percentile DD is beyond -50%.
  - For BTC and SOL, every config has fewer than 30 holdout trades.

# Universal v0 — backtest report (2026-11-10)

Paper-only research. Everything below is computed by the code on branch `feat/universal-strategy`
(`src/lab/universal/`) on the VPS parquet cache (Binance USD-M perpetuals, 4H bars + funding),
with the same honesty pipeline as every other Strategy Lab run (`HONESTY_VERSION 2026-11.1`).

## TL;DR

- **Verdict: FAIL** (the same 7-check honesty report as single-coin Lab runs). 2 of 7 checks fail:
  - holdout profit factor **1.14** (needs >= 1.2)
  - Monte Carlo 95th-percentile drawdown **-66.8%** (needs to be shallower than -50%)
- The holdout (2025-07-24 -> 2026-11-10, ~15.5 months, locked before anything was looked at) was
  **+26.9% net after all costs**, max DD -33.6%, Sharpe 0.63, 311 trades, and still +13.2% at 2x costs.
  Over the same holdout BTC buy & hold was **-37.0%** and an equal-weight basket of the universe **-49.4%**.
- Interpretation: the strategy did what trend + momentum is supposed to do (stay mostly out / small in a
  falling market), but the edge per trade in the holdout is thin and the drawdown risk over the full
  history is too high for the Lab's risk limit. **Do not trade real money on this. Paper-trade it.**
- No parameter was tuned to make this look better. The defaults are literature defaults chosen before the
  run (see "Parameters"). The variants below were run once each for information and they **all** FAIL too.

## Setup

| | |
|---|---|
| Universe | 29 cached perps: 1000PEPE, 1000SHIB, AAVE, ADA, APT, ARB, AVAX, BNB, BTC, DOGE, DOT, ETH, FET, GALA, HYPE, INJ, LINK, LTC, NEAR, OP, RENDER, SEI, SOL, SUI, TIA, UNI, WIF, XRP, ZEC (USDT) |
| Bars | 4H, 2020-01-01 -> 2026-11-10 00:00 UTC (last complete bar) |
| Evaluated range | 2020-05-16 08:00 (first bar with >= 5 eligible coins) -> 2026-11-10 00:00, 6.5 years |
| Development segment | 2020-05-16 -> 2025-07-24 (first 80%) |
| Locked holdout | **2025-07-24 04:00 UTC -> 2026-11-10** (last 20%, same rule as the Lab lock) |
| Costs | commission 0.05% + slippage 0.05% per side on traded notional, funding charged/received at every settlement from the real funding history |
| Capital / leverage | 10,000 USDT, gross exposure capped at 1.0x (no leverage), max 35% per coin |

### Rules (Universal v0, one rule set for every coin)

1. Score every coin at each daily close (00:00 UTC): mean of vol-adjusted log returns over 7 / 30 / 90 days
   (return / (30-day realised vol x sqrt(horizon))).
2. Eligible = at least 120 days of history, real bar present, finite vol.
3. Long the top-5 eligible coins with score > 0 **and** price above its 50-day EMA (uptrend). Fewer qualify -> fewer
   positions (the rest stays in cash).
4. Weights: inverse 30-day volatility over 5 slots, then the whole book is scaled to a 40%/yr ex-ante portfolio
   volatility (60-day covariance), capped at 35% per coin and 1.0x gross.
5. Rebalance daily; trades that change a held weight by < 2% of equity are skipped.
6. Decision at the close of bar t uses data <= t only, fills at that close + slippage (no look-ahead; a unit test
   tampers with future prices and checks the weights do not change).

## Honesty report (default params)

| Check | Value | Threshold | Result |
|---|---|---|---|
| Holdout profit factor | 1.14 | >= 1.2 | FAIL |
| Holdout net return after costs | +26.92% | > 0 | pass |
| Monte Carlo 95th-pct drawdown | -66.83% | > -50% | **FAIL** |
| Holdout trades | 311 | >= 30 | pass |
| Holdout net at 2x costs | +13.24% | > 0 | pass |
| Fragile parameters | 0 of 8 | <= 3 | pass |
| Liquidations | 0 | 0 | pass |

### Segments

| Segment | Net | CAGR | Max DD | Sharpe | Vol/yr | PF | Trades | Win% | Turnover/yr | Avg gross |
|---|---|---|---|---|---|---|---|---|---|---|
| In-sample (dev) | +2023.8% | 80.2% | -48.2% | 1.65 | 40.6% | 1.46 | 1153 | 40.4 | 70.9x | 0.46 |
| **Holdout** | **+26.9%** | 20.2% | -33.6% | 0.63 | 44.2% | 1.14 | 311 | 34.1 | 87.7x | 0.55 |
| Full range | +2580.6% | 66.0% | -48.2% | 1.43 | 41.4% | 1.31 | 1460 | 39.0 | 74.2x | 0.48 |

Costs over the full range: commission 29.6k + slippage 29.6k + funding 19.9k USDT (on a curve ending at 268k).
Zero-cost reference: full +5793%, holdout +43.2% — i.e. costs and funding eat roughly a third of the holdout gross return.

Benchmarks (no costs, context only):

| | Full range | Holdout |
|---|---|---|
| Universal v0 | +2580.6% (DD -48.2%) | +26.9% (DD -33.6%) |
| BTC buy & hold | +692.1% (DD -77.1%) | -37.0% (DD -53.4%) |
| Equal-weight universe, daily rebalanced | +1287.2% (DD -82.6%) | -49.4% (DD -68.9%) |

Calendar years (strategy vs BTC): 2020* +120.9% / +207.7% · 2021 +211.3% / +59.6% · **2022 -41.8% / -64.2%** ·
2023 +133.4% / +155.9% · 2024 +131.0% / +121.1% · 2025 +15.7% / -6.4% · 2026 YTD +7.4% / -14.9%  (*from 2020-05-16).

### Walk-forward (development segment only, rolling 12m train / 3m test, fixed params)

| Test window | Net | Max DD | PF | Trades |
|---|---|---|---|---|
| 2023-11-16 -> 2024-02-16 | +48.4% | -12.4% | 3.07 | 80 |
| 2024-02-16 -> 2024-05-16 | +39.7% | -21.8% | 1.87 | 79 |
| 2024-05-16 -> 2024-08-16 | -7.9% | -20.7% | 0.76 | 67 |
| 2024-08-16 -> 2024-11-16 | +50.7% | -12.0% | 2.84 | 78 |
| 2024-11-16 -> 2025-02-16 | +2.3% | -14.9% | 1.08 | 71 |
| 2025-02-16 -> 2025-05-16 | -9.2% | -22.2% | 0.67 | 43 |

Compounded OOS +167.2%, avg PF 1.71, 4/6 folds profitable. Note the trend: the last folds and the holdout are
much weaker than 2023-2024 — the edge is decaying or regime-dependent.

### Monte Carlo

Stationary block bootstrap (mean block 20 days) of the full-range **daily portfolio returns**, 1000 paths.
(Trade reshuffling, used for single-coin runs, is not valid for a portfolio with overlapping positions.)
Drawdown: median -48.2%, 95th pct **-66.8%**, 99th pct -74.6%, P(DD beyond -50%) = 43%. Realised max DD -47.5% (daily).

### Sensitivity (dev segment, each param +-10/20%)

All 8 tunable params stable (stability 0.89-1.00, every variation profitable). The result is not a knife-edge
parameter artefact — but note the in-sample period is a huge bull run, so "every variation profitable" in-sample
says little about the future. Biggest lever is `target_vol_pct` (32% -> +1193%, 48% -> +3009% in-sample),
i.e. returns scale with risk, as expected.

### Per-coin contribution

Full range, top: ZEC +100.5k, ADA +26.5k, XRP +22.7k, NEAR +21.1k, DOGE +19.6k, 1000PEPE +18.2k.
Bottom: TIA -21.5k, LTC -15.3k, OP -12.8k, DOT -11.8k, APT -8.9k.
Holdout: ZEC +4.27k is **the whole holdout profit** (+2.69k net total). Without ZEC the holdout is roughly -1.6k
(-16%). Concentration risk is real.

## Variants (informational, each run once against the same holdout — all FAIL)

| Variant | Holdout net | Holdout PF | Holdout DD | 2x cost | MC DD p95 | Full net | Verdict |
|---|---|---|---|---|---|---|---|
| A default (long-only, daily) | +26.9% | 1.14 | -33.6% | +13.2% | -66.8% | +2581% | FAIL |
| B + short bottom-3 in downtrend | +35.2% | 1.10 | -20.5% | +9.2% | -63.1% | +981% | FAIL |
| C rebalance every 4H | +52.0% | 1.17 | -26.4% | +12.8% | -66.6% | +3019% | FAIL |
| D + BTC regime filter | +11.5% | 1.09 | -32.2% | +2.7% | -53.8% | +3094% | FAIL |
| E optimize (30 trials, WF re-optimised) | +57.1% | 1.32 | -33.8% | +41.8% | -60.8% | +9884% | FAIL |

E picked top_n 3, EMA 130d, long momentum 120d, target vol 45%. It passes the holdout PF check but still fails
the Monte Carlo drawdown check, and its walk-forward picks jump around wildly (top_n 3 -> 13 -> 6, EMA 40 -> 195),
which is a classic sign of fitting noise. Looking at five variants on one holdout is itself a mild form of
peeking, so none of these should be promoted on the strength of this table.

## Known limitations (read before trusting any number)

1. **Survivorship / selection bias.** The universe is today's cached list. Coins that died or were delisted
   (LUNA, FTT, etc.) are missing and coins that became big (HYPE, PEPE, SUI) are included because they became big.
   This flatters every historical number, especially the full range.
2. **ZEC dominance**: one coin explains most of the full-range and all of the holdout profit.
3. Fills at the 4H close with a flat 0.05% slippage; no market impact, no partial fills, no liquidity filter.
4. Funding is applied from the history; any missing funding history counts as zero.
5. Gross is capped at 1.0x and no liquidation engine is simulated beyond "equity <= 0".
6. Monte Carlo uses the engine threshold (-50%) designed for single-coin strategies; for a diversified,
   vol-targeted book the realised DD was already -48% (2022), so this check is expected to be hard to pass.
7. The production holdout lock is created on the first Lab run in production; it will start at the 80% point of
   whatever range that run evaluates (it will be ~2025-07-24 if run now).

## Reproduce

On the VPS (copy of the cache, never writes under /root):

```bash
cp -r /root/crypto-screener/data/lab/cache/perp /tmp/uv/cache
cd <repo copy> && PYTHONPATH=. LAB_DATA_DIR=/tmp/uv/cache LAB_DB_PATH=/tmp/uv/r.db LAB_ARTIFACTS_DIR=/tmp/uv/art \
  /root/bmtm-v2/venv/bin/python - <<'PY'
from src.lab.universal import runner as R, params as P, backtest as B, strategy as S
from src.lab import honesty
p = P.validate_params({}); panel = R.load_panel(R.universe_symbols(p))
feat = S.compute_features(panel, p); a, b = R.eval_range(panel, feat, p, None, None)
hs = honesty.proposed_holdout_start(B.iso(panel.ts[a]), B.iso(panel.ts[b]), S.BAR_S)
res = R.evaluate_all(panel, p, {"commission_pct": 0.05, "slippage_pct": 0.05, "funding": True},
                     "validate", None, None, holdout_start=hs)
print(res["verdict"], res["checks"])
PY
```

Or in the app: Lab -> Universal -> "Validasi" with defaults (this creates/uses the production holdout lock).

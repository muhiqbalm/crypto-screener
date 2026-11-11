# Universal v0: robustness, survivorship and concentration (2026-11-11)

Paper/research only. This follows up on `docs/universal-v0-backtest-2026-11-10.md`. All numbers come from
`src/lab/universal/robustness.py` running on the VPS in `/tmp/universal2` (nice 10). Raw outputs are in
`docs/universal-robustness-2026-11-data/`.

## TL;DR

- **Recommendation: drop Universal v0 as a real-money candidate.** Keep the existing paper watch only as a
  zero-cost forward record (it changes nothing). Do not iterate further on this holdout: it has now been
  evaluated 3 times (the original run plus the 2 pre-registered variants below).
- **Survivorship-free universe**: point-in-time top-30 by trailing 30-day quote volume, drawn from all 897 USDT perps
  Binance ever listed (including LUNA, FTT, SRM, MATIC, FTM, WAVES, OCEAN, ALPACA…). The default parameters were not changed.
  - Development period (2020-05 → 2025-07): **+2351%** (DD −47%, Sharpe 1.63, PF 1.25), against +2024% for the 29
    survivors. The dev result was therefore *not* produced by survivorship. Trend-following exits dying coins and
    often profits from their last pumps.
  - **Holdout (2025-07-24 → 2026-11-10): −27.3%, PF 0.89, DD −36%**, against **+26.9%** for the 29-coin list.
    Picking the universe with hindsight was worth about **54 percentage points** of the holdout. The original list
    contained ZEC (the holdout's big winner) and left out the dozens of new listings that whipsawed the strategy.
- **Concentration**: in the development period the top coin is about 14–16% of PnL and the top 3 about 39–45%. That is fine
  for 5 slots. Dropping the top 1 or top 3 coins costs a lot of return (PIT +2351% → +1754% → +986%) but does not
  break the strategy. On the holdout the PIT run's only meaningful winner is again ZEC; without it the run is **−41.9%**.
- **Robustness is weak**:
  - Results swing a lot with arbitrary choices:
    - rebalance hour: PIT dev +2136% to +4898%;
    - universe size: 20 → +1173%, 30 → +2351%, 50 → +1637%;
    - top-N 10/15: return falls by 3–5x.
  - Requiring 1 year of listing history cuts the comparable 2021+ dev return from +814% to +182% (static: +856% → +253%).
    **Most of the edge comes from coins in their first year after listing**, which is exactly where data, liquidity and
    selection are weakest.
  - The strategy only makes money in BTC bull regimes:
    - bull: Sharpe 2.5;
    - chop: about 1.1;
    - bear: −0.5 to −0.8.
  - The PIT dev years already show the decay: 2023 +244%, 2024 +22%, 2025 H1 −9.8%.
- **Both pre-registered variants FAIL** on the single holdout evaluation:
  - **C1** (PIT, defaults): −27.3%;
  - **C2** (PIT, 10% per-coin cap): −20.7%, PF 0.89, MC p95 −66%.

## 1. Survivorship-free (point-in-time) universe

### Data

| | |
|---|---|
| Source | `data.binance.vision` USD-M monthly 4H klines (daily files for 2026-11), monthly fundingRate, via the public S3 listing |
| Symbols | 897 USDT perps ever published (after excluding stablecoins, index perps BTCDOM/DEFI/…, dated futures and non-USDT quotes); 0 download errors, 216 MB |
| Listed before the holdout | 506 |
| Dead (last bar with volume > 0 more than 3 days before 2026-11-09) | 163 (64 died before the holdout start) |
| Quirk | Vision keeps writing **flat, zero-volume placeholder bars after a delisting** (FTT shows data to 2026-11, but its last trade was 2022-11-14; OCEAN/AGIX 2024-06-25). Zero-volume bars are never in the universe. |
| Gaps > 7 days | ICP (2022-08/09), BNX, TLM, MDT (2026-10, followed by a 1496x "move" on relisting). Not cleaned (pre-registered: report, don't edit). None of these coins was held across its gap. |
| Funding | present for all 897 symbols. Vision has no daily funding, so 2026-11-01..09 funding counts as 0. |

### Universe rule (`universe_mode="liquidity"`)

At every bar t, a coin is in the universe if it:
- passes the usual eligibility (≥120 days of data, finite score/vol, real bar);
- traded in bar t (quote volume > 0);
- is among the **top-30 by quote volume summed over the trailing 30 days** (bars ≤ t only, ≥80% of the window present).

Strategy parameters are unchanged. K=30 was fixed in advance to match the 29-coin static list.

### Development segment (2020-05-16 → 2025-07-24, holdout bars never loaded)

| Universe | Net | CAGR | Max DD | Sharpe | PF | MC DD p95 | Trades |
|---|---|---|---|---|---|---|---|
| Static 29 survivors (original) | +2024% | 80.2% | −48.2% | 1.65 | 1.46 | −63.6% | 1153 |
| Static 29, picked by liquidity (sanity check: identical) | +2024% | 80.2% | −48.2% | 1.65 | 1.46 | −63.6% | 1153 |
| **PIT top-30 (all 506 listed coins)** | **+2351%** | 85.2% | −47.4% | 1.63 | 1.25 | −65.3% | 1760 |
| PIT top-30, survivors only (163 dead coins removed, deliberate hindsight) | +1125% | 62.0% | −60.4% | 1.32 | 1.19 | −75.5% | 1712 |
| PIT top-20 | +1173% | 63.2% | −63.0% | 1.36 | 1.21 | −73.0% | 1472 |
| PIT top-50 | +1637% | 73.3% | −57.0% | 1.42 | 1.14 | −73.3% | 2065 |

How to read this:
- In the development period, dead coins *added* return. 35 coins that later died were held, for +45.1k in total:
  - ALPACA +20.5k (a single trade, held into its April 2025 delisting squeeze);
  - REEF +19.3k, BNX +18.6k, BLZ +15.1k, LUNA +10.9k;
  - EOS −18.5k.
- Positions that ended within 60 days of the coin's last trade made +23.7k, about 10% of dev PnL. **This is
  probably not realisable.** Delisting periods are thin, may be reduce-only, and settle at an index price. Our
  model closes at the last traded price.
- The PIT run **received** 30.1k of funding in the development period; the static run paid 18.9k. The biggest receivers
  were TRB (−16.4k, the late-2023 short squeeze), BLZ and AUCTION. The negative-funding squeeze profits are real
  history, but capacity for them is very small.
- PF fell from 1.46 to 1.25 and trades rose by 50%. The PIT book spends far more time in noisy mid-caps.

### Survivorship on the holdout (from the single pre-registered evaluation, §4)

| | Holdout net | PF | Max DD | 2x cost |
|---|---|---|---|---|
| Static 29 (original report) | +26.9% | 1.14 | −33.6% | +13.2% |
| **PIT top-30, same params (C1)** | **−27.3%** | 0.89 | −36.1% | −37.3% |
| BTC buy & hold | −36.4% | | −53.4% | |
| Equal-weight PIT universe | −76.0% | | −79.9% | |

**How much was survivorship?** On the development segment, none in aggregate return. On the holdout, all of the profit
and more: +26.9% → −27.3%. The 29-coin list was effectively chosen in 2025–26 knowing which coins mattered.
It included ZEC and HYPE and excluded the stream of new listings. The strategy still beat BTC and the
equal-weight basket by a wide margin in a falling market, so the trend filter works as a *loss limiter*. It is not
a money maker after costs.

## 2. Concentration (development segment)

### Per-coin contribution (baseline)

| Static 29: top | PnL | PIT top-30: top | PnL |
|---|---|---|---|
| SUI | +28.3k | ADA | +36.7k |
| ADA | +27.8k | XRP | +35.6k |
| BTC | +22.6k | TRB | +33.0k |
| XRP | +21.4k | BTC | +31.2k |
| DOGE | +18.4k | RUNE | +23.8k |
| BNB | +16.0k | 1000PEPE | +22.1k |
| FET | +14.8k | ALPACA (dead) | +20.5k |
| ETH | +11.5k | ETH | +19.8k |
| ZEC | +10.3k | BNB | +19.5k |
| **bottom**: UNI −8.8k, LTC −7.2k, APT −5.7k | | **bottom**: EOS −18.5k, ENS −15.6k, LTC −15.1k, TRX −12.3k | |

ZEC is *not* a dev-period story (9th in static, outside the top 10 in PIT). ZEC dominance is a holdout-only (late-2025 rally) phenomenon.

### Variants (each changes one thing; strategy otherwise default)

| Variant | Static: net | DD | Sharpe | MC p95 | PIT: net | DD | Sharpe | MC p95 | PIT top-3 share |
|---|---|---|---|---|---|---|---|---|---|
| Baseline | +2024% | −48.2 | 1.65 | −63.6 | +2351% | −47.4 | 1.63 | −65.3 | 45% |
| Drop top-1 coin | +1685% | −48.2 | 1.57 | −65.6 | +1754% | −48.5 | 1.51 | −66.9 | 52% |
| Drop top-3 coins | +1050% | −50.0 | 1.40 | −67.0 | +986% | −51.9 | 1.29 | −68.5 | 53% |
| Cap 25% / coin | +1903% | −48.4 | 1.66 | −63.0 | +2111% | −47.5 | 1.60 | −65.1 | 46% |
| Cap 20% | +1802% | −48.8 | 1.68 | −61.8 | +1986% | −47.9 | 1.59 | −64.8 | 46% |
| Cap 15% | +1667% | −46.5 | 1.72 | −58.4 | +1831% | −48.3 | 1.60 | −63.5 | 46% |
| **Cap 10%** | +1201% | **−39.8** | **1.76** | **−50.9** | +1332% | −46.9 | 1.56 | **−59.8** | **39%** |
| Top-10 | +1022% | −55.0 | 1.38 | −67.1 | +688% | −52.3 | 1.16 | −70.6 | 40% |
| Top-10, cap 15% | +971% | −52.3 | 1.44 | −63.4 | +617% | −56.1 | 1.14 | −70.8 | 40% |
| Top-15 | +952% | −49.6 | 1.35 | −67.9 | +515% | −51.2 | 1.05 | −73.3 | 44% |
| Top-15, cap 15% | +933% | −48.1 | 1.42 | −63.0 | +472% | −55.4 | 1.03 | −72.7 | 41% |
| Baseline, from 2021-01 | +856% | −48.2 | 1.46 | −64.4 | +814% | −47.4 | 1.35 | −67.4 | 47% |
| **≥1 year history**, from 2021-01* | +253% | −52.0 | 0.93 | −71.6 | +182% | −54.2 | 0.75 | −80.9 | 88% |

\* The data starts in 2020-01, so a 365-day history rule cannot trade anything before ~2021-01. Compare it with the
"from 2021-01" baseline, not with the full baseline.

PnL by the coin's age when the position was opened (PIT baseline):
- < 180 d: +2.2k;
- 180–365 d: **+83.2k**;
- 1–2 y: −12.1k;
- > 2 y: +118.4k;
- listed before the data starts: +43.4k.

Coins in their second half-year after listing carry about 35% of the profit.

Findings:
- Lower caps work mainly by de-risking (with 5 slots, a 10% cap means ≤50% gross). They improve Sharpe/MC in the static
  universe, but in PIT only the MC tail improves.
- A larger N dilutes the momentum signal and makes everything worse.
- Excluding young coins removes most of the edge.

## 3. Robustness (development segment)

### Rebalance timing (daily rebalance at the 4H close at hh:00 UTC; default 00:00)

| Close hour | Static net | DD | Sharpe | PIT net | DD | Sharpe |
|---|---|---|---|---|---|---|
| 00 (default) | +2024% | −48.2 | 1.65 | +2351% | −47.4 | 1.63 |
| 04 | +1705% | −52.2 | 1.56 | +2136% | −51.1 | 1.56 |
| 08 | +1713% | −57.2 | 1.59 | +3235% | −53.0 | 1.74 |
| 12 | +2594% | −48.8 | 1.79 | +4898% | −50.0 | 1.91 |
| 16 | +2117% | −55.4 | 1.69 | +2755% | −50.8 | 1.67 |
| 20 | +2319% | −49.1 | 1.71 | +3951% | −43.2 | 1.84 |

The Sharpe range is 1.56–1.91, but the 5-year multiple varies by about 2.3x with a choice that should not matter. This
is path dependence from 5 concentrated slots. None of these offsets was selected.

### Costs (commission + slippage multiplied; funding unchanged)

| | Static net | DD | PF | PIT net | DD | PF |
|---|---|---|---|---|---|---|
| 0 (no fees, no slippage, no funding) | +4049% | −44.6 | 1.58 | +2932% | −44.8 | 1.26 |
| 1x (0.05% + 0.05%) | +2024% | −48.2 | 1.46 | +2351% | −47.4 | 1.25 |
| 2x | +1379% | −52.9 | 1.38 | +1531% | −49.7 | 1.21 |
| 3x | +919% | −59.0 | 1.31 | +964% | −53.4 | 1.16 |

Turnover is about 70–80x equity per year, so each extra 0.1% round trip costs roughly 7–8%/yr.

### Calendar years (development segment; 2020 from 05-16, 2025 to 07-24)

| | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 H1 |
|---|---|---|---|---|---|---|
| Static 29 | +120.9% | +211.3% | −41.8% | +133.4% | +131.0% | −1.6% |
| PIT top-30 | +167.6% | +287.0% | −37.5% | +244.4% | **+22.0%** | **−9.8%** |
| PIT cap 10% | +101.4% | +275.0% | −40.0% | +179.9% | +17.8% | −4.0% |

### Regimes (BTC daily close vs its 200-day SMA; bull = above and SMA rising over 20 d, bear = below and falling, chop = rest)

| Regime (dev days) | Static: cum | ann. | Sharpe | PIT: cum | ann. | Sharpe |
|---|---|---|---|---|---|---|
| Bull (1090 d, 58%) | +1918% | +110% | 2.50 | +1964% | +111% | 2.49 |
| Chop (459 d, 24%) | +48% | +37% | 1.07 | +59% | +45% | 1.12 |
| Bear (345 d, 18%) | −29% | −30% | −0.83 | −26% | −22% | −0.49 |

Holdout regimes (C1): bull 165 d −12.4%, bear 266 d −11.4%, chop 42 d −6.2%. **It lost in every regime, including bull.**

## 4. Pre-registered candidates and the single holdout evaluation

The candidates were pre-registered in `docs/universal-robustness-prereg-2026-11.json`
(sha256 `0f0828c6…ed4`, committed in `c2ad50f` *before* the evaluation ran at 2026-11-11T04:20Z). Each was evaluated once
with the full Lab pipeline: `evaluate_all(validate)`, the locked holdout 2025-07-24T04:00Z, and the same 7 checks.

- **C1 `pit_default`**: universe_mode=liquidity, K=30, 30 d; every strategy param at its default. This is the honest
  re-run of v0.
- **C2 `pit_cap10`**: C1 plus a 10% per-coin cap. It was the only change that improved tail risk in *both* dev universes.
  Top-N 10/15, ≥1y history and rebalance offsets were rejected on dev.

| Check | C1 PIT default | C2 PIT cap 10% | Threshold |
|---|---|---|---|
| Holdout profit factor | 0.89 ✗ | 0.89 ✗ | ≥ 1.2 |
| Holdout net after costs | **−27.3%** ✗ | **−20.7%** ✗ | > 0 |
| Monte Carlo DD p95 (full range) | −72.7% ✗ | −66.3% ✗ | > −50% |
| Holdout trades | 465 ✓ | 465 ✓ | ≥ 30 |
| Holdout net at 2x costs | −37.3% ✗ | −26.8% ✗ | > 0 |
| Fragile params (dev sensitivity) | 0 ✓ | 0 ✓ | ≤ 3 |
| Liquidations | 0 ✓ | 0 ✓ | 0 |
| **Verdict** | **FAIL** (4/7 fail) | **FAIL** (4/7 fail) | |

| | C1 | C2 |
|---|---|---|
| Holdout max DD / Sharpe / win% | −36.1% / −0.30 / 33.1% | −28.4% / −0.33 / 32.9% |
| In-sample (dev) net / DD / Sharpe | +2351% / −47.4% / 1.63 | +1332% / −46.9% / 1.56 |
| Full range net / DD | +1677% / −47.4% | +1033% / −46.9% |
| Walk-forward (dev, 6 folds) compounded / avg PF / profitable folds | +44.6% / 1.21 / 4 of 6 | +51.5% / 1.26 / 5 of 6 |
| MC P(DD beyond −50%) | 53% | 32% |
| Holdout top coin | ZEC +1.59k (23 trades) | ZEC +1.37k |
| Holdout without ZEC | **−41.9%**, PF 0.81 | **−37.2%**, PF 0.78 |
| Other holdout winners | LAB, PIPPIN, SIREN, AKE (new 2025–26 listings) | same |
| Holdout losers | WLD, BCH, CLUSDT, IP, TUT | WLD, TUT, IP, PUMP, DUSK |

## 5. Recommendation

**Drop Universal v0 as a trading candidate.** Do not spend more time tuning it on this data.

- The honest (point-in-time) version loses 27% in a 15-month holdout and fails 4 of 7 checks. The only modification
  with a principled dev-period case (lower cap) still loses 21%.
- The development-period profit is a bull-market, young-coin, path-dependent phenomenon:
  - requiring 1 year of listing history removes 70–78% of it;
  - rebalance hour and universe size swing it 2–4x;
  - the PIT dev years were already decaying in 2024–25.
- What survives: in falling markets it loses far less than holding (−27% against BTC −36% and equal-weight −76%). The
  "Koin Terkuat" strength table and trend filter are useful *context*. Neither is a source of profit.
- The holdout from 2025-07-24 is now spent (3 evaluations). Any future multi-coin idea must be judged on **forward paper
  data from 2026-11-10 onward**, or on a fresh, pre-registered split.
- The `universe_mode=liquidity` code and the delisted-coin data are worth keeping. Any future cross-sectional Lab
  strategy should be tested point-in-time by default, and the static survivor list should be treated as biased.

## Reproduce

```bash
# on the VPS, never under /root
cd /tmp/universal2/repo   # a copy of this branch
nice -n 10 /root/bmtm-v2/venv/bin/python -m src.lab.universal.pit_data --out /tmp/universal2/pit --until 2026-11-10 --workers 16
nice -n 10 /root/bmtm-v2/venv/bin/python -m src.lab.universal.robustness --source static --data /tmp/universal2/cache --out dev_static.json
nice -n 10 /root/bmtm-v2/venv/bin/python -m src.lab.universal.robustness --source pit --data /tmp/universal2/pit \
    --static-symbols "$(ls /tmp/universal2/cache/*_4h.parquet | xargs -n1 basename | sed 's/_PERP_4h.parquet//' | paste -sd, -)" \
    --out dev_pit.json
# the holdout step refuses to run twice for the same output file
nice -n 10 /root/bmtm-v2/venv/bin/python -m src.lab.universal.robustness --source pit --data /tmp/universal2/pit \
    --holdout-prereg docs/universal-robustness-prereg-2026-11.json --out holdout_once.json
```

`/tmp/universal2/cache` is a copy of the 4H and funding parquet files from `/root/crypto-screener/data/lab/cache/perp`.

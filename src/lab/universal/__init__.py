"""Universal v0: one rule set for a basket of perpetuals.

Volatility-scaled multi-coin trend following + cross-sectional momentum:
  * rank coins by a vol-adjusted multi-horizon momentum score
  * hold the top-N that are also in an uptrend (optional: short the bottom-N in a downtrend)
  * inverse-volatility weights scaled to a target portfolio volatility, capped by gross leverage
  * rebalance every 4H or daily; commission + slippage on traded notional, funding every settlement

Modules:
  params    stdlib-only parameter schema/validation (imported by the API)
  strategy  features + target weights (numpy/pandas)
  backtest  portfolio simulator + metrics
  runner    Lab run job (honesty report: locked holdout, walk-forward, Monte Carlo, cost stress)
  strength  "Koin Terkuat" relative-strength table
  live      4H refresh job: data, strength, universal watches, paper rebalances
  alerts    Telegram outbox (stdlib; sending happens in the worker process)

Paper only: nothing here places real orders.
"""
TEMPLATE_ID = "universal_v0"
UNIVERSE_SYMBOL = "UNIVERSE"
BAR_TF = "4h"

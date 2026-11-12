"""Basket paper strategies: ONE strategy with default params on a fixed, pre-registered coin
list. Every coin is a normal Lab watch; all of a basket's watches auto-paper into ONE paper
account, and progress is counted per basket (x/30 closed trades across coins).

Pre-registration: docs/riset-2026-11-12/08-praregistrasi-basket.md (machine copy
docs/research/basket/prereg-basket-2026-11-12.json, locked in commit 52dccca before any
basket backtest). A basket's definition (template, params, coins, sizing, account) is frozen
by a trigger: a change means a new basket with a new pre-registration.

Paper only: nothing here sends an order, imports src.trading or sends a notification channel
other than the in-web bell. Stdlib only (importable by the API, the worker and the engine child).

Modules:
  rules   pre-registered thresholds and outcome rules (tested equal to the JSON)
  store   lab_baskets / lab_basket_members / lab_basket_events (CREATE IF NOT EXISTS),
          create() through the same watch-insert path as the API, lookups, event log
  sizing  entry_plan(): position size of a member's new entry on the shared account
          (risk % at the strategy stop, or equal slots x engine notional), caps, kill switch
  report  per-basket progress, per-coin breakdown, checkpoints and the paper-vs-engine
          fidelity check (read-only)
"""

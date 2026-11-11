"""Arena Paper: the paper presets side by side, and how far their forward paper
results drift from the preset's backtest (holdout) expectations.

Read-only over lab_presets / lab_preset_links / watches / watch_state /
paper_accounts / paper_positions / journal_entries. The only table it owns is
``arena_equity_snapshots`` (hourly mark-to-market equity per paper account,
written by the ``arena_snapshot`` worker job, created on demand).

Paper only: nothing here opens, closes or sizes a position, imports src.trading
or sends a notification.

Modules:
  store     snapshot table (CREATE IF NOT EXISTS) + writer       (stdlib)
  stats     small-sample statistics: Poisson / binomial ranges,
            Wilson and t intervals, drawdown, Sharpe              (stdlib)
  report    leaderboard, drift check and equity curves for the API
  jobs      ``arena_snapshot`` job body
  schedule  worker scheduler hook (one snapshot job per hour)
"""
JOB_KIND = "arena_snapshot"

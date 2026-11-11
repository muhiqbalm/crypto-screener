"""Signal Ledger ("Catatan Sinyal"): record every signal the system produces and
score it afterwards, so the team can see which signal types carry information.

Sources (``ledger_signals.source``):
  screener        live screener snapshots (hourly, worker child job), onset-only events
  screener_rekon  causal reconstruction of the screener over the last ~27 days (one-off
                  backfill; approximate inputs, kept as a separate source)
  lab_watch       Strategy Lab watch entries (Rosyade family), from watch_state, only
                  entries at/after the watch was created (earlier ones are a backtest)
  universal       Universal v0 rebalances: a coin entering the target book or flipping side
  webhook         TradingView webhook "open" alerts, read READ-ONLY from bmtm_trading.db

Scoring (``ledger_outcomes``): forward return 4h / 1d / 3d / 7d from public Binance
USD-M 15m klines, direction-aware hit, return relative to BTC, MFE / MAE in the window.

Modules:
  store     schema (own tables in lab.db, created on demand) + inserts   (stdlib)
  stats     Wilson / t intervals, medians, group summaries                (stdlib)
  scoring   outcome maths + filling pending outcomes                     (stdlib)
  collect   lab watch / universal / webhook collectors                   (stdlib)
  binance   public REST helpers (requests), injectable for tests
  screener  live snapshot + reconstruction (pandas; runs in a child job)
  jobs      ledger_cycle / ledger_backfill job bodies
  schedule  worker scheduler hook (stdlib)

Read-only with respect to trading: nothing here imports src.trading or places orders,
and nothing sends notifications.
"""
SOURCES = ("screener", "screener_rekon", "lab_watch", "universal", "webhook")
HORIZONS: dict[str, int] = {"4h": 4 * 3600, "1d": 86400, "3d": 3 * 86400, "7d": 7 * 86400}
JOB_KINDS = ("ledger_cycle", "ledger_backfill")

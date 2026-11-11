"""Cek bot live vs strategi (live-bot reconciliation). Read-only.

Question answered: for every 4H bar of the live strategy **4H-ETH-Basic** (Rosyade
family, ETH 4H, running in TradingView Pine -> BMTM webhook -> Binance), did the bot do
what the strategy says it should have done?

  expected   the Lab template + engine recompute the strategy's own entries / exits on
             cached Binance USD-M data (``expected``; engine child process). Three
             variants: full history with zero costs (= Pine default ``strategy()``
             properties, the reference), a short history (warm-up / path dependence)
             and the preset's costs (cost-sensitive daily-loss / cooldown filters).
  actual     webhook deliveries: nginx access-log lines for ``POST /webhook/tradingview``
             from non-local IPs (rotated .gz files included), the API's app log
             ("Request completed" status, "Order placed", "Order execution failed") and
             ``trade_logs`` rows (``mode=ro`` + ``query_only``). Facts are kept in lab.db
             so they outlive log rotation. Raw lines, passphrases and user ids are never
             stored or returned; IPs are masked.
  match      per 4H bar (``match``; pure): cocok | sinyal tidak terkirim | terkirim tapi
             gagal / ditolak | tak terduga | harga beda, plus ``perlu_dicek`` where the
             Lab may legitimately differ from Pine (see docs/lab/live-check.md).

Nothing here sends orders, posts to the webhook, notifies anyone or imports
``src.trading``.

Modules:
  store     schema in lab.db (created on demand) + LAB_LIVECHECK_* settings   (stdlib)
  logs      nginx / app-log parsing incl. .gz, sanitising                     (stdlib)
  trades    trade_logs / positions reader (read-only)                         (stdlib)
  expected  strategy signals from the template + engine                       (engine child)
  match     delivery assembly + per-bar classification                        (stdlib)
  jobs      ``livecheck_cycle`` job body
  schedule  worker scheduler hook (after each 4H close + hourly catch-up)
  report    aggregates for the API
"""
JOB_KIND = "livecheck_cycle"

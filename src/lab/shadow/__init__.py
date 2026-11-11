"""Shadow execution ("Kualitas eksekusi"): measure how the live TradingView webhook
signals are executed today, and what a passive limit (maker) entry would have done.

Nothing here changes execution. For every live webhook signal (open and close) in
bmtm_trading.db ``trade_logs`` (read through a separate ``mode=ro`` + ``query_only``
connection, same as the ledger collector) it records:

  actual   signal bar close (the 4H close that fired the alert), alert arrival
           latency, the market fill price if trade_logs has one, slippage vs the
           bar close in bps, split into drift (close -> first public trade after
           arrival) and impact (that trade -> our fill)
  shadow   a post-only limit placed at arrival at ``close - dir * k * ATR(14)``
           for a few k; filled only on a TRADE-THROUGH (a public trade strictly
           better than the limit, so queue position never matters); time to fill
           from aggTrades (1m klines locate the minute, aggTrades pin the trade);
           per time-to-live: fill / miss / post-only reject, saving vs the actual
           (or proxy) market fill incl. the taker-maker fee difference, and on a
           miss how far price ran away and the cost of chasing with a market order
           at expiry

Public Binance USD-M market data only (REST + data.binance.vision), no API keys,
no orders, no notifications, no import of ``src.trading``.

Modules:
  store     schema in lab.db (created on demand) + LAB_SHADOW_* settings   (stdlib)
  source    trade_logs reader (read-only) -> one signal per alert          (stdlib)
  market    public REST / data.binance.vision helpers (urllib)             (stdlib)
  simulate  pure maths: ATR, actual quality, shadow limit outcomes         (stdlib)
  jobs      shadow_cycle job body (collect + evaluate due signals)
  schedule  worker scheduler hook
  report    aggregates for the API
"""
JOB_KIND = "shadow_cycle"

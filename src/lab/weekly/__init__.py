"""Weekly report ("Laporan Mingguan"): one ISO week (UTC, Monday 00:00 -> next Monday).

Every section is computed from data that exists (lab.db, bmtm_trading.db
``trade_logs`` read-only, the deploy / backup logs read-only); a section without
data says so instead of showing zeros that look like results.

  build     the report dict for one week (stdlib)
  store     ``weekly_reports`` snapshot table in lab.db (write-once per week)
  system    deploy / backup log parsing + PM2 process status (read-only, no secrets)
  schedule  worker scheduler hook: snapshot of the finished week every Monday 00:30 UTC,
            plus the deploy-log notification scan

Nothing here imports src.trading, places orders or sends external messages.
"""
SNAPSHOT_AFTER_S = 30 * 60      # Monday 00:30 UTC

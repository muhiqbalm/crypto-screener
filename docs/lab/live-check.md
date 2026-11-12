# Cek bot live vs strategi (`/lab/live-check`)

Read-only reconciliation of the live bot (preset **4H-ETH-Basic**: TradingView Pine
`Rosyade_Terbaru.pine` → `POST /webhook/tradingview` → Binance, account Rosyade) against
the strategy's own signals as recomputed by the Strategy Lab.

Code: `src/lab/livecheck/` (job `livecheck_cycle`, fast lane, after every 4H close +
`delay_s` and hourly), API `GET /api/v1/lab/live-check?bars=N` (admin-only, lab.db only).
Nothing here sends orders, posts to the webhook, sends Telegram or imports `src.trading`. The
only outward effect is one in-web notification per failed live order (below).

## Inputs

| Source | What is taken | How |
|---|---|---|
| Lab template + engine | entries / exits with side, bar and price | engine child, cached Binance USD-M data, three variants (below) |
| nginx access log (`/var/log/nginx/access.log*`, .gz included) | `POST /webhook/tradingview` from non-local IPs: time, status, TradingView UA or not, masked IP | read-only; loopback, private and the server's own IPs (`hostname -I`) are local |
| App log (PM2 `bmtm-api-out/error*.log*`, `/root/bmtm_webhook_evidence*.log`) | "Request completed" status + duration, "Order placed" (buy/sell), "Order execution failed" reason, duplicates, symbol | read-only, sanitised |
| `bmtm_trading.db` `trade_logs` | action, side, status, fill price/qty, error text (sanitised) | `mode=ro` + `query_only`; no user id, passphrase or order id selected |

Facts from logs are stored in `livecheck_evidence` (hash of the line, never the line), so
they outlive logrotate (nginx keeps 14 days). Log coverage intervals are kept in `lab_kv`.

## Statuses

`cocok` · `harga_beda` (fill vs Lab price > `LAB_LIVECHECK_PRICE_BPS`, default 30) ·
`gagal` (terkirim tapi gagal / ditolak, with reason) · `tidak_terkirim` · `tak_terduga` ·
`menunggu` (too recent) · `tanpa_log` (no log covers that time) · `diabaikan` (non-TradingView
client, e.g. curl tests).

Matching: same bar → one bar off (`beda_bar`) → for exits, anywhere inside the same trade
(`beda_waktu_exit`). A delivery's direction (from trade_logs or the app's "Order placed
side=buy/sell") must fit; nginx-only deliveries have unknown direction.

## Known Pine-vs-Lab differences (flagged "perlu dicek", not errors)

| Cause | Why the Lab can legitimately differ |
|---|---|
| `warmup` | Pine starts at the first bar loaded on the chart; the strategy is path dependent (position, daily-loss, cooldown, OB state). Variant `pendek` starts 60 days before `since`; a signal missing there depends on far history. |
| `biaya` | The script sets no commission, so the reference variant uses zero costs/funding. If the chart's Properties set commission, realised PnL changes the daily-loss / cooldown filters. Variant `biaya` uses the preset costs. |
| `intrabar` | `strategy.exit(stop, limit)` fills on the live tick that touches the level, mid-bar; the engine replays OHLC with an assumed path. Live SL/TP/BE/OB-trail exits can come hours earlier than the Lab's bar-close exits. |
| `beda_bar`, `beda_waktu_exit` | Bar timing: TradingView realtime vs closed-bar data, volume differences between the TV feed and Binance klines, thresholds near the edge. |
| data source | Lab uses Binance USD-M perp klines (`ETHUSDT`); the chart is `ETHUSDT.P`. Volumes/wicks can differ slightly, which moves volume / RVOL / TP-check filters. |
| input drift | The Lab uses preset params (template defaults). The Pine source defaults differ in places (e.g. long hard TP 60 vs 62.5) and the live chart's inputs can be changed in TradingView without any trace here. |
| `tengah_bar` | A delivery mid-bar is an intrabar SL/TP alert or a manual alert. |

## Failed live orders (audit 2026-11-13 K1)

Every `gagal` row (delivered but rejected / failed / outcome unknown) is `perlu_dicek`, whatever
its causes: the bot is no longer where the strategy is. On the first cycle that sees it (bars
closed within the last 14 days), the job raises one **sticky** in-web notification (type
`live`, link `/bot#cek`, dedupe per bar + action + side): pinned in red on top of the Lab bell
for every admin, not cleared by "tandai semua sudah dibaca" or the 90-day prune, until one
admin presses "Sudah dicek" (`POST /api/v1/lab/notifications/{id}/ack`). The /bot answer keeps
counting a `gagal` row as a missed trade ("Belum aman"), not as a Lab-vs-Pine doubt.

## Manual positions

The bot only records positions it opened itself. A position opened by hand on the
account is not part of the strategy and is not counted. It shows up only through its
effect: the bot rejects opens while any ETH position exists ("posisi manual") and closes
only what it opened.

## Settings (`.env`, all optional)

`LAB_LIVECHECK_ENABLED` (1) · `LAB_LIVECHECK_PRESET` (4H-ETH-Basic) · `LAB_LIVECHECK_SINCE`
(2026-10-01) · `LAB_LIVECHECK_SHORT_HISTORY_DAYS` (60) · `LAB_LIVECHECK_PRICE_BPS` (30) ·
`LAB_LIVECHECK_NGINX_GLOB` · `LAB_LIVECHECK_APP_GLOBS` (comma list) · `LAB_LIVECHECK_LOCAL_IPS`.

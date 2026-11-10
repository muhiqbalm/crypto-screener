#!/bin/bash
# BMTM daily backup  (install: /usr/local/bin/bmtm-backup.sh, cron 02:30 UTC)
#
# What:   trading DB + lab DB (SQLite online-backup API, WAL-safe), .env files,
#         nginx site, PM2 dump, crontabs  ->  one tar.gz per day.
# Checks: PRAGMA integrity_check on every DB copy; non-zero exit + log + optional
#         Telegram alert on any failure.
# Retention: 14 daily + 8 weekly (Sunday) archives.
# Off-site (optional, recommended):
#   - encryption: set AGE_RECIPIENT (age public key) -> archive is age-encrypted
#     before leaving the box. Without it, nothing is uploaded (the archive
#     contains TRADING_ENCRYPTION_KEY next to the encrypted exchange keys).
#   - upload:     set RCLONE_REMOTE (e.g. "b2:bmtm-backups") -> rclone copy.
# Config file: /etc/default/bmtm-backup (KEY=value, sourced).
# Read-only towards production data; never stops or restarts any service.
set -euo pipefail
umask 077

[ -f /etc/default/bmtm-backup ] && . /etc/default/bmtm-backup
APP=${APP:-/root/crypto-screener}
ROOT=${BACKUP_ROOT:-/root/backups}
DAILY_KEEP=${DAILY_KEEP:-14}
WEEKLY_KEEP=${WEEKLY_KEEP:-8}
LOG=${LOG:-/var/log/bmtm-backup.log}
PY=${PY:-/usr/bin/python3}
AGE_RECIPIENT=${AGE_RECIPIENT:-}
RCLONE_REMOTE=${RCLONE_REMOTE:-}
ALERT_TELEGRAM=${ALERT_TELEGRAM:-0}

STAMP=$(date -u +%Y%m%dT%H%M%SZ)
DAY=$(date -u +%Y%m%d)
WORK=$(mktemp -d "${TMPDIR:-/tmp}/bmtm-backup.XXXXXX")
trap 'rm -rf "$WORK"' EXIT

log() { echo "$(date -u +%FT%TZ) $*" | tee -a "$LOG" >&2; }

alert() {
  [ "$ALERT_TELEGRAM" = "1" ] || return 0
  local tok chat
  tok=$(grep -E '^TRADING_TELEGRAM_BOT_TOKEN=' "$APP/.env" | cut -d= -f2- | tr -d '"'"'"' \r') || return 0
  chat=$(grep -E '^TRADING_TELEGRAM_DEFAULT_CHAT_ID=' "$APP/.env" | cut -d= -f2- | tr -d '"'"'"' \r') || return 0
  [ -n "$tok" ] && [ -n "$chat" ] || return 0
  curl -fsS -m 10 -o /dev/null "https://api.telegram.org/bot${tok}/sendMessage" \
    --data-urlencode "chat_id=${chat}" --data-urlencode "text=BMTM backup FAILED on $(hostname): $1" || true
}

fail() { log "FAIL: $*"; alert "$*"; exit 1; }

sqlite_backup() {  # src dst
  "$PY" - "$1" "$2" <<'P' || return 1
import sqlite3, sys
src = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True, timeout=30)
dst = sqlite3.connect(sys.argv[2])
src.backup(dst)
res = dst.execute("PRAGMA integrity_check").fetchone()[0]
dst.close(); src.close()
if res != "ok":
    print(f"integrity_check: {res}", file=sys.stderr); sys.exit(2)
P
}

mkdir -p "$ROOT/daily" "$ROOT/weekly"
chmod 700 "$ROOT" "$ROOT/daily" "$ROOT/weekly"
B="$WORK/bmtm-$STAMP"; mkdir -p "$B"

LAB_DB=$(grep -E '^LAB_DB_PATH=' "$APP/.env" 2>/dev/null | cut -d= -f2- | tr -d '"'"'"' \r' || true)
LAB_DB=${LAB_DB:-$APP/data/lab/lab.db}
case "$LAB_DB" in /*) ;; *) LAB_DB="$APP/$LAB_DB";; esac

sqlite_backup "$APP/bmtm_trading.db" "$B/bmtm_trading.db" || fail "trading DB backup/integrity"
if [ -f "$LAB_DB" ]; then sqlite_backup "$LAB_DB" "$B/lab.db" || fail "lab DB backup/integrity"; fi

mkdir -p "$B/config"
cp -p "$APP/.env" "$B/config/crypto-screener.env"
for f in /root/crypto-screener-fe/.env /root/crypto-screener-fe/.env.local; do
  [ -f "$f" ] && cp -p "$f" "$B/config/fe$(basename "$f")"
done
cp -pL /etc/nginx/sites-enabled/bmtm-trade.duckdns.org "$B/config/nginx-site.conf" 2>/dev/null || true
[ -f /root/.pm2/dump.pm2 ] && cp -p /root/.pm2/dump.pm2 "$B/config/pm2-dump.json"
crontab -l > "$B/config/root.crontab" 2>/dev/null || true
cp -p /etc/cron.d/bmtm-* "$B/config/" 2>/dev/null || true
[ -d "$APP/data/lab/artifacts" ] && tar -C "$APP/data/lab" -czf "$B/lab-artifacts.tar.gz" artifacts

( cd "$B" && find . -type f ! -name SHA256SUMS -exec sha256sum {} + > SHA256SUMS )

ARCHIVE="$ROOT/daily/bmtm-$DAY.tar.gz"
tar -C "$WORK" -czf "$ARCHIVE.tmp" "bmtm-$STAMP" && mv -f "$ARCHIVE.tmp" "$ARCHIVE"
chmod 600 "$ARCHIVE"
tar -tzf "$ARCHIVE" >/dev/null || fail "archive unreadable: $ARCHIVE"

# Legacy single-file copy kept for scripts that expect it.
cp -p "$B/bmtm_trading.db" "$ROOT/daily/bmtm_trading_$DAY.db"

if [ "$(date -u +%u)" = "7" ]; then cp -p "$ARCHIVE" "$ROOT/weekly/bmtm-$DAY.tar.gz"; fi

find "$ROOT/daily"  -maxdepth 1 \( -name 'bmtm-*.tar.gz' -o -name 'bmtm_trading_*.db' \) -mtime +"$DAILY_KEEP" -delete
find "$ROOT/weekly" -maxdepth 1 -name 'bmtm-*.tar.gz' -mtime +$((WEEKLY_KEEP * 7)) -delete

if [ -n "$RCLONE_REMOTE" ]; then
  if [ -z "$AGE_RECIPIENT" ] || ! command -v age >/dev/null || ! command -v rclone >/dev/null; then
    fail "RCLONE_REMOTE set but age/rclone/AGE_RECIPIENT missing - refusing to upload plaintext secrets"
  fi
  age -r "$AGE_RECIPIENT" -o "$WORK/bmtm-$DAY.tar.gz.age" "$ARCHIVE" || fail "age encryption"
  rclone copy --no-traverse "$WORK/bmtm-$DAY.tar.gz.age" "$RCLONE_REMOTE/daily/" || fail "rclone upload"
  log "off-site upload ok -> $RCLONE_REMOTE/daily/bmtm-$DAY.tar.gz.age"
fi

log "ok $ARCHIVE ($(du -h "$ARCHIVE" | cut -f1))"

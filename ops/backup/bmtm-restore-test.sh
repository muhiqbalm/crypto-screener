#!/bin/bash
# Restore drill: unpack the newest (or given) backup archive into a temp dir,
# verify checksums + PRAGMA integrity_check + schema, and compare row counts
# with the live DBs (read-only). Never touches production files.
# Usage: bmtm-restore-test.sh [/root/backups/daily/bmtm-YYYYMMDD.tar.gz]
set -euo pipefail
umask 077
APP=${APP:-/root/crypto-screener}
ARCHIVE=${1:-$(ls -1t /root/backups/daily/bmtm-*.tar.gz 2>/dev/null | head -1)}
[ -n "$ARCHIVE" ] && [ -f "$ARCHIVE" ] || { echo "no archive found" >&2; exit 1; }
T=$(mktemp -d /tmp/bmtm-restore.XXXXXX); trap 'rm -rf "$T"' EXIT
tar -xzf "$ARCHIVE" -C "$T"
D=$(find "$T" -mindepth 1 -maxdepth 1 -type d | head -1)
( cd "$D" && sha256sum --quiet -c SHA256SUMS ) && echo "checksums: ok"
LAB_LIVE=$(grep -E '^LAB_DB_PATH=' "$APP/.env" | cut -d= -f2- | tr -d '"'"'"' \r' || true)
LAB_LIVE=${LAB_LIVE:-$APP/data/lab/lab.db}
/usr/bin/python3 - "$D" "$APP/bmtm_trading.db" "$LAB_LIVE" <<'P'
import os, sqlite3, sys
d, live_trading, live_lab = sys.argv[1:4]
bad = 0
for name, live in (("bmtm_trading.db", live_trading), ("lab.db", live_lab)):
    p = os.path.join(d, name)
    if not os.path.exists(p):
        print(f"{name}: not in archive"); continue
    r = sqlite3.connect(p)
    ic = r.execute("PRAGMA integrity_check").fetchone()[0]
    fk = r.execute("PRAGMA foreign_key_check").fetchall()
    print(f"{name}: integrity={ic} fk_violations={len(fk)}")
    bad |= ic != "ok"
    if os.path.exists(live):
        l = sqlite3.connect(f"file:{live}?mode=ro", uri=True)
        for (t,) in r.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
            a = r.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
            try:
                b = l.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
            except sqlite3.Error:
                b = "missing"
            print(f"   {t:24} backup={a:<8} live={b}")
sys.exit(1 if bad else 0)
P
for f in crypto-screener.env; do
  [ -s "$D/config/$f" ] && echo "config/$f: present ($(grep -c '=' "$D/config/$f") keys)"
done
echo "restore drill OK: $ARCHIVE"

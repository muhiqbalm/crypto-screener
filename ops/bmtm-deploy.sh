#!/bin/bash
# bmtm-deploy — satu-satunya jalur deploy BMTM ke VPS (dijalankan manual oleh orang, bukan CI).
#
#   bmtm-deploy be [REF] [--dry-run] [--allow-trading]   backend  (bmtm-api + bmtm-lab-worker)
#   bmtm-deploy fe [REF] [--dry-run]                     frontend (bmtm-web)
#   bmtm-deploy status                                   versi yang sedang live
#
# REF default: main (branch/tag/commit di GitHub). Alur: fetch -> tes -> backup -> pasang
# -> restart -> cek kesehatan -> rollback otomatis kalau gagal. Satu deploy dalam satu waktu.
# Backend hanya boleh di menit :15-:44 UTC (jauh dari close candle 4H). Perubahan src/trading
# (jalur trading live) ditolak kecuali --allow-trading.
set -euo pipefail

BASE=/root/deploy
LOG=/var/log/bmtm-deploy.log
BE_LIVE=/root/crypto-screener
FE_LIVE=/root/crypto-screener-fe
FE_BUILD=/root/fe-build
BE_PY=$BE_LIVE/.venv/bin/python
PYTOOLS=$BASE/pytools          # pytest & co (PYTHONPATH saat tes)
LAB_ENGINE=/root/bmtm-lab-engine
declare -A URL=([be]=https://github.com/muhiqbalm/crypto-screener.git [fe]=https://github.com/muhiqbalm/crypto-screener-fe.git)

say() { echo "[$(date -u +%FT%TZ)] $*" | tee -a "$LOG"; }
die() { say "GAGAL: $*"; exit 1; }
who() { echo "${SUDO_USER:-${BMTM_DEPLOYER:-$(logname 2>/dev/null || echo root)}}"; }

cmd=${1:-}; shift || true
REF=main; DRY=0; ALLOW_TRADING=0
for a in "$@"; do
  case $a in
    --dry-run) DRY=1 ;;
    --allow-trading) ALLOW_TRADING=1 ;;
    -*) die "opsi tidak dikenal: $a" ;;
    *) REF=$a ;;
  esac
done

if [ "$cmd" = status ]; then
  for k in be fe; do printf "%s: %s\n" "$k" "$(cat $BASE/state/$k.deployed 2>/dev/null || echo '(belum pernah lewat bmtm-deploy)')"; done
  pm2 jlist | python3 -c "import sys,json;[print(' ',p['name'],p['pm2_env']['status']) for p in json.load(sys.stdin)]"
  exit 0
fi
[ "$cmd" = be ] || [ "$cmd" = fe ] || { sed -n '2,11p' "$0"; exit 2; }

mkdir -p $BASE/repos $BASE/state && chmod 700 $BASE
exec 9>/run/bmtm-deploy.lock
flock -n 9 || die "deploy lain sedang berjalan"

# 1. Ambil kode dari GitHub (clone bersih terpisah dari folder live).
SRC=$BASE/repos/$cmd
[ -d $SRC/.git ] || git clone -q "${URL[$cmd]}" $SRC
git -C $SRC fetch -q --prune origin
SHA=$(git -C $SRC rev-parse --verify -q "origin/$REF^{commit}" || git -C $SRC rev-parse --verify -q "$REF^{commit}") \
  || die "ref '$REF' tidak ditemukan di GitHub"
git -C $SRC checkout -q --detach "$SHA" && git -C $SRC clean -qfdx
say "$(who) deploy $cmd $REF @ ${SHA:0:7} ($(git -C $SRC log -1 --format=%s "$SHA" | cut -c1-70))$([ $DRY = 1 ] && echo ' [dry-run]')"
TS=$(date -u +%Y%m%dT%H%M%SZ)
BK=/root/backups/deploy-$cmd-$TS

health() { for _ in $(seq 1 30); do curl -fs -m 3 -o /dev/null "$1" && return 0; sleep 1; done; return 1; }

if [ "$cmd" = be ]; then
  # 2. Jaga jalur trading live.
  if ! diff -rq --exclude=__pycache__ $SRC/src/trading $BE_LIVE/src/trading >/dev/null; then
    diff -rq --exclude=__pycache__ $SRC/src/trading $BE_LIVE/src/trading | sed 's/^/   /' | tee -a "$LOG" || true
    [ $ALLOW_TRADING = 1 ] || die "src/trading berubah (jalur trading LIVE). Butuh review + --allow-trading."
    say "PERINGATAN: src/trading ikut berubah (--allow-trading)"
  fi
  # 3. Tes penuh di salinan.
  T=$BASE/test-be; rm -rf $T; cp -a $SRC $T; rm -rf $T/.git
  say "tes backend..."
  (cd $T && LAB_ENGINE_PATH=$LAB_ENGINE PYTHONPATH=$PYTOOLS timeout 1800 $BE_PY -m pytest -q -p no:cacheprovider >$BASE/state/be-test.log 2>&1) \
    || { tail -25 $BASE/state/be-test.log; die "tes backend gagal (log: $BASE/state/be-test.log)"; }
  say "tes: $(grep -E 'passed|failed' $BASE/state/be-test.log | tail -1)"
  [ $DRY = 1 ] && { say "dry-run selesai, tidak ada yang dipasang"; exit 0; }
  M=$((10#$(date -u +%M)))
  { [ $M -ge 15 ] && [ $M -le 44 ]; } || die "backend hanya boleh di menit :15-:44 UTC (sekarang :$(date -u +%M))"
  # 4. Backup kode + lab.db.
  mkdir -p $BK && chmod 700 $BK
  tar -C $BE_LIVE -czf $BK/code.tgz --exclude=.venv --exclude=data --exclude=output --exclude=.git --exclude='__pycache__' --exclude='*.db*' --exclude='.env*' .
  $BE_PY -c "import sqlite3,sys;s=sqlite3.connect('$BE_LIVE/data/lab/lab.db');d=sqlite3.connect('$BK/lab.db');s.backup(d)" 2>/dev/null || true
  # 5. Pasang.
  if ! cmp -s $SRC/requirements.txt $BE_LIVE/requirements.txt; then
    say "requirements.txt berubah -> pip install"
    $BE_LIVE/.venv/bin/pip freeze > $BK/pip-freeze.txt
    $BE_LIVE/.venv/bin/pip install -q -r $SRC/requirements.txt || die "pip install gagal (kode belum dipasang)"
  fi
  rsync -a --exclude=.git --exclude='.env*' --exclude=data --exclude=output --exclude=.venv --exclude=__pycache__ --exclude='*.db' $SRC/ $BE_LIVE/
  pm2 restart bmtm-api bmtm-lab-worker >/dev/null
  # 6. Cek kesehatan; rollback kalau gagal.
  ok=1
  health http://127.0.0.1:8000/api/v1/health || ok=0
  code=$(curl -s -o /dev/null -w '%{http_code}' -m 5 -X POST -H 'Content-Type: application/json' \
    -d '{"action":"open","symbol":"ETH/USDT:USDT","side":"long","size_type":"percent","size_value":1,"exchange":"binance","passphrase":"bmtm-deploy-healthcheck-invalid"}' \
    http://127.0.0.1:8000/webhook/tradingview || true)
  [ "$code" = 401 ] || ok=0
  if [ $ok = 0 ]; then
    say "cek kesehatan GAGAL (webhook=$code) -> rollback"
    tar -C $BE_LIVE -xzf $BK/code.tgz
    [ -f $BK/pip-freeze.txt ] && $BE_LIVE/.venv/bin/pip install -q -r $BK/pip-freeze.txt || true
    pm2 restart bmtm-api bmtm-lab-worker >/dev/null
    health http://127.0.0.1:8000/api/v1/health && die "deploy dibatalkan, versi lama dipulihkan (backup $BK)" \
      || die "ROLLBACK JUGA GAGAL — cek manual SEGERA (backup $BK)"
  fi
  say "backend live @ ${SHA:0:7}; health 200, webhook tolak passphrase salah (401). backup $BK"
  echo "$REF ${SHA:0:7} $(date -u +%FT%TZ) $(who)" > $BASE/state/be.deployed
else
  # 2. Build di folder build terpisah.
  say "build frontend..."
  LOCK_CHANGED=1; cmp -s $SRC/package-lock.json $FE_BUILD/package-lock.json && LOCK_CHANGED=0
  rsync -a --delete --exclude=node_modules --exclude=.next --exclude='.env*' --exclude=.git $SRC/ $FE_BUILD/
  cd $FE_BUILD
  { [ $LOCK_CHANGED = 1 ] || [ ! -d node_modules ]; } && { npm ci --no-audit --no-fund >$BASE/state/fe-build.log 2>&1 || die "npm ci gagal"; }
  npx vitest run >$BASE/state/fe-test.log 2>&1 || { tail -20 $BASE/state/fe-test.log; die "tes frontend gagal"; }
  say "tes: $(grep -E 'Tests' $BASE/state/fe-test.log | tail -1 | sed 's/\x1b\[[0-9;]*m//g')"
  npm run build >>$BASE/state/fe-build.log 2>&1 || { tail -30 $BASE/state/fe-build.log; die "build gagal (live tidak disentuh)"; }
  [ $DRY = 1 ] && { say "dry-run selesai (sudah ter-build di $FE_BUILD), live tidak disentuh"; exit 0; }
  # 3. Backup + pasang.
  mkdir -p $BK && chmod 700 $BK
  tar -C $FE_LIVE -czf $BK/code.tgz --exclude=node_modules --exclude=.git --exclude='.env*' .
  rsync -a --exclude=.git --exclude='.env*' --exclude=node_modules --exclude=.next $SRC/ $FE_LIVE/
  [ $LOCK_CHANGED = 1 ] && rsync -a --delete $FE_BUILD/node_modules/ $FE_LIVE/node_modules/
  rm -rf $FE_LIVE/.next.new && cp -a $FE_BUILD/.next $FE_LIVE/.next.new
  mv $FE_LIVE/.next $FE_LIVE/.next.old && mv $FE_LIVE/.next.new $FE_LIVE/.next
  pm2 restart bmtm-web >/dev/null
  if ! health http://127.0.0.1:3000/login; then
    say "cek kesehatan GAGAL -> rollback"
    rm -rf $FE_LIVE/.next && mv $FE_LIVE/.next.old $FE_LIVE/.next && tar -C $FE_LIVE -xzf $BK/code.tgz
    pm2 restart bmtm-web >/dev/null
    die "deploy dibatalkan, versi lama dipulihkan (backup $BK)"
  fi
  rm -rf $FE_LIVE/.next.old
  say "frontend live @ ${SHA:0:7}; /login 200. backup $BK"
  echo "$REF ${SHA:0:7} $(date -u +%FT%TZ) $(who)" > $BASE/state/fe.deployed
fi

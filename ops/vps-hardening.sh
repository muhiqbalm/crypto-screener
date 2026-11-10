#!/bin/bash
# BMTM VPS hardening (audit 2026-11-10). Idempotent; dry-run unless --apply.
#
# Usage (on the VPS, from a checkout of this branch):
#   sudo ops/vps-hardening.sh                     # dry run: show what would change, all safe steps
#   sudo ops/vps-hardening.sh --apply perms needrestart fail2ban backup nginx
#   sudo ops/vps-hardening.sh --apply ssh --i-have-tested-key-login
#   sudo ops/vps-hardening.sh --apply docker-off
#
# Steps (risk / restart / live-trading impact):
#   perms        LOW  / none                      / none   chmod 600 secrets+DBs, 700 dirs
#   needrestart  LOW  / none                      / protects it (no auto-restart of pm2-root)
#   fail2ban     LOW  / fail2ban reload           / none   (TradingView IPs in ignoreip)
#   backup       LOW  / none                      / none   new backup script + restore drill cron
#   nginx        MED  / nginx reload (graceful)   / webhook block unchanged; nginx -t gated,
#                                                            auto-rollback if the post-check fails
#   ssh          HIGH / ssh reload (sessions kept)/ none   key-only login; needs --i-have-tested-key-login
#   docker-off   LOW  / stops dockerd             / none   (no containers exist)
#
# Every replaced file is copied to /root/backups/hardening-<UTC stamp>/ first.
# Nothing here touches /root/crypto-screener code, .env values, PM2 or bmtm-api.
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
APP=/root/crypto-screener
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
SAVE=/root/backups/hardening-$STAMP
APPLY=0; KEY_OK=0; STEPS=()
for a in "$@"; do
  case "$a" in
    --apply) APPLY=1 ;;
    --i-have-tested-key-login) KEY_OK=1 ;;
    -*) echo "unknown flag $a" >&2; exit 2 ;;
    *) STEPS+=("$a") ;;
  esac
done
[ ${#STEPS[@]} -gt 0 ] || STEPS=(perms needrestart fail2ban backup nginx)
[ "$(id -u)" = 0 ] || { echo "run as root" >&2; exit 1; }

say()  { printf '\033[1m[%s]\033[0m %s\n' "$1" "$2"; }
run()  { if [ $APPLY = 1 ]; then "$@"; else echo "    would run: $*"; fi; }
save() { [ -e "$1" ] || return 0; mkdir -p "$SAVE$(dirname "$1")"; cp -a "$1" "$SAVE$1"; }

# install_file SRC DST MODE -> returns 0 if changed (or would change)
install_file() {
  local src=$1 dst=$2 mode=${3:-644}
  if [ -f "$dst" ] && cmp -s "$src" "$dst"; then echo "    unchanged: $dst"; return 1; fi
  if [ -f "$dst" ]; then diff -u "$dst" "$src" | sed 's/^/    /' | head -80 || true; else echo "    new file: $dst"; fi
  if [ $APPLY = 1 ]; then save "$dst"; install -D -m "$mode" "$src" "$dst"; fi
  return 0
}

step_perms() {
  say perms "secrets and databases readable by root only"
  local f
  for f in "$APP/.env" /root/crypto-screener-fe/.env /root/crypto-screener-fe/.env.local \
           /root/fe-build/.env /root/fe-build/.env.local \
           "$APP"/bmtm_trading.db* "$APP"/data/lab/lab.db*; do
    [ -e "$f" ] || continue
    [ "$(stat -c %a "$f")" = 600 ] && continue
    echo "    $f $(stat -c %a "$f") -> 600"; run chmod 600 "$f"
  done
  for d in /root/backups "$APP/data" "$APP/data/lab" "$APP/output/logs" /root/.pm2/logs; do
    [ -d "$d" ] || continue
    [ "$(stat -c %a "$d")" = 700 ] && continue
    echo "    dir $d $(stat -c %a "$d") -> 700"; run chmod 700 "$d"
  done
  # backup snapshots taken by hand (pre-*/validation-*) may contain .env and DB copies
  local n
  n=$(find /root/backups -type f -perm /077 | wc -l)
  if [ "$n" -gt 0 ]; then echo "    $n backup files group/other-readable -> 600"; run find /root/backups -type f -perm /077 -exec chmod 600 {} +; fi
  n=$(find /root/backups -mindepth 1 -type d -perm /077 | wc -l)
  if [ "$n" -gt 0 ]; then echo "    $n backup dirs -> 700"; run find /root/backups -mindepth 1 -type d -perm /077 -exec chmod 700 {} +; fi
}

step_needrestart() {
  say needrestart "stop automatic service restarts (pm2-root owns the live webhook)"
  install_file "$HERE/needrestart/50-bmtm.conf" /etc/needrestart/conf.d/50-bmtm.conf 644 || true
}

step_fail2ban() {
  say fail2ban "sshd tuning + auth/botsearch/limit-req/recidive jails"
  local changed=0
  install_file "$HERE/fail2ban/filter.d/bmtm-auth.conf" /etc/fail2ban/filter.d/bmtm-auth.conf 644 && changed=1
  install_file "$HERE/fail2ban/bmtm.local" /etc/fail2ban/jail.d/bmtm.local 644 && changed=1
  if [ $changed = 1 ]; then
    if [ $APPLY = 1 ]; then
      fail2ban-client -t >/dev/null || { echo "    fail2ban config test FAILED - restoring" >&2
        for f in /etc/fail2ban/filter.d/bmtm-auth.conf /etc/fail2ban/jail.d/bmtm.local; do
          if [ -e "$SAVE$f" ]; then cp -a "$SAVE$f" "$f"; else rm -f "$f"; fi; done; return 1; }
      fail2ban-client reload
      fail2ban-client status | sed 's/^/    /'
    else
      echo "    would run: fail2ban-client -t && fail2ban-client reload"
    fi
  fi
}

step_backup() {
  say backup "full daily backup (both DBs + configs, integrity-checked) + weekly restore drill"
  install_file "$HERE/backup/bmtm-backup.sh" /usr/local/bin/bmtm-backup.sh 700 || true
  install_file "$HERE/backup/bmtm-restore-test.sh" /usr/local/bin/bmtm-restore-test.sh 700 || true
  local cron; cron=$(mktemp)
  cat > "$cron" <<'CRON'
30 2 * * * root /usr/local/bin/bmtm-backup.sh >/dev/null 2>&1
15 3 * * 1 root /usr/local/bin/bmtm-restore-test.sh >> /var/log/bmtm-backup.log 2>&1
CRON
  install_file "$cron" /etc/cron.d/bmtm-backup 644 || true
  rm -f "$cron"
  if [ ! -f /etc/default/bmtm-backup ]; then
    echo "    new file: /etc/default/bmtm-backup (off-site disabled until AGE_RECIPIENT + RCLONE_REMOTE are set)"
    if [ $APPLY = 1 ]; then
      install -m 600 /dev/null /etc/default/bmtm-backup
      printf '%s\n' '# AGE_RECIPIENT=age1...        # public key; keep the private key OFF this server' \
                    '# RCLONE_REMOTE=remote:bucket   # configure with: rclone config' \
                    'ALERT_TELEGRAM=1' > /etc/default/bmtm-backup
    fi
  fi
  if [ $APPLY = 1 ]; then
    /usr/local/bin/bmtm-backup.sh && /usr/local/bin/bmtm-restore-test.sh | sed 's/^/    /'
  fi
}

step_nginx() {
  say nginx "security headers, rate limits, debug API not public, server_tokens off"
  local site=/etc/nginx/sites-available/bmtm-trade.duckdns.org
  local changed=0
  # Guard: the webhook location in the template must equal production's.
  local want have
  want=$(sed -n '/location = \/webhook\/tradingview {/,/}/p' "$HERE/nginx/bmtm-trade.duckdns.org.conf")
  have=$(sed -n '/location = \/webhook\/tradingview {/,/}/p' "$site")
  if [ "$want" != "$have" ]; then
    echo "    ABORT: production webhook block differs from the template; reconcile by hand" >&2; return 1
  fi
  install_file "$HERE/nginx/bmtm-http.conf" /etc/nginx/conf.d/bmtm-http.conf 644 && changed=1
  install_file "$HERE/nginx/bmtm-security-headers.conf" /etc/nginx/snippets/bmtm-security-headers.conf 644 && changed=1
  install_file "$HERE/nginx/bmtm-trade.duckdns.org.conf" "$site" 644 && changed=1
  [ $changed = 1 ] || return 0
  if [ $APPLY = 0 ]; then echo "    would run: nginx -t && systemctl reload nginx && post-checks"; return 0; fi
  rollback() {
    echo "    rolling back nginx" >&2
    for f in /etc/nginx/conf.d/bmtm-http.conf /etc/nginx/snippets/bmtm-security-headers.conf "$site"; do
      if [ -e "$SAVE$f" ]; then cp -a "$SAVE$f" "$f"; else rm -f "$f"; fi
    done
    nginx -t && systemctl reload nginx
  }
  nginx -t || { rollback; return 1; }
  systemctl reload nginx; sleep 1
  local h=https://bmtm-trade.duckdns.org ok=1 c
  # GET never reaches the webhook handler (FastAPI answers 405), but proves
  # nginx still routes the path to bmtm-api.
  c=$(curl -s -o /dev/null -w '%{http_code}' -m 10 "$h/webhook/tradingview")
  echo "    webhook GET -> $c (expect 405 from bmtm-api)"; [ "$c" = 405 ] || ok=0
  c=$(curl -s -o /dev/null -w '%{http_code}' -m 10 "$h/api/v1/health"); echo "    /api/v1/health -> $c"; [ "$c" = 200 ] || ok=0
  c=$(curl -s -o /dev/null -w '%{http_code}' -m 10 "$h/login"); echo "    /login -> $c"; case $c in 200|307|308) ;; *) ok=0;; esac
  c=$(curl -s -o /dev/null -w '%{http_code}' -m 10 "$h/api/v1/debug/health"); echo "    /api/v1/debug/health -> $c (expect 404)"
  curl -sI -m 10 "$h/" | grep -iE '^(strict-transport|x-frame|x-content-type)' | sed 's/^/    /'
  [ $ok = 1 ] || { rollback; return 1; }
}

step_ssh() {
  say ssh "key-only login, no X11, fewer auth tries"
  local keys
  keys=$(grep -cE '^(ssh-|ecdsa-|sk-)' /root/.ssh/authorized_keys 2>/dev/null || echo 0)
  echo "    root authorized_keys entries: $keys"
  if [ "$keys" = 0 ]; then echo "    ABORT: no authorized key - you would be locked out" >&2; return 1; fi
  if [ $APPLY = 1 ] && [ $KEY_OK = 0 ]; then
    echo "    ABORT: first log in with your key in a NEW terminal (ssh -o PasswordAuthentication=no root@host)," >&2
    echo "           then re-run with --i-have-tested-key-login. Keep the current session open." >&2
    return 1
  fi
  install_file "$HERE/ssh/00-bmtm-hardening.conf" /etc/ssh/sshd_config.d/00-bmtm-hardening.conf 644 || return 0
  if [ $APPLY = 1 ]; then
    sshd -t || { echo "    sshd -t failed - restoring" >&2; rm -f /etc/ssh/sshd_config.d/00-bmtm-hardening.conf; return 1; }
    systemctl reload ssh
    sshd -T | grep -E '^(passwordauthentication|permitrootlogin|x11forwarding|maxauthtries) ' | sed 's/^/    /'
  fi
}

step_docker-off() {
  say docker-off "dockerd runs as root with no containers; stop and disable it"
  if [ -n "$(docker ps -aq 2>/dev/null)" ]; then echo "    ABORT: containers exist" >&2; return 1; fi
  run systemctl disable --now docker.socket docker.service containerd.service
  echo "    (cron jobs in /etc/cron.d/docker-* become no-ops; remove them if docker stays off)"
}

for s in "${STEPS[@]}"; do
  case "$s" in
    perms|needrestart|fail2ban|backup|nginx|ssh|docker-off) "step_$s" ;;
    *) echo "unknown step: $s" >&2; exit 2 ;;
  esac
done
[ $APPLY = 1 ] && [ -d "$SAVE" ] && say done "previous files saved under $SAVE"
[ $APPLY = 0 ] && say dry-run "nothing changed; re-run with --apply <steps>"
exit 0

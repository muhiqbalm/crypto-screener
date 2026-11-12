#!/bin/bash
# add_team_ssh_key — pasang public key SSH (ed25519) anggota tim BMTM untuk login root.
#
#   bash ops/add_team_ssh_key.sh <nama> <file.pub | ->            cek saja (dry-run)
#   bash ops/add_team_ssh_key.sh <nama> <file.pub | -> --apply    backup, lalu tambahkan
#   bash ops/add_team_ssh_key.sh --list                           key aktif: fingerprint + komentar
#
# - Hanya MENAMBAH satu baris di akhir /root/.ssh/authorized_keys. Baris lain (termasuk yang
#   dinonaktifkan dengan '#' atau dikelola panel Hostinger) tidak diubah.
# - Idempotent: key yang sudah aktif tidak ditambah lagi (exit 0, tanpa perubahan).
# - Sebelum menulis, file disalin ke /root/backups/ssh-<UTC>.<acak>/authorized_keys.
#   Kalau cek sesudah menulis gagal, file dikembalikan dari backup.
# - Tidak mengubah sshd_config: password root tetap aktif sampai tim memutuskan
#   (matikan lewat ops/vps-hardening.sh ssh setelah key semua anggota lolos tes).
# - Tidak pernah mencetak isi key; yang ditampilkan hanya fingerprint dan komentar.
#
# Opsi: --allow-disabled  izinkan key yang pernah dinonaktifkan ('#') dipasang lagi.
# Pelaku tercatat di komentar key: BMTM_DEPLOYER=andra bash ops/add_team_ssh_key.sh ...
# Uji lokal tanpa root: BMTM_AUTHORIZED_KEYS, BMTM_BACKUP_DIR, BMTM_SSH_LOCK (path lain).
set -euo pipefail

AK=${BMTM_AUTHORIZED_KEYS:-/root/.ssh/authorized_keys}
BACKUPS=${BMTM_BACKUP_DIR:-/root/backups}
LOCK=${BMTM_SSH_LOCK:-/run/bmtm-ssh-keys.lock}
HOST=${BMTM_HOST:-72.60.201.108}
TAG=bmtm-team

die()   { echo "GAGAL: $*" >&2; exit 1; }
warn()  { echo "PERINGATAN: $*" >&2; }
usage() { sed -n '2,6p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
who()   { echo "${SUDO_USER:-${BMTM_DEPLOYER:-$(logname 2>/dev/null || echo root)}}" | tr -cd 'A-Za-z0-9._-'; }
# Komentar bisa memuat key lain (baris yang menempel); sensor sebelum dicetak.
mask()  { LC_ALL=C tr -cd '[:print:]\n' | sed -E 's#AAAA[A-Za-z0-9+/=]{16,}#<key>#g'; }

# Fingerprint (SHA256) + komentar tiap key aktif di file; kosong kalau tidak ada.
fingerprints() { [ -s "$1" ] || return 0; ssh-keygen -l -E sha256 -f "$1" </dev/null 2>/dev/null || true; }

APPLY=0; ALLOW_DISABLED=0; LIST=0; NAME=; SRC=
for a in "$@"; do
  case $a in
    --apply) APPLY=1 ;;
    --allow-disabled) ALLOW_DISABLED=1 ;;
    --list) LIST=1 ;;
    -h|--help) usage ;;
    -?*) die "opsi tidak dikenal: $a" ;;
    *) if [ -z "$NAME" ]; then NAME=$a; elif [ -z "$SRC" ]; then SRC=$a; else usage; fi ;;
  esac
done

if [ -z "${BMTM_AUTHORIZED_KEYS:-}" ] && [ "$(id -u)" != 0 ]; then die "jalankan sebagai root"; fi
command -v ssh-keygen >/dev/null || die "ssh-keygen tidak ada"

if [ $LIST = 1 ]; then
  echo "Key aktif di $AK:"
  out=$(fingerprints "$AK")
  if [ -n "$out" ]; then printf '%s\n' "$out" | mask | sed 's/^/  /'; else echo "  (tidak ada)"; fi
  echo "Baris diawali '#' (komentar/dinonaktifkan): $( (grep -cE '^[[:space:]]*#' "$AK" 2>/dev/null) || true)"
  exit 0
fi
[ -n "$NAME" ] && [ -n "$SRC" ] || usage

# ---- 1. Validasi nama dan key (belum menyentuh authorized_keys) ----
[[ $NAME =~ ^[a-z][a-z0-9-]{1,30}$ ]] \
  || die "nama '$NAME' tidak valid: huruf kecil, angka, '-', 2-31 karakter, diawali huruf (contoh: iqbal)"

WORK=$(mktemp -d); trap 'rm -rf "$WORK"' EXIT
if [ "$SRC" = - ]; then cat > "$WORK/in"; else [ -f "$SRC" ] || die "file tidak ada: $SRC"; cat -- "$SRC" > "$WORK/in"; fi
[ "$(wc -c < "$WORK/in")" -le 16384 ] || die "file terlalu besar untuk satu public key"
# File berisi byte NUL = UTF-16 (mis. disimpan ulang lewat PowerShell): ubah ke UTF-8.
if ! LC_ALL=C tr -d '\000' < "$WORK/in" | cmp -s - "$WORK/in"; then
  iconv -f UTF-16 -t UTF-8 < "$WORK/in" > "$WORK/in8" 2>/dev/null \
    || die "file bukan teks biasa; minta $NAME mengirim isi id_ed25519.pub sebagai teks"
  mv "$WORK/in8" "$WORK/in"
fi
if LC_ALL=C grep -qE 'PRIVATE KEY|PuTTY-User-Key-File' "$WORK/in"; then
  die "INI PRIVATE KEY, bukan public key. Jangan dipasang, jangan diteruskan, hapus file ini.
       Key ini dianggap bocor: minta $NAME membuat key BARU lalu kirim hanya file .pub."
fi

raw=$(LC_ALL=C tr -d '\r' < "$WORK/in")
raw=${raw#$'\xEF\xBB\xBF'}
n=$(printf '%s\n' "$raw" | awk 'NF' | wc -l | tr -d ' ')
[ "$n" = 1 ] || die "harus tepat 1 baris key, ditemukan $n (lebih dari satu key, atau key terpotong jadi beberapa baris saat disalin)."
line=$(printf '%s\n' "$raw" | awk 'NF')
read -r ktype kblob kcomment <<< "$line" || true

case $ktype in
  ssh-ed25519) ;;
  ssh-rsa|ssh-dss|ecdsa-sha2-*|sk-*) die "key bertipe $ktype; tim memakai ed25519: ssh-keygen -t ed25519 -C \"$NAME-bmtm\"" ;;
  *) die "baris harus diawali 'ssh-ed25519 AAAA...' tanpa opsi di depannya" ;;
esac
[[ ${kblob:-} =~ ^AAAAC3NzaC1lZDI1NTE5AAAAI[A-Za-z0-9+/]{43}$ ]] \
  || die "isi key rusak atau terpotong (cek tidak ada spasi atau baris yang terputus waktu disalin)"
printf '%s %s %s\n' "$ktype" "$kblob" "$NAME" > "$WORK/key.pub"
fpline=$(ssh-keygen -l -E sha256 -f "$WORK/key.pub" </dev/null 2>/dev/null) || die "ssh-keygen menolak key ini (rusak)"
case $fpline in *"(ED25519)") ;; *) die "ssh-keygen tidak mengenali key ini sebagai ED25519" ;; esac
fp=$(printf '%s\n' "$fpline" | awk '{print $2}')
echo "Key valid: ED25519 $fp (komentar dari pengirim: $(printf '%s' "${kcomment:-kosong}" | mask | cut -c1-80))"
case $(printf '%s' "${kcomment:-}" | tr '[:upper:]' '[:lower:]') in
  *"$NAME"*) ;;
  *) warn "komentar key tidak memuat '$NAME'. Pastikan file ini memang dari $NAME." ;;
esac

# ---- 2. Cek terhadap authorized_keys (di dalam lock kalau --apply) ----
if [ $APPLY = 1 ] && command -v flock >/dev/null 2>&1; then
  exec 9>"$LOCK"; flock -n 9 || die "proses lain sedang mengubah authorized_keys"
fi
touch_ak=0; [ -e "$AK" ] || touch_ak=1
if [ $touch_ak = 0 ]; then
  # Key aktif = field tepat sesudah field tipe-key pertama di baris yang tidak diawali '#'.
  found=$(awk -v b="$kblob" '!/^[[:space:]]*#/ {
      for (i = 1; i < NF; i++) if ($i ~ /^(ssh-|ecdsa-|sk-)/) {
        if ($(i+1) == b) { c = ""; for (j = i + 2; j <= NF; j++) c = c (c == "" ? "" : " ") $j; print NR ": " c; exit }
        break } }' "$AK")
  if [ -n "$found" ]; then
    echo "Sudah terpasang di baris $(printf '%s' "$found" | mask). Tidak ada perubahan."
    case $found in *"$TAG:$NAME "*|*"$TAG:$NAME") ;; *) warn "key ini terdaftar dengan komentar lain (lihat di atas)." ;; esac
    exit 0
  fi
  off=$(awk -v b="$kblob" '/^[[:space:]]*#/ && index($0, b) { print NR; exit }' "$AK")
  if [ -n "$off" ] && [ $ALLOW_DISABLED = 0 ]; then
    die "key ini pernah DINONAKTIFKAN (baris $off). Kalau memang mau dipakai lagi, ulangi dengan --allow-disabled."
  fi
  taken=$(awk -v t="$TAG:$NAME" '!/^[[:space:]]*#/ { for (i = 1; i <= NF; i++) if ($i == t) { print NR; exit } }' "$AK")
  if [ -n "$taken" ]; then
    die "nama '$NAME' sudah dipakai key lain (baris $taken). Laptop kedua: pakai nama $NAME-2.
       Ganti key: nonaktifkan baris lama dulu (beri '#' di depannya), lalu ulangi."
  fi
fi

NEWLINE="$ktype $kblob $TAG:$NAME added=$(date -u +%F) by=$(who)"
if [ $APPLY = 0 ]; then
  echo "Akan ditambahkan ke $AK sebagai: $TAG:$NAME added=$(date -u +%F) by=$(who)"
  echo "Dry-run: belum ada yang diubah. Ulangi dengan --apply."
  exit 0
fi

# ---- 3. Backup, tambah satu baris, cek, pulihkan kalau gagal ----
mkdir -p "$BACKUPS"
BK=$(mktemp -d "$BACKUPS/ssh-$(date -u +%Y%m%dT%H%M%SZ).XXXX")
if [ $touch_ak = 1 ]; then
  mkdir -p "$(dirname "$AK")"; chmod 700 "$(dirname "$AK")"
  (umask 077; : > "$AK")
  echo "(file baru: $AK)" > "$BK/BELUM-ADA"
else
  cp -p "$AK" "$BK/authorized_keys"
  cmp -s "$AK" "$BK/authorized_keys" || die "backup tidak sama dengan aslinya; tidak ada yang diubah"
fi
before=$(fingerprints "$AK" | awk 'NF' | wc -l | tr -d ' ')

restore() {
  if [ -f "$BK/authorized_keys" ]; then cp -p "$BK/authorized_keys" "$AK"; else rm -f "$AK"; fi
  die "$1. authorized_keys dikembalikan ke keadaan sebelum skrip (backup: $BK)."
}
# Baris terakhir tanpa newline akan menempel ke key baru dan merusak keduanya.
if [ -s "$AK" ] && [ -n "$(tail -c 1 "$AK")" ]; then printf '\n' >> "$AK"; fi
printf '%s\n' "$NEWLINE" >> "$AK"
chmod 600 "$AK"

if [ -f "$BK/authorized_keys" ]; then
  size=$(wc -c < "$BK/authorized_keys" | tr -d ' ')
  head -c "$size" "$AK" | cmp -s - "$BK/authorized_keys" || restore "isi lama ikut berubah"
fi
after=$(fingerprints "$AK")
printf '%s\n' "$after" | grep -qF " $fp " || restore "key baru tidak terbaca oleh ssh-keygen"
[ "$(printf '%s\n' "$after" | awk 'NF' | wc -l | tr -d ' ')" = $((before + 1)) ] || restore "jumlah key aktif tidak bertambah tepat 1"

echo "OK: key $NAME dipasang ($fp). Key aktif sekarang: $((before + 1)). Backup: $BK"
echo "Minta $NAME tes dari laptopnya: ssh -o PreferredAuthentications=publickey root@$HOST echo BMTM-OK"

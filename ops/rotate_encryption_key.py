#!/usr/bin/env python3
"""Re-encrypt stored exchange credentials under a new Fernet key.

TRADING_ENCRYPTION_KEY has never been rotated and copies of it sit in old
backup snapshots. This re-wraps every ``*_encrypted`` column of
``exchange_credentials`` with ``MultiFernet([new, old]).rotate()``: the
ciphertext is decrypted and re-encrypted in memory, plaintext is never written
or printed.

Run in a maintenance window (it is part of the live-trading setup):

    pm2 stop bmtm-api                       # no webhook may read creds mid-rotation
    NEW_KEY=$(/root/crypto-screener/.venv/bin/python -c \
        "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
    OLD_KEY=$(grep ^TRADING_ENCRYPTION_KEY= /root/crypto-screener/.env | cut -d= -f2-)
    OLD_KEY=$OLD_KEY NEW_KEY=$NEW_KEY /root/crypto-screener/.venv/bin/python \
        ops/rotate_encryption_key.py /root/crypto-screener/bmtm_trading.db          # dry run
    ... same command with --apply
    # then set TRADING_ENCRYPTION_KEY=$NEW_KEY in .env (chmod 600) and:
    pm2 start bmtm-api   # verify GET /trading/users/me/credentials and balance work

--apply first writes a backup copy of the DB next to it (mode 600) and does
the update in a single transaction; any failure rolls back.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

COLUMNS = ("api_key_encrypted", "secret_encrypted", "passphrase_encrypted")


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    apply = "--apply" in argv
    if len(args) != 1:
        print(__doc__)
        return 2
    db_path = args[0]
    old_key, new_key = os.environ.get("OLD_KEY", ""), os.environ.get("NEW_KEY", "")
    if not old_key or not new_key:
        print("OLD_KEY and NEW_KEY must be set in the environment", file=sys.stderr)
        return 2
    if old_key == new_key:
        print("NEW_KEY equals OLD_KEY", file=sys.stderr)
        return 2
    old, new = Fernet(old_key.encode()), Fernet(new_key.encode())
    multi = MultiFernet([new, old])

    conn = sqlite3.connect(db_path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(exchange_credentials)")}
    targets = [c for c in COLUMNS if c in cols]
    rows = conn.execute(f"SELECT id, {', '.join(targets)} FROM exchange_credentials").fetchall()

    updates = []
    for row in rows:
        row_id, values = row[0], row[1:]
        new_values = {}
        for col, token in zip(targets, values):
            if not token:
                continue
            try:
                old.decrypt(token.encode())
            except InvalidToken:
                print(f"row {row_id}: {col} is not decryptable with OLD_KEY - aborting", file=sys.stderr)
                return 1
            rotated = multi.rotate(token.encode()).decode()
            new.decrypt(rotated.encode())  # verify round trip under the new key
            new_values[col] = rotated
        updates.append((row_id, new_values))

    print(f"{len(updates)} credential rows, {sum(len(v) for _, v in updates)} fields to re-encrypt")
    if not apply:
        print("dry run OK (re-run with --apply)")
        return 0

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = f"{db_path}.pre-key-rotation-{stamp}"
    conn.close()
    shutil.copy2(db_path, backup)
    os.chmod(backup, 0o600)
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            for row_id, values in updates:
                if values:
                    sets = ", ".join(f"{c} = ?" for c in values)
                    conn.execute(f"UPDATE exchange_credentials SET {sets} WHERE id = ?", (*values.values(), row_id))
    finally:
        conn.close()
    print(f"applied; backup of the previous DB: {backup}")
    print("now set TRADING_ENCRYPTION_KEY to NEW_KEY in .env and restart bmtm-api")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

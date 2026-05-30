"""
Debug script — cek balance dan margin info dari OKX testnet.
Jalankan: python3.11 debug_okx_balance.py
"""
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

async def main():
    import ccxt.async_support as ccxt
    from cryptography.fernet import Fernet
    from supabase import create_client

    # Baca langsung dari env — bypass TradingSettings untuk hindari SCREENER_ conflict
    supabase_url = os.environ["TRADING_SUPABASE_URL"]
    supabase_key = os.environ["TRADING_SUPABASE_KEY"]
    encryption_key = os.environ["TRADING_ENCRYPTION_KEY"]

    supabase = create_client(supabase_url, supabase_key)
    fernet = Fernet(encryption_key.encode())

    user_id = input("Masukkan user_id Anda: ").strip()

    # Ambil credentials dari DB
    response = (
        supabase.table("exchange_credentials")
        .select("api_key_encrypted, secret_encrypted, passphrase_encrypted")
        .eq("user_id", user_id)
        .eq("exchange", "okx")
        .execute()
    )

    if not response.data:
        print("ERROR: Tidak ada OKX credentials untuk user ini")
        return

    row = response.data[0]
    api_key = fernet.decrypt(row["api_key_encrypted"].encode()).decode()
    secret  = fernet.decrypt(row["secret_encrypted"].encode()).decode()
    passphrase = ""
    if row.get("passphrase_encrypted"):
        passphrase = fernet.decrypt(row["passphrase_encrypted"].encode()).decode()

    print(f"\nCredentials OK: api_key={api_key[:8]}...")

    exchange = ccxt.okx({
        "apiKey": api_key,
        "secret": secret,
        "password": passphrase,
        "sandbox": True,
        "options": {"defaultType": "future"},
    })

    try:
        await exchange.load_markets()
        print("Markets loaded OK")

        print("\n--- Balance (type=trading) ---")
        bal = await exchange.fetch_balance({"type": "trading"})
        usdt_free  = float(bal.get("free",  {}).get("USDT") or 0)
        usdt_total = float(bal.get("total", {}).get("USDT") or 0)
        print(f"USDT free:  {usdt_free}")
        print(f"USDT total: {usdt_total}")

        print("\n--- Balance (default) ---")
        bal2 = await exchange.fetch_balance()
        usdt_free2 = float(bal2.get("free", {}).get("USDT") or 0)
        print(f"USDT free (default): {usdt_free2}")

        # Cek semua currency yang ada
        all_currencies = {k: v for k, v in bal.get("total", {}).items() if v and float(v) > 0}
        print(f"Non-zero balances: {all_currencies}")

        print("\n--- DOGE ticker ---")
        ticker = await exchange.fetch_ticker("DOGE/USDT:USDT")
        price = float(ticker["last"])
        print(f"DOGE price: {price}")

        leverage   = 10
        size_pct   = 0.75
        margin     = usdt_free * size_pct
        notional   = margin * leverage
        qty        = notional / price

        print(f"\n--- Kalkulasi Order ---")
        print(f"Balance free : {usdt_free:.4f} USDT")
        print(f"Size         : {size_pct*100:.0f}%")
        print(f"Leverage     : {leverage}x")
        print(f"Margin used  : {margin:.4f} USDT")
        print(f"Notional     : {notional:.4f} USDT")
        print(f"Quantity     : {qty:.2f} DOGE")
        print(f"Min order    : 1 DOGE")
        print(f"Cukup?       : {'YES ✅' if qty >= 1 else 'NO ❌'}")

        print("\n--- Account config ---")
        try:
            cfg = await exchange.private_get_account_config()
            acct_lv = cfg.get("data", [{}])[0].get("acctLv", "unknown")
            pos_mode = cfg.get("data", [{}])[0].get("posMode", "unknown")
            print(f"Account level : {acct_lv}  (1=simple, 2=single-currency, 3=multi-currency, 4=portfolio)")
            print(f"Position mode : {pos_mode}  (long_short_mode or net_mode)")
        except Exception as e:
            print(f"Could not fetch account config: {e}")

    finally:
        await exchange.close()

asyncio.run(main())

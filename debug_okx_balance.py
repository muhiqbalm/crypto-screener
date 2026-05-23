"""
Debug script — cek balance dan margin info dari OKX testnet.
Jalankan: python debug_okx_balance.py
"""
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

async def main():
    import ccxt.async_support as ccxt

    # Baca credentials dari env
    from src.trading.config import TradingSettings
    from src.trading.credentials import CredentialStore
    from supabase import create_client

    settings = TradingSettings()
    supabase = create_client(settings.supabase_url, settings.supabase_key)
    store = CredentialStore(settings.encryption_key, supabase)

    # Ganti dengan user_id Anda
    user_id = input("Masukkan user_id Anda: ").strip()

    creds = await store.get_credentials(user_id, "okx")
    print(f"\nCredentials ditemukan: api_key={creds['api_key'][:8]}...")

    exchange = ccxt.okx({
        "apiKey": creds["api_key"],
        "secret": creds["secret"],
        "password": creds.get("passphrase", ""),
        "sandbox": True,
        "options": {"defaultType": "future"},
    })

    try:
        print("\n--- Checking balance (type=trading) ---")
        bal = await exchange.fetch_balance({"type": "trading"})
        usdt_free = bal.get("free", {}).get("USDT", 0)
        usdt_total = bal.get("total", {}).get("USDT", 0)
        print(f"USDT free:  {usdt_free}")
        print(f"USDT total: {usdt_total}")

        print("\n--- Checking balance (no params) ---")
        bal2 = await exchange.fetch_balance()
        usdt_free2 = bal2.get("free", {}).get("USDT", 0)
        print(f"USDT free (no params): {usdt_free2}")

        print("\n--- Account config ---")
        try:
            config = await exchange.private_get_account_config()
            print(f"Account config: {config}")
        except Exception as e:
            print(f"Could not fetch account config: {e}")

        print("\n--- DOGE ticker ---")
        ticker = await exchange.fetch_ticker("DOGE/USDT:USDT")
        print(f"DOGE price: {ticker['last']}")

        leverage = 10
        size_pct = 0.75
        price = ticker['last']
        margin = usdt_free * size_pct
        notional = margin * leverage
        qty = notional / price
        print(f"\n--- Kalkulasi Order ---")
        print(f"Balance free : {usdt_free:.4f} USDT")
        print(f"Size         : {size_pct*100:.0f}%")
        print(f"Leverage     : {leverage}x")
        print(f"Margin used  : {margin:.4f} USDT")
        print(f"Notional     : {notional:.4f} USDT")
        print(f"Quantity     : {qty:.4f} DOGE")
        print(f"Min order    : 1 DOGE")
        print(f"Cukup?       : {'YES ✅' if qty >= 1 else 'NO ❌'}")

    finally:
        await exchange.close()

asyncio.run(main())

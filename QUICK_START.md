# 🚀 Quick Start Guide - Crypto Screener

## ⚡ Cara Cepat Menjalankan

### Di Linux/Server
```bash
cd ~/crypto-screener
python3.11 main.py
```

### Di Windows
```bash
cd d:\WORK\CRYPTO-SCREENER\crypto-screener
py main.py
```

## 📋 Prerequisites

```bash
# Install dependencies
pip install -r requirements.txt

# Required packages:
# - ccxt
# - pandas
# - numpy
# - matplotlib
# - seaborn
```

## 🎯 Apa yang Akan Terjadi

Ketika Anda menjalankan `main.py`, sistem akan:

1. **Connect ke OKX Exchange** ✅
2. **Fetch data untuk 7 cryptocurrency**:
   - BTC/USDT:USDT (Bitcoin)
   - ETH/USDT:USDT (Ethereum)
   - ZEC/USDT:USDT (Zcash)
   - TAO/USDT:USDT (Bittensor)
   - TON/USDT:USDT (Toncoin)
   - AAVE/USDT:USDT (Aave)
   - SOL/USDT:USDT (Solana)

3. **Generate trading signals** 📊
4. **Calculate multi-factor scores** 🧮
5. **Rank assets** 🏆
6. **Create visualization dashboard** 📈
7. **Save dashboard image** 💾

## 📂 Output Files

Setelah running, Anda akan menemukan:

```
output/
├── logs/
│   └── crypto_screener_YYYYMMDD_HHMMSS.log
└── dashboards/
    └── crypto_screener_dashboard_YYYYMMDD_HHMMSS.png
```

## 🔍 Melihat Hasil

Dashboard akan berisi 3 panel:
1. **Multi-Factor Score Panel** - Ranking cryptocurrency
2. **Funding Rate Panel** - Funding rate analysis
3. **Long/Short Ratio Panel** - Market sentiment

## ⚠️ Troubleshooting

### Error: ModuleNotFoundError
```bash
# Jalankan script ekstraksi modul
py extract_modules.py
```

### Error: No internet connection
- Pastikan koneksi internet aktif
- OKX exchange memerlukan akses internet

### Error: Missing dependencies
```bash
pip install -r requirements.txt
```

## 🆚 Dua Cara Menjalankan

### Cara 1: Modular (Recommended) ⭐
```bash
python3.11 main.py
```
- Menggunakan struktur modular
- Best practices Python
- Mudah di-maintain

### Cara 2: Monolithic (Backward Compatibility)
```bash
python3.11 crypto_screener.py
```
- File original
- Semua dalam 1 file
- Untuk compatibility

## 📚 Dokumentasi Lengkap

- `README_NEW_STRUCTURE.md` - Struktur project
- `REORGANIZATION_SUMMARY.md` - Ringkasan reorganisasi
- `FIX_APPLIED.md` - Penjelasan fix error
- `docs/` - Dokumentasi detail

## 🎉 Selesai!

Sekarang Anda bisa menjalankan crypto screener dengan mudah!

```bash
python3.11 main.py
```

Happy screening! 🚀📈

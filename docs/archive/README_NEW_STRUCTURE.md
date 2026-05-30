# Crypto Screener - Struktur Project Baru

## 📁 Struktur Directory

```
crypto-screener/
├── src/                          # Source code modular
│   ├── exchange/                 # Modul koneksi exchange
│   │   ├── __init__.py
│   │   └── connector.py          # ExchangeConnector class
│   ├── data/                     # Modul pengambilan data
│   │   ├── __init__.py
│   │   └── fetcher.py            # MarketDataFetcher class (akan dibuat)
│   ├── signals/                  # Modul signal trading
│   │   ├── __init__.py
│   │   ├── generator.py          # SignalGenerator class (akan dibuat)
│   │   ├── ic_weights.py         # ICWeightCalculator class (akan dibuat)
│   │   └── scorer.py             # MultiFactorScorer class (akan dibuat)
│   ├── ranking/                  # Modul ranking
│   │   ├── __init__.py
│   │   └── engine.py             # RankingEngine class (akan dibuat)
│   ├── visualization/            # Modul visualisasi
│   │   ├── __init__.py
│   │   ├── panels.py             # Panel classes (akan dibuat)
│   │   └── dashboard.py          # DashboardBuilder class (akan dibuat)
│   └── utils/                    # Utilities
│       ├── __init__.py
│       └── logger.py             # Logging configuration (akan dibuat)
│
├── tests/                        # Test files (sudah dipindahkan)
│   ├── test_exchange/
│   ├── test_data/
│   ├── test_signals/
│   ├── test_ranking/
│   └── test_visualization/
│
├── demos/                        # Demo scripts (sudah dipindahkan)
│   ├── demo_exchange_connector.py
│   ├── demo_fetch_all_data.py
│   └── ...
│
├── docs/                         # Documentation (sudah dipindahkan)
│   ├── ERROR_HANDLING_SUMMARY.md
│   ├── TASK_*.md
│   └── RESTRUCTURE_PLAN.md
│
├── output/                       # Output files
│   ├── logs/                     # Log files (sudah dipindahkan)
│   └── dashboards/               # Dashboard images (sudah dipindahkan)
│
├── main.py                       # Entry point baru (modular)
├── crypto_screener.py            # File original (backward compatibility)
├── reorganize.py                 # Script reorganisasi
├── requirements.txt
├── .gitignore
└── README.md
```

## 🚀 Cara Menggunakan

### Opsi 1: Menggunakan File Original (Monolithic)
```bash
py crypto_screener.py
```

### Opsi 2: Menggunakan Struktur Baru (Modular) - RECOMMENDED
```bash
py main.py
```

## ✅ Yang Sudah Selesai

1. ✅ Struktur directory dibuat
2. ✅ Test files dipindahkan ke `tests/`
3. ✅ Demo files dipindahkan ke `demos/`
4. ✅ Documentation dipindahkan ke `docs/`
5. ✅ Log files dipindahkan ke `output/logs/`
6. ✅ Dashboard images dipindahkan ke `output/dashboards/`
7. ✅ `.gitignore` diupdate
8. ✅ `main.py` entry point dibuat
9. ✅ `src/exchange/connector.py` dibuat

## 📝 Yang Perlu Dilakukan Selanjutnya

Untuk membuat project sepenuhnya modular, class-class berikut perlu diekstrak dari `crypto_screener.py` ke modul masing-masing:

1. **src/data/fetcher.py** - MarketDataFetcher class
2. **src/signals/generator.py** - SignalGenerator class
3. **src/signals/ic_weights.py** - ICWeightCalculator class
4. **src/signals/scorer.py** - MultiFactorScorer class
5. **src/ranking/engine.py** - RankingEngine class
6. **src/visualization/panels.py** - MultiFactorPanel, FundingRatePanel, LongShortRatioPanel
7. **src/visualization/dashboard.py** - DashboardBuilder class
8. **src/utils/logger.py** - Logging configuration

## 🎯 Keuntungan Struktur Baru

1. **Modular**: Setiap komponen dalam modul terpisah
2. **Maintainable**: Mudah menemukan dan mengupdate kode
3. **Testable**: Test terorganisir per modul
4. **Scalable**: Mudah menambah fitur baru
5. **Clean**: Pemisahan concerns yang jelas
6. **Professional**: Struktur yang mengikuti best practices Python

## 📊 Perbandingan

### Struktur Lama
- 1 file besar (1680 baris)
- Semua class dalam 1 file
- Test files tercampur dengan source
- Log files di root directory

### Struktur Baru
- Modular (8+ file terpisah)
- Setiap class dalam modul sendiri
- Test files terorganisir per modul
- Output files dalam directory khusus

## 🔧 Development

### Running Tests
```bash
# Test semua
pytest tests/

# Test specific module
pytest tests/test_exchange/
pytest tests/test_data/
pytest tests/test_signals/
```

### Adding New Features
1. Buat modul baru di `src/`
2. Buat test di `tests/`
3. Update `main.py` jika perlu
4. Update documentation

## 📚 Documentation

Lihat `docs/` untuk dokumentasi lengkap:
- `RESTRUCTURE_PLAN.md` - Rencana reorganisasi
- `ERROR_HANDLING_SUMMARY.md` - Error handling strategy
- `TASK_*.md` - Task summaries

## 🤝 Contributing

1. Fork the repository
2. Create feature branch
3. Make changes in modular structure
4. Add tests
5. Submit pull request

## 📄 License

[Your License Here]

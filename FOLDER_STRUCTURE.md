# Crypto Screener - Struktur Folder

## Struktur Direktori

```
crypto-screener/
│
├── .git/                           # Git repository
├── .kiro/                          # Kiro configuration
│   └── specs/                      # Specification files
│       ├── crypto-screener/        # Original spec
│       └── dashboard-enhancement-phase2/  # Phase 2 spec
│
├── archive/                        # File lama yang sudah tidak digunakan
│   ├── crypto_screener.py          # Monolithic file lama
│   ├── extract_modules.py          # Script ekstraksi
│   └── reorganize.py               # Script reorganisasi
│
├── demos/                          # Demo scripts untuk setiap modul
│   ├── demo_exchange_connector.py
│   ├── demo_fetch_all_data.py
│   ├── demo_ic_weight_calculator.py
│   ├── demo_market_data_fetcher.py
│   ├── demo_multi_factor_scorer.py
│   ├── demo_ranking_engine.py
│   └── demo_signal_generator.py
│
├── docs/                           # Dokumentasi
│   ├── ERROR_HANDLING_SUMMARY.md
│   ├── RESTRUCTURE_PLAN.md
│   └── TASK_*.md                   # Task summaries
│
├── output/                         # Output files
│   ├── dashboards/                 # Dashboard PNG files
│   │   ├── sample_dashboard.png
│   │   └── test_*.png              # Test output images
│   └── logs/                       # Log files
│       └── crypto_screener_*.log
│
├── src/                            # Source code (modular)
│   ├── __init__.py
│   ├── data/                       # Data fetching module
│   │   ├── __init__.py
│   │   └── fetcher.py              # MarketDataFetcher class
│   ├── exchange/                   # Exchange connection module
│   │   ├── __init__.py
│   │   └── connector.py            # ExchangeConnector class
│   ├── ranking/                    # Ranking module
│   │   ├── __init__.py
│   │   └── engine.py               # RankingEngine class
│   ├── scoring/                    # Scoring module
│   │   ├── __init__.py
│   │   ├── ic_weight.py            # ICWeightCalculator class
│   │   └── multi_factor.py         # MultiFactorScorer class
│   ├── signals/                    # Signal generation module
│   │   ├── __init__.py
│   │   └── generator.py            # SignalGenerator class
│   ├── utils/                      # Utility functions
│   │   └── __init__.py
│   └── visualization/              # Visualization module
│       ├── __init__.py
│       ├── dashboard.py            # DashboardBuilder class
│       └── panels.py               # Panel classes (7 panels)
│
├── tests/                          # Test suite
│   ├── __init__.py
│   ├── test_data/                  # Data fetching tests
│   │   ├── __init__.py
│   │   ├── test_calculate_atr.py
│   │   ├── test_calculate_ma50.py
│   │   ├── test_fetch_all_data.py
│   │   ├── test_fetch_all_data_integration.py
│   │   ├── test_market_data_fetcher.py
│   │   ├── test_oi_delta.py
│   │   └── test_sparkline.py
│   ├── test_exchange/              # Exchange connection tests
│   │   ├── __init__.py
│   │   └── test_exchange_connector.py
│   ├── test_integration/           # Integration tests
│   │   ├── __init__.py
│   │   └── test_phase2_pipeline.py
│   ├── test_ranking/               # Ranking tests
│   │   ├── __init__.py
│   │   └── test_ranking_engine.py
│   ├── test_signals/               # Signal generation tests
│   │   ├── __init__.py
│   │   └── test_signal_generator.py
│   ├── test_visualization/         # Visualization tests
│   │   ├── __init__.py
│   │   ├── test_atr_ma50_panels.py
│   │   ├── test_dashboard_builder.py
│   │   ├── test_dashboard_integration.py
│   │   ├── test_dashboard_visual.py
│   │   ├── test_funding_rate_panel.py
│   │   ├── test_funding_rate_panel_unit.py
│   │   ├── test_long_short_ratio_panel.py
│   │   ├── test_multi_factor_panel.py
│   │   ├── test_multi_factor_panel_unit.py
│   │   └── test_phase2b_panels.py
│   ├── test_error_handling.py
│   ├── test_main_function.py
│   └── test_main_requirements.py
│
├── .gitignore                      # Git ignore rules
├── main.py                         # Main entry point
├── requirements.txt                # Python dependencies
│
└── Documentation Files:
    ├── README.md                   # Main readme
    ├── QUICK_START.md              # Quick start guide
    ├── FOLDER_STRUCTURE.md         # This file
    ├── PHASE2_COMPLETION_SUMMARY.md  # Phase 2 summary
    ├── README_NEW_STRUCTURE.md     # New structure explanation
    ├── REORGANIZATION_SUMMARY.md   # Reorganization details
    └── FIX_APPLIED.md              # Applied fixes log
```

## Deskripsi Modul

### Source Code (`src/`)

#### 1. **data/** - Data Fetching
- `fetcher.py`: Mengambil data market dari exchange
  - Ticker data (price, 24h change)
  - Funding rate
  - Long/short ratio
  - 30-day momentum
  - ATR (Average True Range)
  - Distance to MA50
  - Sparkline data (24h price trend)
  - OI Delta (Open Interest change)

#### 2. **exchange/** - Exchange Connection
- `connector.py`: Mengelola koneksi ke exchange (Binance)
  - Initialize exchange
  - Load markets
  - Connection validation

#### 3. **signals/** - Signal Generation
- `generator.py`: Menghasilkan trading signals
  - Reversal signal (funding rate + long/short ratio)
  - Momentum signal (30-day price momentum)
  - Signal normalization

#### 4. **scoring/** - Multi-Factor Scoring
- `ic_weight.py`: Menghitung bobot Information Coefficient
- `multi_factor.py`: Menghitung composite score
  - Weighted signal combination
  - Tier classification (A/B)

#### 5. **ranking/** - Asset Ranking
- `engine.py`: Mengurutkan aset berdasarkan score
  - Sort by multi-factor score
  - Add rank column

#### 6. **visualization/** - Dashboard Visualization
- `dashboard.py`: Membangun dashboard lengkap (7 panels)
- `panels.py`: Individual panel classes
  - MultiFactorPanel
  - FundingRatePanel
  - LongShortRatioPanel
  - ATRPanel (Phase 2a)
  - MA50Panel (Phase 2a)
  - SparklinePanel (Phase 2b)
  - OIDeltaPanel (Phase 2b)

### Tests (`tests/`)

Struktur test mengikuti struktur source code:
- **test_data/**: Tests untuk data fetching
- **test_exchange/**: Tests untuk exchange connection
- **test_signals/**: Tests untuk signal generation
- **test_scoring/**: Tests untuk scoring (jika ada)
- **test_ranking/**: Tests untuk ranking
- **test_visualization/**: Tests untuk visualization
- **test_integration/**: Integration tests untuk full pipeline

### Output (`output/`)

- **dashboards/**: File PNG hasil dashboard
- **logs/**: File log aplikasi

### Archive (`archive/`)

File lama yang sudah tidak digunakan tetapi disimpan untuk referensi.

## Konvensi Penamaan

### File Python
- Module files: `lowercase_with_underscores.py`
- Class names: `PascalCase`
- Function names: `lowercase_with_underscores()`
- Constants: `UPPERCASE_WITH_UNDERSCORES`

### Test Files
- Test files: `test_<module_name>.py`
- Test classes: `Test<ClassName>`
- Test functions: `test_<functionality>()`

### Output Files
- Dashboard: `crypto_screener_dashboard_YYYYMMDD_HHMMSS.png`
- Logs: `crypto_screener_YYYYMMDD_HHMMSS.log`

## Import Paths

Karena menggunakan struktur modular, import menggunakan absolute path dari `src`:

```python
# Correct imports
from src.data.fetcher import MarketDataFetcher
from src.exchange.connector import ExchangeConnector
from src.signals.generator import SignalGenerator
from src.scoring.ic_weight import ICWeightCalculator
from src.scoring.multi_factor import MultiFactorScorer
from src.ranking.engine import RankingEngine
from src.visualization.dashboard import DashboardBuilder
from src.visualization.panels import (
    MultiFactorPanel, FundingRatePanel, LongShortRatioPanel,
    ATRPanel, MA50Panel, SparklinePanel, OIDeltaPanel
)
```

## Menjalankan Aplikasi

### Main Application
```bash
py main.py
```

### Running Tests
```bash
# All tests
py -m pytest tests/ -v

# Specific module
py -m pytest tests/test_data/ -v
py -m pytest tests/test_visualization/ -v

# Specific test file
py -m pytest tests/test_data/test_sparkline.py -v

# Integration tests
py -m pytest tests/test_integration/ -v
```

### Running Demos
```bash
py demos/demo_market_data_fetcher.py
py demos/demo_signal_generator.py
py demos/demo_ranking_engine.py
```

## Maintenance

### Menambah Panel Baru
1. Tambahkan class panel di `src/visualization/panels.py`
2. Update `DashboardBuilder` di `src/visualization/dashboard.py`
3. Tambahkan tests di `tests/test_visualization/`

### Menambah Metric Baru
1. Tambahkan method di `src/data/fetcher.py`
2. Update `fetch_all_data()` untuk include metric baru
3. Tambahkan tests di `tests/test_data/`

### Menambah Signal Baru
1. Tambahkan method di `src/signals/generator.py`
2. Update scoring logic jika perlu
3. Tambahkan tests di `tests/test_signals/`

## Clean Up

### Membersihkan Cache
```bash
# Remove Python cache
Remove-Item -Recurse -Force __pycache__
Remove-Item -Recurse -Force .pytest_cache

# Remove old logs (older than 7 days)
Get-ChildItem output/logs/*.log | Where-Object {$_.LastWriteTime -lt (Get-Date).AddDays(-7)} | Remove-Item
```

### Membersihkan Output Lama
```bash
# Remove old dashboards (older than 30 days)
Get-ChildItem output/dashboards/*.png | Where-Object {$_.LastWriteTime -lt (Get-Date).AddDays(-30)} | Remove-Item
```

## Version Control

File yang di-ignore oleh Git (`.gitignore`):
- `__pycache__/`
- `*.pyc`
- `.pytest_cache/`
- `output/logs/*.log`
- `output/dashboards/*.png` (kecuali sample)
- `.env`
- `venv/`

## Dependencies

Lihat `requirements.txt` untuk daftar lengkap dependencies:
- ccxt (exchange connection)
- pandas (data manipulation)
- numpy (numerical operations)
- matplotlib (visualization)
- pytest (testing)

---

**Last Updated**: 2026-05-12
**Structure Version**: 2.0 (Post Phase 2)

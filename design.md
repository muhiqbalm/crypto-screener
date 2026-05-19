# Crypto Screener — Design & Project Guide

Dokumen ini merangkum gambaran arsitektur, alur data, modul, dan panduan pengembangan untuk project **Crypto Screener**. Tujuannya adalah memberi peta yang lengkap tapi padat agar developer baru maupun lama bisa cepat menavigasi codebase, menambah fitur, dan menjaga konsistensi.

---

## 1. Ringkasan Proyek

**Crypto Screener** adalah sistem screening kuantitatif untuk pasar perpetual futures (Binance USDT-M Futures) yang menghasilkan composite score multi-faktor, risk-adjusted ranking, dan rekomendasi sizing posisi. Sistem dapat dijalankan dalam dua mode:

| Mode | Entry Point | Output Utama |
|------|-------------|--------------|
| Batch / CLI | `main.py` | Dashboard PNG 7 panel + log file |
| REST API | `main_api.py` | FastAPI server (Screener + Debug API) |

Stack teknologi inti: **Python 3.11+**, `ccxt` (exchange), `pandas`/`numpy` (analitik), `FastAPI`/`uvicorn` (API), `pydantic`/`pydantic-settings` (config & schema), `matplotlib`/`seaborn` (visualisasi), `cachetools` (cache), `python-json-logger` (structured logging), Docker (deploy).

Status: production-ready, struktur modular per Phase 2, dengan beberapa spec aktif untuk perbaikan dan ekstensi (lihat bagian 9).

---

## 2. Arsitektur Tingkat Tinggi

```
┌────────────────────────────────────────────────────────────────────────┐
│                            Entry Points                                 │
│   main.py (CLI batch + dashboard)        main_api.py (FastAPI server)  │
└──────────────────┬───────────────────────────────────┬──────────────────┘
                   │                                   │
                   ▼                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│                              src/api/                                   │
│  app.py (factory + lifespan)   routes.py        debug_routes.py        │
│  models.py                     auth.py          rate_limit_middleware  │
│  debug_models.py               debug_utils.py                          │
└──────────────────┬───────────────────────────────────┬──────────────────┘
                   │                                   │
                   ▼                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│                            src/services/                                │
│  data_processor.py  ── orkestrasi pipeline (async wrapper)             │
│  cache_manager.py   ── TTL in-memory cache (thread-safe)               │
│  response_builder.py── DataFrame → Pydantic response                   │
│  symbol_utils.py    ── normalisasi simbol multi-format                 │
│  debug_exchange_service.py ── raw exchange data + field mapping        │
│  models.py          ── ProcessedResult, CacheEntry                     │
└──────────────────┬───────────────────────────────────┬──────────────────┘
                   │                                   │
        ┌──────────┴──────────┐              ┌─────────┴─────────┐
        ▼                     ▼              ▼                   ▼
┌────────────────┐  ┌────────────────┐  ┌──────────────┐  ┌──────────────┐
│ src/exchange/  │  │  src/data/     │  │ src/signals/ │  │ src/ranking/ │
│  connector.py  │  │   fetcher.py   │  │  generator   │  │   engine     │
│ (ccxt wrapper) │  │ (market data)  │  │  ic_weights  │  │              │
│                │  │                │  │  scorer      │  │              │
└────────────────┘  └────────────────┘  └──────────────┘  └──────────────┘
                                                │
                                                ▼
                                        ┌────────────────────┐
                                        │ src/visualization/ │
                                        │   dashboard.py     │
                                        │   panels.py        │
                                        └────────────────────┘

Cross-cutting: src/config/ (settings.py, logging_config.py)
```

Prinsip arsitektur:
- **Separation of concerns**: setiap modul punya satu tanggung jawab. API tidak menyentuh exchange langsung; selalu via `services/`.
- **Reuse pipeline**: `main.py` (CLI) dan `data_processor.py` (API) memakai modul yang sama (`exchange`, `data`, `signals`, `ranking`).
- **Async di tepi, sync di inti**: API endpoint bersifat async; modul sintetis pipeline di-wrap dengan `asyncio.to_thread()` untuk non-blocking.
- **Per-symbol error isolation**: kegagalan satu simbol tidak menggagalkan seluruh batch.

---

## 3. Pipeline Data (End-to-End)

Pipeline yang sama digunakan oleh CLI dan API, dengan urutan:

```
┌─────────────┐  ┌──────────────┐  ┌────────────────┐  ┌─────────────────┐
│ 1. Connect  │─▶│ 2. Fetch raw │─▶│ 3. Generate    │─▶│ 4. Normalize    │
│  exchange   │  │  market data │  │  5 sinyal      │  │  (z-score)      │
└─────────────┘  └──────────────┘  └────────────────┘  └─────────────────┘
                                                                │
┌─────────────┐  ┌──────────────┐  ┌────────────────┐           │
│ 8. Rank     │◀─│ 7. Confidence│◀─│ 6. Risk-adj +  │◀──────────┘
│ assets      │  │   rate +     │  │  Position size │
└──────┬──────┘  │   tier (ABC) │  └────────────────┘
       │         └──────────────┘
       ▼
┌──────────────┐
│ 9. Output:   │
│  • Dashboard │
│  • API JSON  │
│  • Cache     │
└──────────────┘
```

### Tabel Field Per Simbol (DataFrame canonical)

| Kolom | Sumber | Catatan |
|-------|--------|---------|
| `symbol` | Settings | Format CCXT: `BTC/USDT:USDT` |
| `price`, `change_24h`, `volume_24h` | `fetch_ticker` | `last`, `percentage`, `quoteVolume` (fallback `baseVolume`) |
| `open_interest` | `fetch_open_interest` | `openInterestAmount` (fallback `openInterest`) |
| `funding_rate` | `fetch_funding_rate` | Dikonversi ke persentase (× 100) |
| `long_short_ratio` | Binance Futures Data API | Top trader account ratio, period 5m |
| `momentum_30d` | OHLCV 1d × 31 | `(close_now − close_30d) / close_30d × 100` |
| `atr_percent` | OHLCV 1d × 15 | ATR-14 SMA dari True Range, dinormalisasi ke harga |
| `distance_to_ma50` | OHLCV 1d × 50 | `(price − MA50) / MA50 × 100` |
| `sparkline_data`, `sparkline_trend` | OHLCV 1h × 24 (fallback 4h × 42) | Closing prices + arah |
| `oi_delta_percent`, `oi_interpretation` | Binance Futures Data API | Δ OI 24h + matriks interpretasi |
| `*_signal` (5 kolom) | `SignalGenerator` | Setelah `normalize_signal()` (z-score) |
| `multi_factor_score` | `MultiFactorScorer.calculate_score` | Σ weight × signal |
| `risk_adjusted_score` | `MultiFactorScorer.calculate_risk_adjusted_score` | `score / max(atr_percent, 1.0)` |
| `suggested_position_pct` | `MultiFactorScorer.calculate_position_sizing` | Inverse volatility, jumlah = 100% |
| `confidence_pct`, `confidence_tier` | `MultiFactorScorer.calculate_confidence_rate` | Hybrid (60% magnitude + 40% confluence) |
| `tier` | `MultiFactorScorer.classify_tiers` | A (top 33%), B (mid 34%), C (bottom 33%) |
| `rank` | `RankingEngine.rank_assets` | Diurutkan berdasarkan `risk_adjusted_score` |

---

## 4. Multi-Factor Scoring Engine

### 4.1 Lima Sinyal & Bobot IC

| Sinyal | Bobot IC | Logika Inti |
|--------|----------|-------------|
| Momentum 30d | **0.30** | 30-day price change; penalti 0.6× saat overbought (>30% di atas MA50) atau oversold (<-30%) |
| Funding Rate (kontrarian) | **0.25** | `signal = -funding_rate`; funding tinggi → market overleveraged long → bearish |
| OI Momentum | **0.20** | Matriks OI×Price: ↑↑=+1.0, ↑↓=−1.0, ↓↑=+0.5 (squeeze), ↓↓=−0.5 (liquidation) |
| Sentiment L/S (kontrarian) | **0.15** | `signal = -(long_short_ratio − 1.0)`; crowd long → bearish |
| Reversal 1d | **0.10** | `signal = -change_24h`; mean-reversion |

Bobot ini hard-coded di `src/signals/ic_weights.py` (catatan: implementasi production seharusnya menghitung IC dari rolling backtest historis).

### 4.2 Composite Score & Klasifikasi

```
multi_factor_score      = Σ wᵢ × normalized_signalᵢ          (z-score weighted)
risk_adjusted_score     = multi_factor_score / max(atr%, 1.0) (volatility penalty)
suggested_position_pct  = (1/atr%) / Σ(1/atr%) × 100         (inverse volatility)
confidence_pct          = 0.6 × magnitude_prob + 0.4 × confluence_prob
tier                    = A (≥ p67) | B (p33–p67) | C (< p33)
rank                    = sort by risk_adjusted_score, descending
```

`magnitude_prob` memakai CDF normal dari |z-score|; `confluence_prob` adalah fraksi sinyal individual yang sejalan arah dengan `risk_adjusted_score`.

---

## 5. API Layer

### 5.1 Endpoints Aktif

| Method | Path | Deskripsi |
|--------|------|-----------|
| GET | `/api/v1/health` | Health + cache status (always 200) |
| GET | `/api/v1/screener/summary?summary_only=false` | Full dataset (metadata + summary + assets) |
| GET | `/api/v1/screener/assets/{symbol}` | Detail satu aset (auto-normalisasi simbol) |
| GET | `/api/v1/debug/health` | Cek koneksi exchange |
| GET | `/api/v1/debug/exchange/ticker/{symbol}` | Raw ticker + field mapping |
| GET | `/api/v1/debug/exchange/open-interest/{symbol}` | Raw OI + field mapping |
| GET | `/api/v1/debug/exchange/funding-rate/{symbol}` | Raw funding rate |
| GET | `/api/v1/debug/exchange/long-short-ratio/{symbol}` | Raw L/S ratio |
| GET | `/api/v1/debug/exchange/all/{symbol}` | Aggregated 4 data type (concurrent) |

### 5.2 Lifecycle, Cache, & Authentication

- **Lifespan** (`src/api/app.py`):
  - Startup: `Settings()`, `setup_logging()`, init `CacheManager`, `DataProcessor`, `ResponseBuilder`, `ExchangeConnector`, `DebugExchangeService`.
  - Shutdown: signal handler (SIGTERM/SIGINT) → flag `shutting_down` → tolak request baru (503) → wait active requests s/d `shutdown_timeout`.
- **Cache** (`CacheManager`): TTL default 60s, single entry untuk seluruh hasil screener; thread-safe via `threading.Lock`.
- **Auth global**: `SCREENER_REQUIRE_API_KEY=true` mengaktifkan header `X-API-Key` untuk semua endpoint kecuali `/health`. Verifikasi pakai `secrets.compare_digest`.
- **Rate limiting** (debug only): sliding window (`max_requests`/`window_seconds`), key by `X-Forwarded-For` atau client host.
- **Sanitisasi**: response debug otomatis menyembunyikan field sensitif (`apikey`, `secret`, `token`, dll) jadi `[REDACTED]`.

### 5.3 Symbol Normalization

`src/services/symbol_utils.normalize_symbol()` menerima beberapa format dan mengembalikan format kanonik CCXT:

```
BTC, btc, BTCUSDT, btcusdt, BTC/USDT, BTC/USDT:USDT  →  BTC/USDT:USDT
```

Bila tidak ada di whitelist `SCREENER_SYMBOLS`, return `None` → endpoint balas 404 dengan `available_symbols`.

---

## 6. Konfigurasi & Environment

Semua env var memakai prefix **`SCREENER_`** dan dibaca `pydantic-settings` (`src/config/settings.py`). Lihat `.env.example` untuk daftar lengkap. Yang paling sering dipakai:

| Variable | Default | Fungsi |
|----------|---------|--------|
| `SCREENER_API_HOST`, `SCREENER_API_PORT` | `0.0.0.0`, `8000` | Bind server |
| `SCREENER_SYMBOLS` | 7 simbol default | Daftar yang dipantau |
| `SCREENER_CACHE_TTL` | `60` | Detik |
| `SCREENER_LOG_LEVEL` | `INFO` | DEBUG/INFO/WARNING/ERROR |
| `SCREENER_MOCK_MODE` | `false` | Bypass exchange, pakai data sintetis |
| `SCREENER_REQUIRE_API_KEY` + `SCREENER_API_KEY` | `false`, `""` | Auth global |
| `SCREENER_DEBUG_RATE_LIMIT_*` | `false`, 10/60s | Rate limiter debug |
| `SCREENER_CORS_ORIGINS` | `*` | CORS whitelist |
| `SCREENER_SHUTDOWN_TIMEOUT` | `30` | Detik graceful shutdown |

Logging selalu structured JSON (file rotating max 10×10MB di `output/logs/api_server.log` + stdout).

---

## 7. Struktur Folder

```
crypto-screener/
├── main.py                 # CLI batch entry
├── main_api.py             # FastAPI server entry
├── requirements.txt        # Pinned production deps
├── requirements-dev.txt    # Dev/test deps
├── pytest.ini              # asyncio_mode = auto
├── Dockerfile              # Multi-stage (builder + runtime, non-root user)
├── docker-compose.yml      # Service `api`, healthcheck, log rotate
├── docker-entrypoint.sh    # Fix volume permission, drop ke appuser
├── .env.example            # Template env vars
│
├── src/
│   ├── api/                # FastAPI app, routes, models, auth, middleware
│   ├── config/             # Settings (pydantic), structured JSON logging
│   ├── exchange/           # CCXT connector (binanceusdm only)
│   ├── data/               # MarketDataFetcher (ticker, OI, funding, OHLCV, ATR, MA50, sparkline)
│   ├── signals/            # SignalGenerator, ICWeightCalculator, MultiFactorScorer
│   ├── ranking/            # RankingEngine
│   ├── services/           # DataProcessor (async pipeline), CacheManager, ResponseBuilder, DebugExchangeService, symbol_utils
│   ├── visualization/      # DashboardBuilder + 7 panel classes
│   └── utils/              # (placeholder)
│
├── tests/                  # Pytest, mengikuti struktur src/
├── demos/                  # Script demo per modul (manual run)
├── docs/                   # Catatan task, error handling, restructure plans
├── archive/                # File legacy / monolitik (tidak dipakai)
├── output/
│   ├── dashboards/         # PNG dashboard (timestamped)
│   └── logs/               # Log JSON (timestamped + rotating)
├── scratch/                # Eksperimen sementara
└── .kiro/specs/            # Spec aktif & history (lihat §9)
```

---

## 8. Cara Menjalankan

### 8.1 Lokal (Windows / Linux)

```bash
# Setup
pip install -r requirements.txt
copy .env.example .env  # lalu edit sesuai kebutuhan (Windows: copy, Linux: cp)

# Mode CLI (sekali jalan, hasilkan dashboard PNG)
python main.py

# Mode API server
python main_api.py            # production
python main_api.py --reload   # dev (auto-reload)

# Tes endpoint
curl http://localhost:8000/api/v1/health
curl http://localhost:8000/api/v1/screener/summary
curl http://localhost:8000/api/v1/screener/assets/BTC
```

### 8.2 Docker

```bash
docker compose up -d --build
docker compose logs -f api
```

Container memakai user non-root `appuser` (uid 1000) dan healthcheck internal lewat `/api/v1/health`.

### 8.3 Testing

```bash
python -m pytest tests/ -v                 # semua
python -m pytest tests/test_signals/ -v    # per modul
python -m pytest tests/test_integration -v # integration
```

Pytest sudah otomatis async (`asyncio_mode = auto`).

---

## 9. Spec & Roadmap

Folder `.kiro/specs/` berisi spec terstruktur (requirements → design → tasks). Status saat ini:

| Spec | Status | Cakupan |
|------|--------|---------|
| `crypto-screener` | Selesai (baseline) | Pipeline awal, 2 sinyal |
| `dashboard-enhancement-phase2` | Selesai | Tambah 4 panel (ATR, MA50, sparkline, OI delta) → total 7 panel |
| `api-backend-transformation` | Selesai | FastAPI + cache + 5 sinyal + risk-adjusted + tier |
| `exchange-debug-api` | Selesai | Debug endpoints + sanitisasi response |
| `null-volume-open-interest-fix` | Selesai | Bugfix nilai null untuk volume/OI |
| `debug-api-symbol-format-fix` | Aktif | Konsistensi format simbol di debug API |

Setiap spec punya `requirements.md`, `design.md`, dan `tasks.md` sendiri. Patuhi alur ini untuk perubahan signifikan.

---

## 10. Panduan Pengembangan

### 10.1 Konvensi Kode

- **Naming**: modul `snake_case.py`, kelas `PascalCase`, fungsi `snake_case`, konstanta `UPPER_SNAKE`.
- **Import**: selalu absolute dari `src.*` (mis. `from src.signals.scorer import MultiFactorScorer`). Jangan pakai relative import lintas modul utama.
- **Type hints**: wajib pada signature publik (modul `services/`, `api/`, `config/`).
- **Docstring**: minimal 1-line summary + Args/Returns/Raises bila relevan. Bahasa Inggris untuk kode, bahasa Indonesia diizinkan untuk dokumen `.md`.
- **Logging**: pakai `logger = logging.getLogger(__name__)`, hindari `print()`. Tambahkan `extra={...}` untuk konteks structured.
- **NaN handling**: gunakan `np.nan` untuk numeric missing; `Optional[float]` di Pydantic; `_sanitize_value()` di `ResponseBuilder` untuk JSON-safe output.

### 10.2 Menambah Sinyal Baru

1. Tambah method `calculate_<nama>_signal(df)` di `src/signals/generator.py`.
2. Tambah bobot di `ICWeightCalculator.weights` (pastikan total tetap koheren — boleh re-normalisasi).
3. Update `MultiFactorScorer.calculate_score()` untuk menyertakan kolom baru.
4. Update `DataProcessor.process_all()` (fetch + normalize stage) dan mock generator.
5. Tambah field di `AssetDetail` (`src/api/models.py`) bila perlu diekspos.
6. Tulis test di `tests/test_signals/`.

### 10.3 Menambah Metric Pasar Baru

1. Method baru di `MarketDataFetcher` (`src/data/fetcher.py`).
2. Daftarkan di `_fetch_symbol_data()` di `DataProcessor`.
3. Tambah kolom default `np.nan` agar pipeline tidak break saat fetch gagal.
4. (Opsional) Tambah panel di `src/visualization/panels.py` + register di `DashboardBuilder.create_dashboard()`.

### 10.4 Menambah Endpoint API

1. Definisikan response model Pydantic di `src/api/models.py` (atau `debug_models.py`).
2. Tambah handler di `src/api/routes.py` atau `debug_routes.py`. Gunakan `Depends(verify_api_key)` untuk endpoint yang dilindungi.
3. Akses dependency via `request.app.state.*` (cache, processor, response_builder, debug_service).
4. Tangani exchange error → 503, not found → 404, internal → 500. Pakai helper `_is_exchange_error()` jika sudah cocok.
5. Tambah test di `tests/`.

### 10.5 Bug Fix Workflow

1. Buat folder spec di `.kiro/specs/<nama-fix>/` dengan `bugfix.md` (akar masalah & repro), `design.md` (pendekatan), `tasks.md` (langkah).
2. Implementasi minimal & terisolasi; jangan refactor di luar scope tanpa diskusi.
3. Tambah regression test sebelum menutup task.

### 10.6 Hal yang Perlu Diperhatikan

- **Exchange yang didukung hanya `binanceusdm`** (Binance USDT-M Futures). OKX di-block secara eksplisit di `ExchangeConnector` karena masalah kompatibilitas.
- **`main.py` punya copy logic main()** di `dashboard.py` (legacy). Sumber kebenaran tetap `main.py` di root; jangan modifikasi `dashboard.py.main` untuk pipeline.
- **Symbol di mock vs real**: `mock_mode=true` mem-bypass exchange; gunakan untuk dev/test tanpa internet.
- **Cache shared global**: satu `CacheManager` per app instance; tidak ada cache per-symbol. Kalau butuh granular caching, refactor `CacheManager` (saat ini single entry).
- **Output PNG resolusi tinggi** (300 dpi) → file ~1 MB. Bersihkan `output/dashboards/` periodik.

---

## 11. Quick Reference

### Health check & smoke test
```bash
curl http://localhost:8000/api/v1/health
curl http://localhost:8000/api/v1/debug/health
```

### Auth aktif
```bash
curl -H "X-API-Key: <secret>" http://localhost:8000/api/v1/screener/summary
```

### Mock mode untuk dev tanpa internet
```bash
SCREENER_MOCK_MODE=true python main_api.py --reload
```

### Re-run pipeline dengan symbol custom
```bash
SCREENER_SYMBOLS="BTC/USDT:USDT,ETH/USDT:USDT" python main.py
```

---

**Versi dokumen**: 1.0  
**Update terakhir**: 2026-05-19  
**Cakupan**: Refleksi state codebase saat dokumen dibuat (post Phase 2 + API transformation + debug API + bugfixes berjalan).

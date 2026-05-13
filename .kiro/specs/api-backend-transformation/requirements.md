# Requirements Document

## Introduction

Dokumen ini mendefinisikan requirements untuk transformasi aplikasi crypto screener Python dari script standalone yang menghasilkan visualisasi matplotlib menjadi REST API backend yang mengembalikan data JSON mentah. Transformasi ini memisahkan data processing dari visualisasi, memungkinkan frontend untuk mengkonsumsi API dan membuat visualisasi sendiri.

## Glossary

- **API_Server**: REST API backend yang menyediakan endpoint untuk data crypto screener
- **Data_Processor**: Komponen yang melakukan fetching dan kalkulasi metrik crypto
- **Exchange_Connector**: Modul yang menghubungkan ke Binance USDT-M Futures via CCXT
- **Cache_Manager**: Komponen yang mengelola caching data untuk menghindari rate limit
- **Response_Builder**: Komponen yang membangun struktur JSON response
- **Market_Data**: Data pasar crypto termasuk price, funding rate, long/short ratio
- **Signal_Data**: Data sinyal trading termasuk reversal signal dan momentum signal
- **Score_Data**: Data scoring termasuk multi-factor score, tier, dan ranking
- **Rate_Limit**: Batasan jumlah request yang diizinkan oleh exchange dalam periode waktu tertentu

## Requirements

### Requirement 1: REST API Framework Selection

**User Story:** Sebagai developer, saya ingin menggunakan framework REST API yang tepat untuk financial data, sehingga API dapat menangani request dengan cepat dan efisien.

#### Acceptance Criteria

1. THE API_Server SHALL menggunakan FastAPI sebagai framework REST API
2. THE API_Server SHALL mendukung async/await untuk operasi I/O non-blocking
3. THE API_Server SHALL menyediakan automatic OpenAPI documentation di endpoint /docs
4. THE API_Server SHALL menggunakan Pydantic untuk validasi request dan response schema

### Requirement 2: Data Processing Separation

**User Story:** Sebagai developer, saya ingin memisahkan data processing dari visualization logic, sehingga backend hanya fokus pada data fetching dan calculation.

#### Acceptance Criteria

1. THE Data_Processor SHALL menggunakan modul existing (exchange/connector.py, data/fetcher.py, signals/generator.py, signals/ic_weights.py, signals/scorer.py, ranking/engine.py)
2. THE Data_Processor SHALL menghapus dependency pada matplotlib dan seaborn
3. THE Data_Processor SHALL mengembalikan data dalam bentuk Python dictionary atau pandas DataFrame
4. THE Data_Processor SHALL mempertahankan semua kalkulasi metrik existing (reversal signal, momentum signal, multi-factor score, tier, ranking)

### Requirement 3: JSON Response Structure

**User Story:** Sebagai frontend developer, saya ingin menerima data dalam format JSON yang terstruktur dengan baik, sehingga mudah untuk dikonsumsi dan divisualisasikan.

#### Acceptance Criteria

1. THE Response_Builder SHALL mengembalikan JSON dengan struktur top-level: metadata, summary, dan assets
2. THE Response_Builder SHALL menyertakan metadata berisi timestamp, symbol_count, dan data_freshness
3. THE Response_Builder SHALL menyertakan summary berisi top_3_assets dan market_overview
4. THE Response_Builder SHALL menyertakan assets sebagai array of objects dengan semua metrik per symbol
5. FOR ALL numeric values, THE Response_Builder SHALL memformat dengan presisi 2-4 decimal places
6. WHEN data field bernilai NaN atau None, THE Response_Builder SHALL mengembalikan null dalam JSON

### Requirement 4: API Endpoint Design

**User Story:** Sebagai API consumer, saya ingin endpoint yang jelas dan RESTful, sehingga mudah untuk dipahami dan digunakan.

#### Acceptance Criteria

1. THE API_Server SHALL menyediakan endpoint GET /api/v1/screener/summary untuk data ringkasan semua assets
2. THE API_Server SHALL menyediakan endpoint GET /api/v1/screener/assets/{symbol} untuk data detail per asset
3. THE API_Server SHALL menyediakan endpoint GET /api/v1/health untuk health check
4. THE API_Server SHALL mengembalikan HTTP status 200 untuk request yang berhasil
5. THE API_Server SHALL mengembalikan HTTP status 404 untuk symbol yang tidak ditemukan
6. THE API_Server SHALL mengembalikan HTTP status 500 untuk internal server error
7. THE API_Server SHALL menyertakan error message dalam response body untuk semua error responses

### Requirement 5: Caching Strategy untuk Rate Limit Prevention

**User Story:** Sebagai system administrator, saya ingin API tidak terkena rate limit dari exchange, sehingga service tetap available dan reliable.

#### Acceptance Criteria

1. THE Cache_Manager SHALL menyimpan hasil fetching data dengan TTL (Time To Live) 60 detik
2. WHEN request diterima dan cache masih valid, THE API_Server SHALL mengembalikan data dari cache
3. WHEN request diterima dan cache expired, THE Data_Processor SHALL fetch data baru dari exchange
4. THE Cache_Manager SHALL menggunakan in-memory caching dengan library cachetools atau functools.lru_cache
5. THE API_Server SHALL menyertakan field cache_hit (boolean) dalam response metadata
6. THE API_Server SHALL menyertakan field data_age_seconds dalam response metadata

### Requirement 6: Performance Requirements

**User Story:** Sebagai API consumer, saya ingin API response yang cepat, sehingga user experience tetap smooth.

#### Acceptance Criteria

1. WHEN data tersedia di cache, THE API_Server SHALL mengembalikan response dalam waktu maksimal 100ms
2. WHEN data perlu di-fetch dari exchange, THE API_Server SHALL mengembalikan response dalam waktu maksimal 10 detik
3. THE API_Server SHALL menggunakan connection pooling untuk exchange connections
4. THE Data_Processor SHALL melakukan parallel fetching untuk multiple symbols menggunakan asyncio

### Requirement 7: Error Handling dan Resilience

**User Story:** Sebagai API consumer, saya ingin API tetap berfungsi meskipun ada error pada beberapa symbol, sehingga saya tetap mendapatkan data partial.

#### Acceptance Criteria

1. WHEN fetching data untuk satu symbol gagal, THE Data_Processor SHALL melanjutkan fetching untuk symbol lainnya
2. WHEN fetching data untuk satu symbol gagal, THE Response_Builder SHALL mengembalikan null values untuk metrik symbol tersebut
3. THE API_Server SHALL mencatat error details ke log file
4. WHEN exchange connection timeout, THE API_Server SHALL mengembalikan HTTP status 503 dengan message "Service temporarily unavailable"
5. THE API_Server SHALL menyertakan field errors (array) dalam response untuk mencatat symbol-specific errors

### Requirement 8: Configuration Management

**User Story:** Sebagai developer, saya ingin konfigurasi API dapat diubah tanpa mengubah code, sehingga deployment lebih fleksibel.

#### Acceptance Criteria

1. THE API_Server SHALL membaca konfigurasi dari environment variables atau config file
2. THE API_Server SHALL mendukung konfigurasi untuk: API_HOST, API_PORT, CACHE_TTL, LOG_LEVEL
3. THE API_Server SHALL mendukung konfigurasi untuk SYMBOLS list (default: BTC, ETH, SOL, AAVE, LINK, AVAX, DOGE)
4. THE API_Server SHALL menggunakan default values jika environment variables tidak tersedia

### Requirement 9: Logging dan Monitoring

**User Story:** Sebagai system administrator, saya ingin log yang informatif untuk troubleshooting, sehingga mudah untuk debug issues.

#### Acceptance Criteria

1. THE API_Server SHALL mencatat setiap incoming request dengan timestamp, endpoint, dan response time
2. THE API_Server SHALL mencatat cache hit/miss events
3. THE API_Server SHALL mencatat exchange API errors dengan symbol dan error details
4. THE API_Server SHALL menggunakan structured logging format (JSON) untuk machine readability
5. THE API_Server SHALL menyimpan log ke file dengan rotation policy (max 10 files, 10MB per file)

### Requirement 10: Backward Compatibility dengan Existing Modules

**User Story:** Sebagai developer, saya ingin menggunakan kembali modul existing tanpa refactoring besar, sehingga development lebih cepat.

#### Acceptance Criteria

1. THE API_Server SHALL menggunakan ExchangeConnector dari src/exchange/connector.py tanpa modifikasi
2. THE API_Server SHALL menggunakan MarketDataFetcher dari src/data/fetcher.py tanpa modifikasi
3. THE API_Server SHALL menggunakan SignalGenerator dari src/signals/generator.py tanpa modifikasi
4. THE API_Server SHALL menggunakan ICWeightCalculator dari src/signals/ic_weights.py tanpa modifikasi
5. THE API_Server SHALL menggunakan MultiFactorScorer dari src/signals/scorer.py tanpa modifikasi
6. THE API_Server SHALL menggunakan RankingEngine dari src/ranking/engine.py tanpa modifikasi

### Requirement 11: Development dan Testing Support

**User Story:** Sebagai developer, saya ingin mudah untuk menjalankan dan test API di local environment, sehingga development cycle lebih cepat.

#### Acceptance Criteria

1. THE API_Server SHALL menyediakan command untuk menjalankan development server: `uvicorn main:app --reload`
2. THE API_Server SHALL menyediakan example requests dalam OpenAPI documentation
3. THE API_Server SHALL mendukung CORS untuk local frontend development
4. THE API_Server SHALL menyediakan mock mode untuk testing tanpa hit exchange API

### Requirement 12: Response Time Optimization

**User Story:** Sebagai API consumer, saya ingin mendapatkan data summary dengan cepat tanpa menunggu semua detail, sehingga initial page load lebih cepat.

#### Acceptance Criteria

1. THE API_Server SHALL mengembalikan summary data (top 3 assets, market overview) dalam response /api/v1/screener/summary
2. THE API_Server SHALL mengembalikan full asset details dalam response /api/v1/screener/summary
3. WHEN frontend hanya membutuhkan summary, THE API_Server SHALL mendukung query parameter ?summary_only=true untuk mengurangi response size
4. WHEN summary_only=true, THE Response_Builder SHALL menghilangkan field assets dari response

### Requirement 13: Data Freshness Indicator

**User Story:** Sebagai API consumer, saya ingin tahu seberapa fresh data yang saya terima, sehingga dapat menampilkan indicator ke user.

#### Acceptance Criteria

1. THE Response_Builder SHALL menyertakan field fetched_at (ISO 8601 timestamp) dalam metadata
2. THE Response_Builder SHALL menyertakan field data_age_seconds dalam metadata
3. WHEN data_age_seconds > 300, THE Response_Builder SHALL menyertakan field stale_data_warning dengan value true
4. THE Response_Builder SHALL menyertakan field next_refresh_at (ISO 8601 timestamp) dalam metadata

### Requirement 14: Symbol Validation

**User Story:** Sebagai API consumer, saya ingin mendapatkan error message yang jelas ketika request symbol yang tidak valid, sehingga dapat memperbaiki request.

#### Acceptance Criteria

1. WHEN request ke /api/v1/screener/assets/{symbol} dengan symbol yang tidak ada dalam SYMBOLS list, THE API_Server SHALL mengembalikan HTTP status 404
2. THE API_Server SHALL mengembalikan error message: "Symbol {symbol} not found. Available symbols: [list]"
3. THE API_Server SHALL menyertakan field available_symbols dalam error response
4. THE API_Server SHALL mendukung symbol format dengan atau tanpa slash (BTC/USDT:USDT atau BTCUSDT)

### Requirement 15: Graceful Shutdown

**User Story:** Sebagai system administrator, saya ingin API dapat shutdown dengan graceful tanpa memutus active requests, sehingga tidak ada data loss.

#### Acceptance Criteria

1. WHEN API_Server menerima SIGTERM signal, THE API_Server SHALL menyelesaikan active requests sebelum shutdown
2. THE API_Server SHALL menolak new requests dengan HTTP status 503 setelah menerima shutdown signal
3. THE API_Server SHALL menunggu maksimal 30 detik untuk active requests selesai
4. THE API_Server SHALL mencatat shutdown event ke log file

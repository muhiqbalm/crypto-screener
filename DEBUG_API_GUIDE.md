# Panduan Menjalankan Debug API Exchange

## Cara Menjalankan API Server

### 1. Persiapan Environment

Pastikan file `.env` sudah dikonfigurasi dengan benar:

```bash
# Copy dari .env.example
copy .env.example .env
```

Edit file `.env` dan pastikan:
```env
# Pastikan mock mode DISABLED untuk koneksi real ke exchange
SCREENER_MOCK_MODE=false

# Konfigurasi server
SCREENER_API_HOST=0.0.0.0
SCREENER_API_PORT=8000

# Log level untuk debugging
SCREENER_LOG_LEVEL=INFO
```

### 2. Menjalankan Server

```bash
# Dari root directory project
python -m uvicorn src.api.app:create_app --factory --host 0.0.0.0 --port 8000 --reload
```

Atau menggunakan script startup (jika ada):
```bash
python run_api.py
```

### 3. Verifikasi Server Berjalan

Buka browser dan akses:
- **API Docs (Swagger)**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/api/v1/debug/health

## Format Symbol yang Benar

### ❌ Format SALAH
```
BTCUSDT          # Format spot trading
BTC/USDT         # Format spot trading
ETHUSDT          # Format spot trading
```

### ✅ Format BENAR (Binance Futures)
```
BTC/USDT:USDT    # Bitcoin futures
ETH/USDT:USDT    # Ethereum futures
SOL/USDT:USDT    # Solana futures
AAVE/USDT:USDT   # Aave futures
LINK/USDT:USDT   # Chainlink futures
AVAX/USDT:USDT   # Avalanche futures
DOGE/USDT:USDT   # Dogecoin futures
```

**Catatan**: Format `SYMBOL/USDT:USDT` adalah format CCXT untuk Binance USDT-M Futures.

## Endpoint Debug API yang Tersedia

### 1. Health Check
**Endpoint**: `GET /api/v1/debug/health`

**Contoh Request**:
```bash
curl http://localhost:8000/api/v1/debug/health
```

**Response**:
```json
{
  "success": true,
  "data": {
    "status": "connected",
    "exchange": "binanceusdm",
    "base_url": "https://fapi.binance.com",
    "server_timestamp": 1705315800000,
    "available_endpoints": [...]
  }
}
```

### 2. Raw Ticker Data
**Endpoint**: `GET /api/v1/debug/exchange/ticker/{symbol:path}`

**Contoh Request**:
```bash
# Langsung gunakan format symbol tanpa encoding
curl "http://localhost:8000/api/v1/debug/exchange/ticker/BTC/USDT:USDT"

# Atau dari browser/Postman
http://localhost:8000/api/v1/debug/exchange/ticker/BTC/USDT:USDT
```

**Response**:
```json
{
  "success": true,
  "data": {
    "symbol": "BTC/USDT:USDT",
    "last": 45000.50,
    "percentage": 2.5,
    "quoteVolume": 1500000000.0
  },
  "metadata": {
    "request_timestamp": "2026-05-13T10:30:00.000Z",
    "response_timestamp": "2026-05-13T10:30:00.250Z",
    "response_time_ms": 250.45
  },
  "fieldMapping": {...}
}
```

### 3. Raw Open Interest Data
**Endpoint**: `GET /api/v1/debug/exchange/open-interest/{symbol:path}`

**Contoh Request**:
```bash
curl "http://localhost:8000/api/v1/debug/exchange/open-interest/BTC/USDT:USDT"
```

**Response**:
```json
{
  "success": true,
  "data": {
    "symbol": "BTC/USDT:USDT",
    "openInterestAmount": 1000000.0
  },
  "metadata": {...}
}
```

### 4. Raw Funding Rate Data
**Endpoint**: `GET /api/v1/debug/exchange/funding-rate/{symbol:path}`

**Contoh Request**:
```bash
curl "http://localhost:8000/api/v1/debug/exchange/funding-rate/BTC/USDT:USDT"
```

**Response**:
```json
{
  "success": true,
  "data": {
    "symbol": "BTC/USDT:USDT",
    "fundingRate": 0.0001
  },
  "metadata": {...}
}
```

### 5. Raw Long/Short Ratio Data
**Endpoint**: `GET /api/v1/debug/exchange/long-short-ratio/{symbol:path}`

**Contoh Request**:
```bash
curl "http://localhost:8000/api/v1/debug/exchange/long-short-ratio/BTC/USDT:USDT"
```

**Response**:
```json
{
  "success": true,
  "data": {
    "symbol": "BTCUSDT",
    "longShortRatio": 1.5
  },
  "metadata": {...}
}
```

### 6. Aggregated Data (Semua Data Sekaligus)
**Endpoint**: `GET /api/v1/debug/exchange/all/{symbol:path}`

**Contoh Request**:
```bash
curl "http://localhost:8000/api/v1/debug/exchange/all/BTC/USDT:USDT"
```

**Response**:
```json
{
  "success": true,
  "data": {
    "ticker": {
      "success": true,
      "data": {...}
    },
    "openInterest": {
      "success": true,
      "data": {...}
    },
    "fundingRate": {
      "success": true,
      "data": {...}
    },
    "longShortRatio": {
      "success": true,
      "data": {...}
    }
  },
  "metadata": {
    "total_response_time_ms": 500.0,
    "individual_timings": {
      "ticker_ms": 250.0,
      "open_interest_ms": 300.0,
      "funding_rate_ms": 280.0,
      "long_short_ratio_ms": 320.0
    }
  }
}
```

## Symbol yang Dapat Digunakan untuk Testing

Berikut adalah daftar symbol yang tersedia di Binance Futures (format CCXT):

### Major Cryptocurrencies
- `BTC/USDT:USDT` - Bitcoin
- `ETH/USDT:USDT` - Ethereum
- `BNB/USDT:USDT` - Binance Coin

### Popular Altcoins
- `SOL/USDT:USDT` - Solana
- `ADA/USDT:USDT` - Cardano
- `XRP/USDT:USDT` - Ripple
- `DOT/USDT:USDT` - Polkadot
- `DOGE/USDT:USDT` - Dogecoin
- `AVAX/USDT:USDT` - Avalanche
- `MATIC/USDT:USDT` - Polygon
- `LINK/USDT:USDT` - Chainlink
- `UNI/USDT:USDT` - Uniswap
- `ATOM/USDT:USDT` - Cosmos
- `LTC/USDT:USDT` - Litecoin

### DeFi Tokens
- `AAVE/USDT:USDT` - Aave
- `SUSHI/USDT:USDT` - SushiSwap
- `COMP/USDT:USDT` - Compound
- `MKR/USDT:USDT` - Maker

### Layer 2 & Scaling
- `ARB/USDT:USDT` - Arbitrum
- `OP/USDT:USDT` - Optimism

## Troubleshooting

### Error: "Internal server error: An unexpected error occurred"

**Penyebab**:
1. Format symbol salah (gunakan `BTC/USDT:USDT` bukan `BTCUSDT`)
2. Mock mode aktif dalam testing
3. Koneksi ke exchange gagal

**Solusi**:
1. Pastikan menggunakan format symbol yang benar: `SYMBOL/USDT:USDT`
2. Cek file `.env` dan pastikan `SCREENER_MOCK_MODE=false`
3. Restart server setelah mengubah konfigurasi
4. Cek log di `output/logs/api_server.log` untuk detail error

### Error: "Service unavailable"

**Penyebab**: Tidak bisa terhubung ke Binance API

**Solusi**:
1. Cek koneksi internet
2. Pastikan Binance API tidak diblokir oleh firewall/ISP
3. Coba akses https://fapi.binance.com/fapi/v1/ping dari browser

### Error: "Invalid symbol"

**Penyebab**: Format symbol tidak valid

**Solusi**:
- Gunakan format `SYMBOL/USDT:USDT` (contoh: `BTC/USDT:USDT`)
- Symbol harus alphanumeric, maksimal 20 karakter
- Whitespace akan otomatis di-trim dan diubah ke uppercase

## Testing dengan Swagger UI

1. Buka http://localhost:8000/docs
2. Pilih endpoint yang ingin ditest (misalnya `/api/v1/debug/exchange/ticker/{symbol}`)
3. Klik "Try it out"
4. Masukkan symbol: `BTC/USDT:USDT`
5. Klik "Execute"
6. Lihat response di bagian bawah

## Testing dengan cURL

```bash
# Health check
curl http://localhost:8000/api/v1/debug/health

# Ticker data
curl "http://localhost:8000/api/v1/debug/exchange/ticker/BTC/USDT:USDT"

# Open interest
curl "http://localhost:8000/api/v1/debug/exchange/open-interest/ETH/USDT:USDT"

# Funding rate
curl "http://localhost:8000/api/v1/debug/exchange/funding-rate/SOL/USDT:USDT"

# Long/short ratio
curl "http://localhost:8000/api/v1/debug/exchange/long-short-ratio/DOGE/USDT:USDT"

# All data
curl "http://localhost:8000/api/v1/debug/exchange/all/BTC/USDT:USDT"
```

## Testing dengan Python

```python
import requests

# Base URL
base_url = "http://localhost:8000/api/v1/debug"

# Health check
response = requests.get(f"{base_url}/health")
print(response.json())

# Ticker data
symbol = "BTC/USDT:USDT"
response = requests.get(f"{base_url}/exchange/ticker/{symbol}")
print(response.json())

# Aggregated data
response = requests.get(f"{base_url}/exchange/all/{symbol}")
data = response.json()
print(f"Total response time: {data['metadata']['total_response_time_ms']}ms")
```

## Catatan Penting

1. **Format Symbol**: Selalu gunakan format `SYMBOL/USDT:USDT` untuk Binance Futures
2. **Path Parameter**: Endpoint sudah dikonfigurasi untuk menerima `/` dan `:` dalam symbol, tidak perlu URL encoding
3. **Mock Mode**: Pastikan `SCREENER_MOCK_MODE=false` untuk koneksi real ke exchange
4. **Rate Limiting**: API Binance memiliki rate limit, jangan spam request terlalu cepat
5. **Log Files**: Cek `output/logs/api_server.log` untuk debugging detail error

## Contoh Response Error

### Invalid Symbol
```json
{
  "success": false,
  "error": {
    "message": "Invalid symbol: must be alphanumeric and max 20 characters",
    "code": "INVALID_INPUT"
  },
  "metadata": {
    "http_status": 400
  }
}
```

### Exchange Error
```json
{
  "success": false,
  "error": {
    "message": "Exchange error: Invalid symbol",
    "code": "EXCHANGE_ERROR"
  },
  "metadata": {
    "http_status": 400
  }
}
```

### Network Error
```json
{
  "success": false,
  "error": {
    "message": "Service unavailable: Cannot connect to exchange",
    "code": "SERVICE_UNAVAILABLE",
    "details": "Connection refused"
  },
  "metadata": {
    "http_status": 503
  }
}
```

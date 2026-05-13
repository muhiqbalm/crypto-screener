# Quick Test - Debug API Exchange

## 🚀 Cara Cepat Menjalankan

### 1. Setup Environment
```bash
# Pastikan .env sudah ada dan mock mode disabled
echo SCREENER_MOCK_MODE=false > .env
```

### 2. Jalankan Server
```bash
python -m uvicorn src.api.app:create_app --factory --host 0.0.0.0 --port 8000 --reload
```

### 3. Test Endpoints

## ✅ Test Commands (Copy & Paste)

### Health Check
```bash
curl http://localhost:8000/api/v1/debug/health
```

### Bitcoin (BTC) - All Endpoints
```bash
# Ticker
curl "http://localhost:8000/api/v1/debug/exchange/ticker/BTC/USDT:USDT"

# Open Interest
curl "http://localhost:8000/api/v1/debug/exchange/open-interest/BTC/USDT:USDT"

# Funding Rate
curl "http://localhost:8000/api/v1/debug/exchange/funding-rate/BTC/USDT:USDT"

# Long/Short Ratio
curl "http://localhost:8000/api/v1/debug/exchange/long-short-ratio/BTC/USDT:USDT"

# All Data (Aggregated)
curl "http://localhost:8000/api/v1/debug/exchange/all/BTC/USDT:USDT"
```

### Ethereum (ETH)
```bash
curl "http://localhost:8000/api/v1/debug/exchange/ticker/ETH/USDT:USDT"
curl "http://localhost:8000/api/v1/debug/exchange/open-interest/ETH/USDT:USDT"
curl "http://localhost:8000/api/v1/debug/exchange/all/ETH/USDT:USDT"
```

### Solana (SOL)
```bash
curl "http://localhost:8000/api/v1/debug/exchange/ticker/SOL/USDT:USDT"
curl "http://localhost:8000/api/v1/debug/exchange/open-interest/SOL/USDT:USDT"
curl "http://localhost:8000/api/v1/debug/exchange/all/SOL/USDT:USDT"
```

### Dogecoin (DOGE)
```bash
curl "http://localhost:8000/api/v1/debug/exchange/ticker/DOGE/USDT:USDT"
curl "http://localhost:8000/api/v1/debug/exchange/open-interest/DOGE/USDT:USDT"
curl "http://localhost:8000/api/v1/debug/exchange/all/DOGE/USDT:USDT"
```

## 🌐 Browser Testing

Buka di browser:
- **Swagger UI**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/api/v1/debug/health
- **BTC Ticker**: http://localhost:8000/api/v1/debug/exchange/ticker/BTC/USDT:USDT
- **BTC All Data**: http://localhost:8000/api/v1/debug/exchange/all/BTC/USDT:USDT

## 📋 Symbol List untuk Testing

| Symbol | Endpoint Format |
|--------|----------------|
| Bitcoin | `BTC/USDT:USDT` |
| Ethereum | `ETH/USDT:USDT` |
| Solana | `SOL/USDT:USDT` |
| Dogecoin | `DOGE/USDT:USDT` |
| Cardano | `ADA/USDT:USDT` |
| Ripple | `XRP/USDT:USDT` |
| Polkadot | `DOT/USDT:USDT` |
| Avalanche | `AVAX/USDT:USDT` |
| Polygon | `MATIC/USDT:USDT` |
| Chainlink | `LINK/USDT:USDT` |
| Aave | `AAVE/USDT:USDT` |
| Uniswap | `UNI/USDT:USDT` |

## 🐍 Python Testing Script

```python
import requests
import json

base_url = "http://localhost:8000/api/v1/debug"

# Test health
print("=== Health Check ===")
response = requests.get(f"{base_url}/health")
print(json.dumps(response.json(), indent=2))

# Test BTC ticker
print("\n=== BTC Ticker ===")
response = requests.get(f"{base_url}/exchange/ticker/BTC/USDT:USDT")
data = response.json()
if data['success']:
    print(f"Price: {data['data'].get('last')}")
    print(f"24h Change: {data['data'].get('percentage')}%")
    print(f"Response Time: {data['metadata']['response_time_ms']}ms")
else:
    print(f"Error: {data['error']}")

# Test BTC all data
print("\n=== BTC All Data ===")
response = requests.get(f"{base_url}/exchange/all/BTC/USDT:USDT")
data = response.json()
if data['success']:
    print(f"Total Response Time: {data['metadata']['total_response_time_ms']}ms")
    print(f"Individual Timings:")
    for key, value in data['metadata']['individual_timings'].items():
        print(f"  - {key}: {value}ms")
else:
    print(f"Error: {data['error']}")
```

## ❌ Common Errors & Solutions

### Error: "Not Found"
**Penyebab**: Format symbol salah atau server belum restart setelah update code

**Solusi**:
1. Restart server
2. Gunakan format: `BTC/USDT:USDT` (bukan `BTCUSDT`)
3. Pastikan endpoint path benar

### Error: "Internal server error"
**Penyebab**: Mock mode aktif atau koneksi exchange gagal

**Solusi**:
1. Cek `.env`: `SCREENER_MOCK_MODE=false`
2. Restart server
3. Cek log: `output/logs/api_server.log`

### Error: "Service unavailable"
**Penyebab**: Tidak bisa connect ke Binance API

**Solusi**:
1. Cek koneksi internet
2. Test: `curl https://fapi.binance.com/fapi/v1/ping`
3. Cek firewall/proxy

## 📊 Expected Response Format

### Success Response
```json
{
  "success": true,
  "data": {
    "symbol": "BTC/USDT:USDT",
    "last": 45000.50,
    "percentage": 2.5
  },
  "metadata": {
    "request_timestamp": "2026-05-13T10:30:00.000Z",
    "response_timestamp": "2026-05-13T10:30:00.250Z",
    "response_time_ms": 250.45,
    "http_status": 200,
    "exchange": "binanceusdm"
  },
  "fieldMapping": {...}
}
```

### Error Response
```json
{
  "success": false,
  "data": null,
  "error": {
    "message": "Error description",
    "code": "ERROR_CODE"
  },
  "metadata": {
    "http_status": 400
  }
}
```

## 🔍 Debugging

### Check Server Logs
```bash
# Windows
type output\logs\api_server.log | findstr "ERROR"

# Linux/Mac
tail -f output/logs/api_server.log | grep ERROR
```

### Check if Server is Running
```bash
curl http://localhost:8000/api/v1/debug/health
```

### Test Binance API Directly
```bash
curl https://fapi.binance.com/fapi/v1/ping
```

## 💡 Tips

1. **Gunakan Swagger UI** untuk testing interaktif: http://localhost:8000/docs
2. **Format symbol harus tepat**: `SYMBOL/USDT:USDT` (dengan slash dan colon)
3. **Restart server** setelah mengubah code atau `.env`
4. **Cek log** jika ada error: `output/logs/api_server.log`
5. **Rate limit**: Jangan spam request terlalu cepat ke Binance API

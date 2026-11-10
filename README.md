# crypto-screener

BMTM backend: FastAPI service with the multi-factor crypto futures screener,
market intel, TradingView webhook trading, and the Strategy Lab API + worker.

## Quick start

```bash
# 1. Install dependencies
pip install -r requirements-dev.txt   # or requirements.txt for production only

# 2. Configure environment
cp .env.example .env
# edit .env

# 3. Run the API server
python main_api.py            # add --reload for development

# 4. Run the tests
pytest
```

## Deployment

Production runs natively under PM2 on the VPS (`bmtm-api`, plus
`bmtm-lab-worker` from `ecosystem.lab.config.js`). `./deploy.sh` does
`git pull`, installs `requirements.txt` into `.venv`, restarts `bmtm-api` and
checks `/api/v1/health`. CI/CD (`.github/workflows/deploy.yml`) calls it on
every push to `main`.

A `Dockerfile` / `docker-compose.yml` are also kept for container builds.

## Project layout

| Path | Purpose |
|------|---------|
| `main_api.py` | API entry point (uvicorn, `src.api.app:create_app`). |
| `main_lab_worker.py` | Strategy Lab worker entry point. |
| `src/` | Application source. `src/trading/` is the live webhook trading path. |
| `tests/` | Pytest suite. |
| `docs/` | Design doc, debug API guide, quick test. |
| `tradingview/` | Pine Script source of the live strategy. |
| `output/logs/` | Runtime logs (not tracked). |

## Documentation

- [Design](docs/design.md)
- [Debug API guide](docs/DEBUG_API_GUIDE.md)
- [Quick test](docs/QUICK_TEST.md)

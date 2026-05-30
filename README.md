# crypto-screener

Multi-factor crypto futures screener with a FastAPI service, scoring/ranking
engine, and visualization dashboards.

## Quick start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# edit .env

# 3. Run the screener once
python main.py

# 4. Run the API server
python main_api.py
```

## Docker

```bash
docker compose up -d --build
```

The deployment helper `./deploy.sh` wraps `git pull` + `docker compose up`
on the VPS. CI/CD (`.github/workflows/deploy.yml`) calls it on every push
to `main`.

## Project layout

| Path | Purpose |
|------|---------|
| `main.py` / `main_api.py` | Entry points (CLI and API). |
| `src/` | Application source. |
| `tests/` | Pytest suite. |
| `docs/` | Active documentation (quick start, debug guide, design, etc.). |
| `docs/archive/` | Historical phase summaries kept for reference. |
| `output/` | Runtime artifacts: logs, dashboards, test artifacts. |
| `archive/` | One-off / legacy scripts no longer in the build. |
| `scratch/` | Experimental scripts, not part of the product. |
| `demos/` | Self-contained demo scripts. |

## Documentation

- [Quick start](docs/QUICK_START.md)
- [Quick test](docs/QUICK_TEST.md)
- [Folder structure](docs/FOLDER_STRUCTURE.md)
- [Design](docs/design.md)
- [Debug API guide](docs/DEBUG_API_GUIDE.md)
- [API documentation summary](docs/API_DOCUMENTATION_SUMMARY.md)

## check

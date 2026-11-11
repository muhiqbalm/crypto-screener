"""Shared setup for the new-template research (2026-11-11). Runs on the VPS under /tmp/templates.
Env: LAB_ENGINE_PATH (engine), TPL_REPO (backend checkout). Data = a /tmp copy of the Lab cache."""
import os, sys
EXP = "/tmp/templates/exp"
os.environ.setdefault("LAB_ENGINE_PATH", "/tmp/templates/engine")
os.environ["LAB_DATA_DIR"] = "/tmp/templates/data"
os.environ["LAB_DB_PATH"] = f"{EXP}/lab.db"
os.environ["LAB_ARTIFACTS_DIR"] = f"{EXP}/artifacts"
os.environ["LAB_DATA_OFFLINE"] = "1"
os.environ["LAB_TELEGRAM_ENABLED"] = "0"
sys.dont_write_bytecode = True
REPO = os.environ.get("TPL_REPO", "/tmp/templates/be")
sys.path.insert(0, REPO)
os.makedirs(f"{EXP}/out", exist_ok=True)

from src.lab import data_cache as dc  # noqa: E402
from src.lab import engine_adapter as ea  # noqa: E402

START, END = "2020-01-01", "2026-11-09"
COSTS = {"commission_pct": 0.05, "slippage_pct": 0.05, "funding": True}

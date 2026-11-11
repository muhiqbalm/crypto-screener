"""Strategy Lab settings.

Stdlib only: this module is imported both by the API process (screener venv)
and by the engine child process (bmtm-v2 venv, which has no pydantic).

Values come from the environment first, then from the screener's ``.env``
file (``LAB_*`` keys only), then the defaults below.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


# Non-LAB keys the lab may read from .env (Telegram creds are used only by the
# worker's alert sender and are never logged or written to lab.db).
_EXTRA_KEYS = {"TRADING_LOCAL_DB_PATH", "TRADING_TELEGRAM_BOT_TOKEN", "TRADING_TELEGRAM_DEFAULT_CHAT_ID"}


def _read_dotenv(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            if k.startswith("export "):
                k = k[7:].strip()
            if k.startswith("LAB_") or k in _EXTRA_KEYS:
                out[k] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return out


def _get(env: dict, key: str, default: str) -> str:
    return os.environ.get(key, env.get(key, default))


@dataclass(frozen=True)
class LabSettings:
    db_path: str
    engine_path: str
    engine_python: str
    data_dir: str
    artifacts_dir: str
    admin_emails: tuple[str, ...] = field(default_factory=tuple)
    max_concurrent_jobs: int = 1
    job_timeout_s: int = 3 * 3600
    job_mem_mb: int = 6144
    job_nice: int = 15
    optuna_max_trials: int = 60
    heartbeat_s: int = 10
    stale_after_s: int = 120
    poll_s: float = 2.0
    trading_db_path: str = ""
    bot_import_interval_s: int = 300
    watch_delay_s: int = 30
    watch_max_active: int = 100            # hard cap on active watches (all timeframes)
    klines_cache_s: int = 30
    fast_lane: bool = True                 # one extra slot for watch_eval/universe_refresh jobs
    strength_refresh: bool = True          # universe_refresh job after every 4H close
    telegram_enabled: bool = True
    telegram_chat_id: str = field(default="", repr=False)
    telegram_bot_token: str = field(default="", repr=False)
    telegram_min_interval_s: int = 300
    telegram_max_per_hour: int = 12
    telegram_max_age_s: int = 6 * 3600

    @property
    def admin_set(self) -> set[str]:
        return {a.lower() for a in self.admin_emails}


@lru_cache(maxsize=1)
def get_lab_settings() -> LabSettings:
    env = _read_dotenv(REPO_ROOT / ".env")
    engine_path = _get(env, "LAB_ENGINE_PATH", "/root/bmtm-v2")
    default_py = str(Path(engine_path) / "venv" / "bin" / "python")
    data_root = REPO_ROOT / "data" / "lab"
    return LabSettings(
        db_path=_get(env, "LAB_DB_PATH", str(data_root / "lab.db")),
        engine_path=engine_path,
        engine_python=_get(env, "LAB_ENGINE_PYTHON", default_py),
        data_dir=_get(env, "LAB_DATA_DIR", str(data_root / "cache" / "perp")),
        artifacts_dir=_get(env, "LAB_ARTIFACTS_DIR", str(data_root / "artifacts")),
        admin_emails=tuple(
            e.strip() for e in _get(env, "LAB_ADMIN_EMAILS", "").split(",") if e.strip()
        ),
        max_concurrent_jobs=int(_get(env, "LAB_MAX_CONCURRENT_JOBS", "1")),
        job_timeout_s=int(_get(env, "LAB_JOB_TIMEOUT_S", str(3 * 3600))),
        job_mem_mb=int(_get(env, "LAB_JOB_MEM_MB", "6144")),
        job_nice=int(_get(env, "LAB_JOB_NICE", "15")),
        optuna_max_trials=int(_get(env, "LAB_OPTUNA_MAX_TRIALS", "60")),
        heartbeat_s=int(_get(env, "LAB_HEARTBEAT_S", "10")),
        stale_after_s=int(_get(env, "LAB_STALE_AFTER_S", "120")),
        poll_s=float(_get(env, "LAB_POLL_S", "2")),
        trading_db_path=_get(
            env, "LAB_TRADING_DB_PATH",
            os.environ.get("TRADING_LOCAL_DB_PATH", env.get("TRADING_LOCAL_DB_PATH",
                           str(REPO_ROOT / "bmtm_trading.db"))),
        ),
        bot_import_interval_s=int(_get(env, "LAB_BOT_IMPORT_INTERVAL_S", "300")),
        watch_delay_s=int(_get(env, "LAB_WATCH_DELAY_S", "30")),
        watch_max_active=int(_get(env, "LAB_WATCH_MAX_ACTIVE", "100")),
        klines_cache_s=max(30, int(_get(env, "LAB_KLINES_CACHE_S", "30"))),
        fast_lane=_get(env, "LAB_FAST_LANE", "1") != "0",
        strength_refresh=_get(env, "LAB_STRENGTH_REFRESH", "1") != "0",
        telegram_enabled=_get(env, "LAB_TELEGRAM_ENABLED", "1") != "0",
        telegram_chat_id=_get(env, "LAB_TELEGRAM_CHAT_ID", "") or _get(env, "TRADING_TELEGRAM_DEFAULT_CHAT_ID", ""),
        telegram_bot_token=_get(env, "TRADING_TELEGRAM_BOT_TOKEN", ""),
        telegram_min_interval_s=int(_get(env, "LAB_TELEGRAM_MIN_INTERVAL_S", "300")),
        telegram_max_per_hour=int(_get(env, "LAB_TELEGRAM_MAX_PER_HOUR", "12")),
        telegram_max_age_s=int(_get(env, "LAB_TELEGRAM_MAX_AGE_S", str(6 * 3600))),
    )

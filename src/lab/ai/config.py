"""Ringkasan AI settings (stdlib; read here so the shared LabSettings stays untouched).

Values come from the environment first, then from the screener's ``.env`` (only the
LAB_AI_* keys and ANTHROPIC_API_KEY are read from it), then the defaults below:

  LAB_AI_ENABLED            0 (default) | 1     the feature runs only when 1 AND a key is present
  ANTHROPIC_API_KEY         (absent)            never logged, never stored, never returned by the API
  LAB_AI_MODEL              claude-opus-5-5     any Messages-API model id
  LAB_AI_EFFORT             low                 low | medium | high | xhigh | max
  LAB_AI_DAILY_BUDGET_USD   5.00                spend cap per UTC day; the job stops when it is hit

The .env is re-read at most every CACHE_S seconds, so adding the key needs no restart.
"""
from __future__ import annotations

import importlib.util
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from ..settings import REPO_ROOT, _read_dotenv

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_EFFORT = "low"
DEFAULT_BUDGET_USD = 5.0
EFFORTS = ("low", "medium", "high", "xhigh", "max")
CACHE_S = 30.0
KEY_NAME = "ANTHROPIC_API_KEY"

# USD per million tokens (Anthropic first-party list prices, cached 2026-11-03).
# in / out / cache read / 5-minute cache write.
PRICES: dict[str, dict[str, float]] = {
    "claude-opus-5-5": {"in": 4.00, "out": 20.00, "cache_read": 0.20, "cache_write": 5.00},
    "claude-opus-5": {"in": 5.00, "out": 25.00, "cache_read": 0.50, "cache_write": 6.25},
    "claude-opus-4-8": {"in": 5.00, "out": 25.00, "cache_read": 0.50, "cache_write": 6.25},
    "claude-sonnet-5-5": {"in": 2.00, "out": 10.00, "cache_read": 0.10, "cache_write": 2.50},
    "claude-sonnet-5": {"in": 2.00, "out": 10.00, "cache_read": 0.20, "cache_write": 2.50},
    "claude-haiku-5-5": {"in": 0.10, "out": 0.50, "cache_read": 0.01, "cache_write": 0.125},
    "claude-fable-5-2": {"in": 8.00, "out": 40.00, "cache_read": 0.20, "cache_write": 10.00},
}
# Unknown model id: price it like the most expensive model so the budget cap stays safe.
FALLBACK_PRICE = {"in": 10.00, "out": 50.00, "cache_read": 0.25, "cache_write": 12.50}
# Models that accept the server-side refusal fallback (`fallbacks: "default"`, beta header below).
FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-fable-5-2", "claude-fable-5-1"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"

REASON_TEXT = {
    "no_key": "AI belum aktif — perlu API key",
    "disabled": "AI dimatikan (LAB_AI_ENABLED=0)",
    "sdk_missing": "AI belum aktif — paket anthropic belum terpasang di server",
    "over_budget": "AI berhenti untuk hari ini — batas biaya harian tercapai",
}

_MODEL_RE = re.compile(r"^[a-z0-9][a-z0-9.\-]{2,63}$")


@dataclass(frozen=True)
class AiConfig:
    enabled: bool = False
    model: str = DEFAULT_MODEL
    effort: str = DEFAULT_EFFORT
    daily_budget_usd: float = DEFAULT_BUDGET_USD
    api_key: str = field(default="", repr=False)

    @property
    def key_present(self) -> bool:
        return bool(self.api_key)


def _dotenv_key(path, name: str) -> str:
    """One non-LAB key from .env (the shared reader only returns LAB_* keys). Never logged."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        if k.startswith("export "):
            k = k[7:].strip()
        if k == name:
            return v.strip().strip('"').strip("'")
    return ""


def _load() -> AiConfig:
    path = REPO_ROOT / ".env"
    env = _read_dotenv(path)

    def g(k: str, d: str) -> str:
        return os.environ.get(k, env.get(k, d)).strip()

    key = os.environ.get(KEY_NAME, "").strip() or _dotenv_key(path, KEY_NAME)
    model = g("LAB_AI_MODEL", DEFAULT_MODEL) or DEFAULT_MODEL
    if not _MODEL_RE.match(model):
        model = DEFAULT_MODEL
    effort = g("LAB_AI_EFFORT", DEFAULT_EFFORT).lower()
    if effort not in EFFORTS:
        effort = DEFAULT_EFFORT
    try:
        budget = max(0.0, float(g("LAB_AI_DAILY_BUDGET_USD", str(DEFAULT_BUDGET_USD))))
    except ValueError:
        budget = DEFAULT_BUDGET_USD
    return AiConfig(enabled=g("LAB_AI_ENABLED", "0") == "1", model=model, effort=effort,
                    daily_budget_usd=budget, api_key=key)


_cache: dict[str, Any] = {"at": 0.0, "cfg": None}
_lock = threading.Lock()


def ai_config(fresh: bool = False) -> AiConfig:
    with _lock:
        now = time.monotonic()
        if fresh or _cache["cfg"] is None or now - _cache["at"] > CACHE_S:
            _cache["cfg"], _cache["at"] = _load(), now
        return _cache["cfg"]


def reset_cache() -> None:
    with _lock:
        _cache["cfg"], _cache["at"] = None, 0.0


def sdk_available() -> bool:
    """True when the anthropic package is installed (checked without importing it)."""
    try:
        return importlib.util.find_spec("anthropic") is not None
    except (ImportError, ValueError):
        return False


def off_reason(cfg: Optional[AiConfig] = None) -> Optional[str]:
    """Why the feature cannot run at all (budget aside): no_key | disabled | sdk_missing | None."""
    cfg = cfg or ai_config()
    if not cfg.key_present:
        return "no_key"
    if not cfg.enabled:
        return "disabled"
    if not sdk_available():
        return "sdk_missing"
    return None


# ── cost ─────────────────────────────────────────────────────────────────

def price_for(model: Optional[str]) -> tuple[dict[str, float], str]:
    if model and model in PRICES:
        return PRICES[model], "table"
    return FALLBACK_PRICE, "fallback_max"


def _num(x: Any) -> int:
    try:
        return int(x or 0)
    except (TypeError, ValueError):
        return 0


def tokens_cost(tokens: dict, model: Optional[str]) -> float:
    p, _ = price_for(model)
    return (_num(tokens.get("input_tokens")) * p["in"] + _num(tokens.get("output_tokens")) * p["out"]
            + _num(tokens.get("cache_read_input_tokens")) * p["cache_read"]
            + _num(tokens.get("cache_creation_input_tokens")) * p["cache_write"]) / 1e6


def usage_cost(usage: dict, requested_model: str, served_model: Optional[str] = None) -> tuple[float, dict]:
    """(USD, token totals) for one response. With a server-side fallback the API reports
    every attempt in ``usage.iterations`` (each priced at its own model, conservatively
    counting declined attempts too); otherwise the top-level usage, priced at the model
    that served the response."""
    keys = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
    its = usage.get("iterations") or []
    if its:
        cost, tot = 0.0, {k: 0 for k in keys}
        for it in its:
            cost += tokens_cost(it, it.get("model") or requested_model)
            for k in keys:
                tot[k] += _num(it.get(k))
        return cost, tot
    tot = {k: _num(usage.get(k)) for k in keys}
    return tokens_cost(tot, served_model or requested_model), tot

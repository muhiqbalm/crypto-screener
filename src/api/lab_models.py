"""Request models for /api/v1/lab (responses are plain JSON dicts)."""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,20}USDT$")


def norm_symbol(v: str) -> str:
    s = str(v).upper().replace("/", "").replace(":USDT", "").replace("-", "")
    if s.endswith("USDTUSDT"):
        s = s[:-4]
    if not SYMBOL_RE.match(s):
        raise ValueError(f"invalid USD-M symbol: {v}")
    return s


class Costs(BaseModel):
    commission_pct: float = Field(0.05, ge=0, le=1.0)
    slippage_pct: float = Field(0.05, ge=0, le=2.0)
    funding: bool = True


def _check_date(v: Optional[str]) -> Optional[str]:
    if v in (None, ""):
        return None
    date.fromisoformat(v)
    return v


N_TRIALS_OPTIONS = (10, 30, 60)


class SearchSpec(BaseModel):
    """Optimize search space: which tunable params to search and optional ranges."""
    params: list[str] = Field(default_factory=list, max_length=50)
    ranges: dict[str, list[float]] = Field(default_factory=dict)


def _check_trials(v: Optional[int]) -> Optional[int]:
    if v is not None and v not in N_TRIALS_OPTIONS:
        raise ValueError(f"n_trials must be one of {list(N_TRIALS_OPTIONS)}")
    return v


class RunCreate(BaseModel):
    template_id: str
    symbol: str
    timeframe: str
    start: Optional[str] = None
    end: Optional[str] = None
    params: dict[str, Any] = Field(default_factory=dict)
    costs: Costs = Field(default_factory=Costs)
    mode: Literal["backtest", "validate", "optimize"] = "backtest"
    n_trials: Optional[int] = None  # 10 | 30 | 60 (optimize); also capped by LAB_OPTUNA_MAX_TRIALS
    search: Optional[SearchSpec] = None  # optimize only

    @field_validator("n_trials")
    @classmethod
    def _trials(cls, v: Optional[int]) -> Optional[int]:
        return _check_trials(v)


    @field_validator("symbol")
    @classmethod
    def _sym(cls, v: str) -> str:
        return norm_symbol(v)
    @field_validator("start", "end")
    @classmethod
    def _dates(cls, v: Optional[str]) -> Optional[str]:
        return _check_date(v)


class ScanCreate(BaseModel):
    template_id: str
    symbols: list[str] = Field(min_length=1, max_length=60)
    timeframes: list[str] = Field(min_length=1, max_length=5)
    params: dict[str, Any] = Field(default_factory=dict)
    costs: Costs = Field(default_factory=Costs)
    mode: Literal["validate", "optimize"] = "validate"
    start: Optional[str] = None
    end: Optional[str] = None
    n_trials: Optional[int] = None
    search: Optional[SearchSpec] = None

    @field_validator("n_trials")
    @classmethod
    def _trials(cls, v: Optional[int]) -> Optional[int]:
        return _check_trials(v)

    @field_validator("symbols")
    @classmethod
    def _syms(cls, v: list[str]) -> list[str]:
        out = []
        for s in v:
            n = norm_symbol(s)
            if n not in out:
                out.append(n)
        return out

    @field_validator("start", "end")
    @classmethod
    def _dates(cls, v: Optional[str]) -> Optional[str]:
        return _check_date(v)


class WatchCreate(BaseModel):
    template_id: str
    symbol: str
    timeframe: str
    params: dict[str, Any] = Field(default_factory=dict)
    costs: Costs = Field(default_factory=Costs)

    @field_validator("symbol")
    @classmethod
    def _sym(cls, v: str) -> str:
        return norm_symbol(v)


class PaperAccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    starting_balance: float = Field(10000.0, gt=0, le=1e9)
    risk_pct: float = Field(0.5, gt=0, le=100)
    leverage_max: float = Field(5.0, ge=1, le=125)


class PaperOrderCreate(BaseModel):
    account_id: int
    symbol: str
    side: Literal["long", "short"]
    sl: float = Field(gt=0)
    tp: Optional[float] = Field(None, gt=0)
    qty: Optional[float] = Field(None, gt=0)
    note: Optional[str] = Field(None, max_length=2000)
    watch_id: Optional[int] = None

    @field_validator("symbol")
    @classmethod
    def _sym(cls, v: str) -> str:
        return norm_symbol(v)


class AutoPaper(BaseModel):
    account_id: Optional[int] = None
    enabled: bool


class JournalPatch(BaseModel):
    notes: Optional[str] = Field(None, max_length=10000)
    tags: Optional[list[str]] = Field(None, max_length=50)

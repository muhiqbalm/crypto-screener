-- Strategy Lab schema (lab.db). Separate from bmtm_trading.db.
-- All timestamps are ISO-8601 UTC strings.

CREATE TABLE IF NOT EXISTS lab_jobs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    kind             TEXT    NOT NULL,                 -- run | watch_eval
    ref_id           INTEGER,                          -- lab_runs.id / watches.id
    status           TEXT    NOT NULL DEFAULT 'queued',-- queued|running|done|error|cancelled
    priority         INTEGER NOT NULL DEFAULT 0,
    payload_json     TEXT,
    progress_json    TEXT,
    error            TEXT,
    worker_id        TEXT,
    pid              INTEGER,
    attempts         INTEGER NOT NULL DEFAULT 0,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT    NOT NULL,
    started_at       TEXT,
    heartbeat_at     TEXT,
    finished_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_lab_jobs_status ON lab_jobs (status, priority, id);

CREATE TABLE IF NOT EXISTS strategy_configs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    template_id  TEXT NOT NULL,
    name         TEXT,
    params_json  TEXT NOT NULL,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lab_runs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id           INTEGER,
    scan_id          INTEGER,
    config_id        INTEGER,
    template_id      TEXT NOT NULL,
    symbol           TEXT NOT NULL,
    timeframe        TEXT NOT NULL,
    mode             TEXT NOT NULL,                    -- backtest | validate | optimize
    status           TEXT NOT NULL DEFAULT 'queued',
    start_date       TEXT,
    end_date         TEXT,
    params_json      TEXT NOT NULL,
    costs_json       TEXT NOT NULL,
    verdict          TEXT,                             -- PASS | FAIL | NULL (immutable once set)
    checks_json      TEXT,                             -- immutable once set
    honesty_version  TEXT,
    metrics_json     TEXT,
    oos_metrics_json TEXT,
    best_params_json TEXT,
    extra_json       TEXT,
    holdout_start    TEXT,
    holdout_touches  INTEGER,
    net_return_pct   REAL,
    profit_factor    REAL,
    max_dd_pct       REAL,
    trades           INTEGER,
    engine_commit    TEXT,
    error            TEXT,
    created_at       TEXT NOT NULL,
    finished_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_lab_runs_created ON lab_runs (id DESC);
CREATE INDEX IF NOT EXISTS idx_lab_runs_scan ON lab_runs (scan_id);

-- Verdict + checks are write-once: an honesty report can never be edited.
CREATE TRIGGER IF NOT EXISTS lab_runs_verdict_immutable
BEFORE UPDATE OF verdict, checks_json ON lab_runs
WHEN OLD.verdict IS NOT NULL OR OLD.checks_json IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'lab_runs.verdict/checks_json are immutable');
END;

CREATE TRIGGER IF NOT EXISTS lab_runs_no_delete_with_verdict
BEFORE DELETE ON lab_runs
WHEN OLD.verdict IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'lab_runs with a verdict cannot be deleted');
END;

-- Locked holdout per (template, symbol, timeframe): set on first touch, never moved.
CREATE TABLE IF NOT EXISTS holdout_locks (
    template_id    TEXT NOT NULL,
    symbol         TEXT NOT NULL,
    timeframe      TEXT NOT NULL,
    holdout_start  TEXT NOT NULL,
    touches        INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL,
    last_touch_at  TEXT,
    PRIMARY KEY (template_id, symbol, timeframe)
);

CREATE TRIGGER IF NOT EXISTS holdout_lock_start_immutable
BEFORE UPDATE OF holdout_start ON holdout_locks
WHEN NEW.holdout_start IS NOT OLD.holdout_start
BEGIN
    SELECT RAISE(ABORT, 'holdout_start is locked');
END;

CREATE TABLE IF NOT EXISTS lab_scans (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    template_id     TEXT NOT NULL,
    mode            TEXT NOT NULL,
    symbols_json    TEXT NOT NULL,
    timeframes_json TEXT NOT NULL,
    params_json     TEXT,
    costs_json      TEXT,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scan_rows (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id   INTEGER NOT NULL,
    symbol    TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    run_id    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scan_rows_scan ON scan_rows (scan_id);

-- ── Watches (live strategy evaluation, no orders) ─────────────────────────
CREATE TABLE IF NOT EXISTS watches (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    template_id     TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    timeframe       TEXT NOT NULL,
    params_json     TEXT NOT NULL,
    costs_json      TEXT NOT NULL,
    active          INTEGER NOT NULL DEFAULT 1,
    autopaper_account_id INTEGER,
    autopaper_enabled    INTEGER NOT NULL DEFAULT 0,
    last_bar_scheduled   TEXT,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS watch_state (
    watch_id           INTEGER PRIMARY KEY,
    computed_at        TEXT NOT NULL,
    last_bar           TEXT,
    position_json      TEXT,
    recent_trades_json TEXT,
    last_signal_json   TEXT,
    error              TEXT
);

-- ── Paper trading ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS paper_accounts (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT NOT NULL,
    starting_balance REAL NOT NULL,
    balance          REAL NOT NULL,
    risk_pct         REAL NOT NULL,
    leverage_max     REAL NOT NULL,
    realized_pnl     REAL NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_positions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id    INTEGER NOT NULL,
    symbol        TEXT NOT NULL,
    side          TEXT NOT NULL,
    qty           REAL NOT NULL,
    entry_price   REAL NOT NULL,
    entry_time    TEXT NOT NULL,
    sl            REAL,
    tp            REAL,
    fees          REAL NOT NULL DEFAULT 0,
    funding       REAL NOT NULL DEFAULT 0,
    risk_amount   REAL,
    source        TEXT NOT NULL,                      -- paper_manual | paper_auto
    watch_id      INTEGER,
    note          TEXT,
    status        TEXT NOT NULL DEFAULT 'open',       -- open | closed
    last_checked_bar TEXT,
    last_funding_at  TEXT,
    mark_price    REAL,
    mark_time     TEXT,
    exit_price    REAL,
    exit_time     TEXT,
    exit_reason   TEXT,
    pnl           REAL,
    journal_id    INTEGER,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_paper_positions_open ON paper_positions (status, account_id);

CREATE TABLE IF NOT EXISTS journal_entries (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id   INTEGER,
    source       TEXT NOT NULL,                       -- paper_manual | paper_auto | bot
    external_id  TEXT,                                -- bot positions.id for imports
    watch_id     INTEGER,
    run_id       INTEGER,
    symbol       TEXT NOT NULL,
    side         TEXT NOT NULL,
    entry_time   TEXT,
    entry_price  REAL,
    exit_time    TEXT,
    exit_price   REAL,
    qty          REAL,
    fees         REAL,
    funding      REAL,
    sl           REAL,
    tp           REAL,
    risk_amount  REAL,
    pnl          REAL,
    r_multiple   REAL,
    exit_reason  TEXT,
    notes        TEXT,
    tags         TEXT,                                -- JSON list
    created_at   TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_journal_external ON journal_entries (source, external_id)
    WHERE external_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS lab_kv (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- ── Universal v0 (multi-coin portfolio, paper only) ───────────────────────
CREATE TABLE IF NOT EXISTS universal_watches (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    name               TEXT,
    params_json        TEXT NOT NULL,
    costs_json         TEXT NOT NULL,
    account_id         INTEGER,                       -- paper_accounts.id
    autopaper_enabled  INTEGER NOT NULL DEFAULT 1,
    telegram_enabled   INTEGER NOT NULL DEFAULT 1,
    active             INTEGER NOT NULL DEFAULT 1,
    run_id             INTEGER,                       -- lab_runs.id it was created from (optional)
    last_rebalance_bar TEXT,                          -- open time of the last rebalance boundary bar
    created_at         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS universal_state (
    watch_id        INTEGER PRIMARY KEY,
    computed_at     TEXT NOT NULL,
    last_bar        TEXT,
    targets_json    TEXT,
    ranks_json      TEXT,
    next_rebalance  TEXT,
    error           TEXT
);

CREATE TABLE IF NOT EXISTS universal_rebalances (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    watch_id      INTEGER NOT NULL,
    bar           TEXT NOT NULL,                      -- close time of the decision bar
    targets_json  TEXT,
    orders_json   TEXT,
    equity        REAL,
    note          TEXT,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_universal_rebalances_watch ON universal_rebalances (watch_id, id DESC);

-- Outbox for Telegram alerts (sent by the worker scheduler, rate-limited).
CREATE TABLE IF NOT EXISTS lab_alerts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    channel     TEXT NOT NULL,                        -- telegram
    ref         TEXT NOT NULL,                        -- e.g. universal:3
    text        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',      -- pending|sent|superseded|expired|skipped|error
    error       TEXT,
    created_at  TEXT NOT NULL,
    sent_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_lab_alerts_status ON lab_alerts (status, id);

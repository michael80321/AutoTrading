CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

CREATE TABLE IF NOT EXISTS signals (
    id          BIGSERIAL,
    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    pool        TEXT NOT NULL,           -- 'crypto' | 'stock'
    bot_id      TEXT NOT NULL,
    bot_name    TEXT,
    school      TEXT,
    symbol      TEXT NOT NULL,
    side        TEXT NOT NULL,           -- 'LONG' | 'SHORT'
    entry_price DOUBLE PRECISION,
    stop_loss   DOUBLE PRECISION,
    confidence  DOUBLE PRECISION,
    rationale   TEXT,
    PRIMARY KEY (id, ts)
);
SELECT create_hypertable('signals', 'ts', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_signals_pool_ts ON signals (pool, ts DESC);

CREATE TABLE IF NOT EXISTS trades (
    id          BIGSERIAL,
    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    pool        TEXT NOT NULL,
    bot_id      TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    side        TEXT NOT NULL,
    entry_price DOUBLE PRECISION,
    exit_price  DOUBLE PRECISION,
    pnl         DOUBLE PRECISION,
    hold_bars   INTEGER,
    PRIMARY KEY (id, ts)
);
SELECT create_hypertable('trades', 'ts', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS bot_metrics_history (
    id          BIGSERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    pool        TEXT NOT NULL,
    bot_id      TEXT NOT NULL,
    win_rate    DOUBLE PRECISION,
    expectancy  DOUBLE PRECISION,
    sharpe      DOUBLE PRECISION,
    max_drawdown DOUBLE PRECISION,
    total_trades INTEGER
);

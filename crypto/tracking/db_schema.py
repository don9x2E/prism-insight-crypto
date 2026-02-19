"""Database schema for crypto tracking (Phase 2)."""

import logging

logger = logging.getLogger(__name__)


TABLE_CRYPTO_HOLDINGS = """
CREATE TABLE IF NOT EXISTS crypto_holdings (
    symbol TEXT PRIMARY KEY,           -- BTC-USD, ETH-USD...
    asset_name TEXT NOT NULL,          -- BTC, ETH...
    buy_price REAL NOT NULL,           -- USD
    buy_date TEXT NOT NULL,
    quantity REAL,                     -- fractional size for crypto
    notional_usd REAL,                 -- order notional
    current_price REAL,
    last_updated TEXT,
    scenario TEXT,                     -- JSON
    target_price REAL,
    stop_loss REAL,
    trigger_type TEXT,
    timeframe TEXT,                    -- 15m/1h/4h/1d
    theme TEXT                         -- L1/AI/DeFi/Meme etc
)
"""


TABLE_CRYPTO_TRADING_HISTORY = """
CREATE TABLE IF NOT EXISTS crypto_trading_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    asset_name TEXT NOT NULL,
    buy_price REAL NOT NULL,
    buy_date TEXT NOT NULL,
    quantity REAL,
    notional_usd REAL,
    sell_price REAL NOT NULL,
    sell_date TEXT NOT NULL,
    profit_rate REAL NOT NULL,
    holding_hours REAL,                -- crypto is 24/7; use hour granularity
    scenario TEXT,
    trigger_type TEXT,
    timeframe TEXT,
    theme TEXT
)
"""


TABLE_CRYPTO_WATCHLIST_HISTORY = """
CREATE TABLE IF NOT EXISTS crypto_watchlist_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    analyzed_date TEXT NOT NULL,
    current_price REAL NOT NULL,
    buy_score INTEGER,
    min_score INTEGER,
    decision TEXT NOT NULL,            -- entry/no_entry
    skip_reason TEXT,
    target_price REAL,
    stop_loss REAL,
    risk_reward_ratio REAL,
    trigger_type TEXT,
    timeframe TEXT,
    theme TEXT,
    scenario TEXT
)
"""


TABLE_CRYPTO_PERFORMANCE_TRACKER = """
CREATE TABLE IF NOT EXISTS crypto_analysis_performance_tracker (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    analysis_date TEXT NOT NULL,
    analysis_price REAL NOT NULL,

    predicted_direction TEXT,          -- UP/DOWN/NEUTRAL
    target_price REAL,
    stop_loss REAL,
    buy_score INTEGER,
    decision TEXT,
    skip_reason TEXT,
    risk_reward_ratio REAL,

    price_24h REAL,
    price_72h REAL,
    price_168h REAL,                   -- 7d

    return_24h REAL,
    return_72h REAL,
    return_168h REAL,

    hit_target INTEGER DEFAULT 0,
    hit_stop_loss INTEGER DEFAULT 0,
    tracking_status TEXT DEFAULT 'pending',
    was_traded INTEGER DEFAULT 0,

    trigger_type TEXT,
    timeframe TEXT,
    theme TEXT,
    created_at TEXT NOT NULL,
    last_updated TEXT
)
"""


TABLE_CRYPTO_HOLDING_DECISIONS = """
CREATE TABLE IF NOT EXISTS crypto_holding_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    decision_date TEXT NOT NULL,
    decision_time TEXT NOT NULL,

    current_price REAL NOT NULL,
    should_sell BOOLEAN NOT NULL,
    sell_reason TEXT,
    confidence INTEGER,

    technical_trend TEXT,
    volume_analysis TEXT,
    market_condition_impact TEXT,
    time_factor TEXT,

    portfolio_adjustment_needed BOOLEAN,
    adjustment_reason TEXT,
    new_target_price REAL,
    new_stop_loss REAL,
    adjustment_urgency TEXT,

    full_json_data TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (symbol) REFERENCES crypto_holdings(symbol)
)
"""


TABLE_CRYPTO_ORDER_EXECUTIONS = """
CREATE TABLE IF NOT EXISTS crypto_order_executions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,                -- buy/sell
    order_type TEXT NOT NULL,          -- market/limit
    status TEXT NOT NULL,              -- filled/unfilled/rejected
    requested_price REAL,
    executed_price REAL,
    quantity REAL,
    quote_amount REAL,
    fee_amount REAL,
    mode TEXT DEFAULT 'paper',         -- paper/real
    message TEXT,
    metadata TEXT,
    created_at TEXT NOT NULL
)
"""


CRYPTO_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_crypto_holdings_theme ON crypto_holdings(theme)",
    "CREATE INDEX IF NOT EXISTS idx_crypto_holdings_trigger ON crypto_holdings(trigger_type)",
    "CREATE INDEX IF NOT EXISTS idx_crypto_history_symbol ON crypto_trading_history(symbol)",
    "CREATE INDEX IF NOT EXISTS idx_crypto_history_sell_date ON crypto_trading_history(sell_date)",
    "CREATE INDEX IF NOT EXISTS idx_crypto_watchlist_symbol ON crypto_watchlist_history(symbol)",
    "CREATE INDEX IF NOT EXISTS idx_crypto_watchlist_date ON crypto_watchlist_history(analyzed_date)",
    "CREATE INDEX IF NOT EXISTS idx_crypto_perf_symbol ON crypto_analysis_performance_tracker(symbol)",
    "CREATE INDEX IF NOT EXISTS idx_crypto_perf_status ON crypto_analysis_performance_tracker(tracking_status)",
    "CREATE INDEX IF NOT EXISTS idx_crypto_holding_dec_symbol ON crypto_holding_decisions(symbol)",
    "CREATE INDEX IF NOT EXISTS idx_crypto_exec_symbol ON crypto_order_executions(symbol)",
    "CREATE INDEX IF NOT EXISTS idx_crypto_exec_created ON crypto_order_executions(created_at)",
]


def create_crypto_tables(cursor, conn):
    tables = [
        ("crypto_holdings", TABLE_CRYPTO_HOLDINGS),
        ("crypto_trading_history", TABLE_CRYPTO_TRADING_HISTORY),
        ("crypto_watchlist_history", TABLE_CRYPTO_WATCHLIST_HISTORY),
        ("crypto_analysis_performance_tracker", TABLE_CRYPTO_PERFORMANCE_TRACKER),
        ("crypto_holding_decisions", TABLE_CRYPTO_HOLDING_DECISIONS),
        ("crypto_order_executions", TABLE_CRYPTO_ORDER_EXECUTIONS),
    ]
    for table_name, table_sql in tables:
        cursor.execute(table_sql)
        logger.info("Created/verified table: %s", table_name)
    conn.commit()


def create_crypto_indexes(cursor, conn):
    for index_sql in CRYPTO_INDEXES:
        cursor.execute(index_sql)
    conn.commit()


def add_theme_columns_if_missing(cursor, conn):
    """Add theme columns to tables created before Phase 2.5."""
    migrations = [
        ("crypto_watchlist_history", "theme TEXT"),
        ("crypto_analysis_performance_tracker", "theme TEXT"),
    ]
    for table_name, column_def in migrations:
        try:
            cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_def}")
            conn.commit()
            logger.info("Added column to %s: %s", table_name, column_def)
        except Exception:
            pass


def get_crypto_holdings_count(cursor) -> int:
    cursor.execute("SELECT COUNT(*) FROM crypto_holdings")
    return cursor.fetchone()[0]


def is_crypto_symbol_in_holdings(cursor, symbol: str) -> bool:
    cursor.execute("SELECT COUNT(*) FROM crypto_holdings WHERE symbol = ?", (symbol,))
    return cursor.fetchone()[0] > 0



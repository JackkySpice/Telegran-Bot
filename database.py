import aiosqlite
import config

_db: aiosqlite.Connection | None = None


async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is None:
        _db = await aiosqlite.connect(config.DB_PATH)
        _db.row_factory = aiosqlite.Row
        await _db.execute("PRAGMA journal_mode=WAL")
        await _db.execute("PRAGMA foreign_keys=ON")
        await _init_tables(_db)
    return _db


async def close_db():
    global _db
    if _db:
        await _db.close()
        _db = None


async def _init_tables(db: aiosqlite.Connection):
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id       INTEGER PRIMARY KEY,
            username      TEXT,
            first_name    TEXT,
            referred_by   INTEGER REFERENCES users(user_id),
            referral_code TEXT UNIQUE,
            wallet_address TEXT,
            balance_trx   REAL DEFAULT 0.0,
            balance_usdt  REAL DEFAULT 0.0,
            created_at    TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS deposits (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       INTEGER NOT NULL REFERENCES users(user_id),
            plan_id       INTEGER NOT NULL,
            amount        REAL NOT NULL,
            currency      TEXT NOT NULL DEFAULT 'TRX',
            cp_txn_id     TEXT UNIQUE,
            deposit_address TEXT,
            status        TEXT NOT NULL DEFAULT 'pending',
            cp_status     INTEGER DEFAULT 0,
            created_at    TEXT DEFAULT (datetime('now')),
            confirmed_at  TEXT
        );

        CREATE TABLE IF NOT EXISTS investments (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       INTEGER NOT NULL REFERENCES users(user_id),
            plan_id       INTEGER NOT NULL,
            deposit_id    INTEGER REFERENCES deposits(id),
            amount        REAL NOT NULL,
            currency      TEXT NOT NULL DEFAULT 'TRX',
            profit_pct    REAL NOT NULL,
            duration_days INTEGER NOT NULL,
            lock_days     INTEGER NOT NULL,
            daily_profit  REAL NOT NULL,
            total_profit  REAL NOT NULL,
            earned_so_far REAL DEFAULT 0.0,
            status        TEXT NOT NULL DEFAULT 'active',
            started_at    TEXT DEFAULT (datetime('now')),
            unlocks_at    TEXT,
            expires_at    TEXT
        );

        CREATE TABLE IF NOT EXISTS referral_earnings (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       INTEGER NOT NULL REFERENCES users(user_id),
            from_user_id  INTEGER NOT NULL REFERENCES users(user_id),
            investment_id INTEGER NOT NULL REFERENCES investments(id),
            level         INTEGER NOT NULL,
            pct           REAL NOT NULL,
            amount        REAL NOT NULL,
            currency      TEXT NOT NULL DEFAULT 'TRX',
            created_at    TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS withdrawals (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       INTEGER NOT NULL REFERENCES users(user_id),
            amount        REAL NOT NULL,
            fee           REAL NOT NULL DEFAULT 0.0,
            net_amount    REAL NOT NULL DEFAULT 0.0,
            currency      TEXT NOT NULL DEFAULT 'TRX',
            wallet_address TEXT,
            status        TEXT NOT NULL DEFAULT 'pending',
            created_at    TEXT DEFAULT (datetime('now')),
            processed_at  TEXT
        );

        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        INSERT OR IGNORE INTO settings (key, value) VALUES ('payouts_paused', '0');

        CREATE INDEX IF NOT EXISTS idx_deposits_user
            ON deposits(user_id);
        CREATE INDEX IF NOT EXISTS idx_deposits_txn
            ON deposits(cp_txn_id);
        CREATE INDEX IF NOT EXISTS idx_deposits_status
            ON deposits(status);
        CREATE INDEX IF NOT EXISTS idx_investments_user
            ON investments(user_id);
        CREATE INDEX IF NOT EXISTS idx_investments_status
            ON investments(status);
        CREATE INDEX IF NOT EXISTS idx_referral_earnings_user
            ON referral_earnings(user_id);
        CREATE INDEX IF NOT EXISTS idx_withdrawals_user
            ON withdrawals(user_id);
    """)
    await db.commit()


async def get_setting(key: str, default: str = "") -> str:
    db = await get_db()
    row = await db.execute_fetchall(
        "SELECT value FROM settings WHERE key = ?", (key,)
    )
    return row[0][0] if row else default


async def set_setting(key: str, value: str):
    db = await get_db()
    await db.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (key, value),
    )
    await db.commit()

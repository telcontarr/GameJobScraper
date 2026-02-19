"""SQLite schema creation and migrations."""

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 2

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Identity / deduplication
    external_id TEXT,
    source TEXT NOT NULL,
    url TEXT NOT NULL,
    url_hash TEXT NOT NULL,

    -- Job details
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT,
    is_remote INTEGER DEFAULT 0,
    description TEXT,
    description_raw TEXT,
    employment_type TEXT,
    salary_min REAL,
    salary_max REAL,
    salary_currency TEXT,

    -- Search grouping (e.g. "priority", "us_canada")
    query_group TEXT DEFAULT 'priority',

    -- Timestamps
    date_posted TEXT,
    date_scraped TEXT NOT NULL,
    date_updated TEXT,
    is_active INTEGER DEFAULT 1,

    -- Scoring
    ai_score REAL,
    keyword_score REAL,
    combined_score REAL,
    score_reasoning TEXT,

    -- User interaction
    user_status TEXT DEFAULT 'new',
    user_notes TEXT,

    -- Cross-source dedup
    title_company_hash TEXT,

    UNIQUE(source, external_id),
    UNIQUE(url_hash)
);

CREATE INDEX IF NOT EXISTS idx_jobs_combined_score ON jobs(combined_score DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_date_scraped ON jobs(date_scraped DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(source);
CREATE INDEX IF NOT EXISTS idx_jobs_user_status ON jobs(user_status);
CREATE INDEX IF NOT EXISTS idx_jobs_is_active ON jobs(is_active);
CREATE INDEX IF NOT EXISTS idx_jobs_title_company_hash ON jobs(title_company_hash);
CREATE INDEX IF NOT EXISTS idx_jobs_query_group ON jobs(query_group);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    channel TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    status TEXT NOT NULL,
    error_message TEXT,
    FOREIGN KEY (job_id) REFERENCES jobs(id)
);

CREATE INDEX IF NOT EXISTS idx_notifications_job_channel ON notifications(job_id, channel);

CREATE TABLE IF NOT EXISTS scrape_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL,
    jobs_found INTEGER DEFAULT 0,
    jobs_new INTEGER DEFAULT 0,
    jobs_updated INTEGER DEFAULT 0,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
"""


def init_db(db_path: str) -> sqlite3.Connection:
    """Initialize the database, creating tables if they don't exist."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    # Check current schema version
    try:
        row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
        current_version = row[0] if row[0] is not None else 0
    except sqlite3.OperationalError:
        current_version = 0

    if current_version < 1:
        logger.info("Initializing database schema (version %d)", SCHEMA_VERSION)
        conn.executescript(SCHEMA_SQL)
        conn.execute(
            "INSERT OR REPLACE INTO schema_version (version, applied_at) VALUES (?, datetime('now'))",
            (SCHEMA_VERSION,),
        )
        conn.commit()
    else:
        # Incremental migrations
        if current_version < 2:
            logger.info("Migrating database to version 2 (adding query_group)")
            conn.execute("ALTER TABLE jobs ADD COLUMN query_group TEXT DEFAULT 'priority'")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_query_group ON jobs(query_group)")
            conn.execute(
                "INSERT OR REPLACE INTO schema_version (version, applied_at) VALUES (?, datetime('now'))",
                (2,),
            )
            conn.commit()

    return conn

"""Data access layer — CRUD operations with deduplication."""

import logging
import sqlite3
from datetime import datetime, timezone

from gamejobtracker.scrapers.base import ScrapedJob
from gamejobtracker.utils.text_processing import title_company_hash, url_hash

logger = logging.getLogger(__name__)


class JobRepository:
    """Database operations for job listings."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # ── Upsert / Dedup ─────────────────────────────────────────────

    def upsert_job(self, job: ScrapedJob) -> tuple[int, bool]:
        """Insert a job or update if it already exists.

        Returns (job_id, is_new).
        """
        u_hash = url_hash(job.url)
        tc_hash = title_company_hash(job.title, job.company)
        now = datetime.now(timezone.utc).isoformat()

        # Check for existing by url_hash (same posting, same source)
        existing = self.conn.execute(
            "SELECT id FROM jobs WHERE url_hash = ?", (u_hash,)
        ).fetchone()

        if existing:
            self.conn.execute(
                "UPDATE jobs SET date_updated = ?, is_active = 1 WHERE id = ?",
                (now, existing["id"]),
            )
            self.conn.commit()
            return existing["id"], False

        # Check for cross-source duplicate (same title+company from different source)
        cross_dup = self.conn.execute(
            "SELECT id, source FROM jobs WHERE title_company_hash = ?", (tc_hash,)
        ).fetchone()

        if cross_dup:
            logger.debug(
                "Cross-source duplicate: '%s' at '%s' (existing from %s)",
                job.title, job.company, cross_dup["source"],
            )
            # Still insert — both sources are valuable — but log the overlap
            # The combined_score can later prefer whichever has the fuller description

        try:
            cursor = self.conn.execute(
                """INSERT INTO jobs (
                    external_id, source, url, url_hash,
                    title, company, location, is_remote,
                    description, description_raw, employment_type,
                    salary_min, salary_max, salary_currency,
                    query_group,
                    date_posted, date_scraped, date_updated,
                    title_company_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    job.external_id, job.source, job.url, u_hash,
                    job.title, job.company, job.location, int(job.is_remote),
                    job.description, job.description_raw, job.employment_type,
                    job.salary_min, job.salary_max, job.salary_currency,
                    job.query_group,
                    job.date_posted, job.date_scraped, now,
                    tc_hash,
                ),
            )
            self.conn.commit()
            return cursor.lastrowid, True
        except sqlite3.IntegrityError:
            # Race condition or missed duplicate — safe to ignore
            logger.debug("IntegrityError on insert for %s — likely duplicate", job.url)
            self.conn.rollback()
            row = self.conn.execute(
                "SELECT id FROM jobs WHERE url_hash = ?", (u_hash,)
            ).fetchone()
            return (row["id"] if row else 0), False

    def upsert_jobs(self, jobs: list[ScrapedJob]) -> list[tuple[int, ScrapedJob]]:
        """Upsert a batch of jobs. Returns list of (job_id, job) for NEW jobs only."""
        new_jobs = []
        for job in jobs:
            job_id, is_new = self.upsert_job(job)
            if is_new:
                new_jobs.append((job_id, job))
        return new_jobs

    # ── Scoring ────────────────────────────────────────────────────

    def update_scores(
        self,
        job_id: int,
        keyword_score: float | None = None,
        ai_score: float | None = None,
        combined_score: float | None = None,
        score_reasoning: str | None = None,
    ) -> None:
        """Update scoring fields for a job."""
        updates = []
        params = []
        if keyword_score is not None:
            updates.append("keyword_score = ?")
            params.append(keyword_score)
        if ai_score is not None:
            updates.append("ai_score = ?")
            params.append(ai_score)
        if combined_score is not None:
            updates.append("combined_score = ?")
            params.append(combined_score)
        if score_reasoning is not None:
            updates.append("score_reasoning = ?")
            params.append(score_reasoning)

        if not updates:
            return

        params.append(job_id)
        self.conn.execute(
            f"UPDATE jobs SET {', '.join(updates)} WHERE id = ?", params
        )
        self.conn.commit()

    # ── Queries ────────────────────────────────────────────────────

    def get_unscored_jobs(self) -> list[sqlite3.Row]:
        """Get jobs that haven't been scored yet."""
        return self.conn.execute(
            "SELECT * FROM jobs WHERE combined_score IS NULL AND is_active = 1 ORDER BY date_scraped DESC"
        ).fetchall()

    def get_jobs(
        self,
        min_score: float = 0.0,
        status: str | None = None,
        source: str | None = None,
        group: str | None = None,
        limit: int = 20,
    ) -> list[sqlite3.Row]:
        """Get jobs with optional filters."""
        query = "SELECT * FROM jobs WHERE is_active = 1"
        params: list = []

        if min_score > 0:
            query += " AND (combined_score >= ? OR combined_score IS NULL)"
            params.append(min_score)
        if status:
            query += " AND user_status = ?"
            params.append(status)
        if source:
            query += " AND source = ?"
            params.append(source)
        if group:
            query += " AND query_group = ?"
            params.append(group)

        query += " ORDER BY COALESCE(combined_score, 0) DESC LIMIT ?"
        params.append(limit)

        return self.conn.execute(query, params).fetchall()

    def get_job_by_id(self, job_id: int) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()

    def set_user_status(self, job_id: int, status: str, notes: str | None = None) -> None:
        if notes is not None:
            self.conn.execute(
                "UPDATE jobs SET user_status = ?, user_notes = ? WHERE id = ?",
                (status, notes, job_id),
            )
        else:
            self.conn.execute(
                "UPDATE jobs SET user_status = ? WHERE id = ?", (status, job_id)
            )
        self.conn.commit()

    # ── Stats ──────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Get summary statistics."""
        total = self.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        active = self.conn.execute("SELECT COUNT(*) FROM jobs WHERE is_active = 1").fetchone()[0]
        scored = self.conn.execute("SELECT COUNT(*) FROM jobs WHERE combined_score IS NOT NULL").fetchone()[0]

        by_source = {
            row["source"]: row["cnt"]
            for row in self.conn.execute(
                "SELECT source, COUNT(*) as cnt FROM jobs GROUP BY source"
            ).fetchall()
        }

        by_status = {
            row["user_status"]: row["cnt"]
            for row in self.conn.execute(
                "SELECT user_status, COUNT(*) as cnt FROM jobs GROUP BY user_status"
            ).fetchall()
        }

        avg_score = self.conn.execute(
            "SELECT AVG(combined_score) FROM jobs WHERE combined_score IS NOT NULL"
        ).fetchone()[0]

        high_matches = self.conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE combined_score >= 0.7"
        ).fetchone()[0]

        return {
            "total": total,
            "active": active,
            "scored": scored,
            "by_source": dict(by_source),
            "by_status": dict(by_status),
            "avg_score": round(avg_score, 3) if avg_score else 0,
            "high_matches": high_matches,
        }

    # ── Scrape Runs ────────────────────────────────────────────────

    def start_scrape_run(self, source: str) -> int:
        cursor = self.conn.execute(
            "INSERT INTO scrape_runs (source, started_at, status) VALUES (?, datetime('now'), 'running')",
            (source,),
        )
        self.conn.commit()
        return cursor.lastrowid

    def complete_scrape_run(
        self, run_id: int, jobs_found: int = 0, jobs_new: int = 0, jobs_updated: int = 0
    ) -> None:
        self.conn.execute(
            """UPDATE scrape_runs
               SET completed_at = datetime('now'), status = 'completed',
                   jobs_found = ?, jobs_new = ?, jobs_updated = ?
               WHERE id = ?""",
            (jobs_found, jobs_new, jobs_updated, run_id),
        )
        self.conn.commit()

    def fail_scrape_run(self, run_id: int, error: str) -> None:
        self.conn.execute(
            "UPDATE scrape_runs SET completed_at = datetime('now'), status = 'failed', error_message = ? WHERE id = ?",
            (error, run_id),
        )
        self.conn.commit()

    # ── Notifications ──────────────────────────────────────────────

    def get_unnotified_jobs(self, channel: str, min_score: float = 0.5) -> list[sqlite3.Row]:
        """Get jobs that haven't been notified on a given channel."""
        return self.conn.execute(
            """SELECT j.* FROM jobs j
               WHERE j.combined_score >= ?
                 AND j.is_active = 1
                 AND j.id NOT IN (
                     SELECT job_id FROM notifications WHERE channel = ? AND status = 'sent'
                 )
               ORDER BY j.combined_score DESC""",
            (min_score, channel),
        ).fetchall()

    def record_notification(self, job_id: int, channel: str, status: str, error: str | None = None) -> None:
        self.conn.execute(
            "INSERT INTO notifications (job_id, channel, sent_at, status, error_message) VALUES (?, ?, datetime('now'), ?, ?)",
            (job_id, channel, status, error),
        )
        self.conn.commit()

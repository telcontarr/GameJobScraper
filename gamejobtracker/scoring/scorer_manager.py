"""Scoring orchestration — combines keyword and AI scoring."""

import logging
import sqlite3

from gamejobtracker.db.repository import JobRepository
from gamejobtracker.scoring.ai_scorer import AIScorer
from gamejobtracker.scoring.keyword_scorer import KeywordScorer
from gamejobtracker.scoring.profile import CandidateProfile

logger = logging.getLogger(__name__)


class ScorerManager:
    """Orchestrates keyword and AI scoring, manages thresholds."""

    def __init__(self, config: dict, repo: JobRepository):
        self.config = config
        self.repo = repo

        scoring_cfg = config.get("scoring", {})
        self.engine = scoring_cfg.get("engine", "hybrid")
        self.min_keyword_for_ai = scoring_cfg.get("min_keyword_score_for_ai", 0.2)
        weights = scoring_cfg.get("weights", {})
        self.ai_weight = weights.get("ai", 0.7)
        self.keyword_weight = weights.get("keyword", 0.3)

        self.profile = CandidateProfile.from_config(config)
        self.keyword_scorer = KeywordScorer(self.profile)

        self.ai_scorer = AIScorer(config, self.profile)
        self.use_ai = self.engine in ("ai", "hybrid") and self.ai_scorer.is_available()

        if self.use_ai:
            logger.info("AI scoring enabled (model: %s)", self.ai_scorer.model)
        else:
            logger.info("Using keyword-only scoring")

    def score_job(self, job: sqlite3.Row) -> None:
        """Score a single job and save results to the database."""
        title = job["title"]
        description = job["description"]
        location = job["location"]
        is_remote = bool(job["is_remote"])
        company = job["company"]

        # Always run keyword scoring
        kw_score, kw_reasoning = self.keyword_scorer.score_job(
            title, description, location, is_remote
        )

        ai_score = None
        ai_reasoning = ""

        # Only run AI scorer for promising jobs
        if self.use_ai and kw_score >= self.min_keyword_for_ai:
            ai_score, ai_reasoning = self.ai_scorer.score_job(
                title, company, location, description
            )

        # Calculate combined score
        if ai_score is not None:
            combined = self.ai_weight * ai_score + self.keyword_weight * kw_score
            reasoning = f"AI: {ai_reasoning} | Keywords: {kw_reasoning}"
        else:
            combined = kw_score
            reasoning = f"Keywords: {kw_reasoning}"

        self.repo.update_scores(
            job_id=job["id"],
            keyword_score=kw_score,
            ai_score=ai_score,
            combined_score=combined,
            score_reasoning=reasoning,
        )

        logger.debug(
            "Scored #%d '%s': combined=%.2f (kw=%.2f, ai=%s)",
            job["id"], title, combined, kw_score,
            f"{ai_score:.2f}" if ai_score is not None else "n/a",
        )

    def score_batch(self, jobs: list[sqlite3.Row]) -> None:
        """Score a batch of jobs."""
        total = len(jobs)
        for i, job in enumerate(jobs, 1):
            try:
                self.score_job(job)
            except Exception:
                logger.exception("Error scoring job #%d '%s'", job["id"], job["title"])

            if i % 10 == 0:
                logger.info("Scored %d/%d jobs", i, total)

        logger.info("Scoring complete: %d jobs scored", total)

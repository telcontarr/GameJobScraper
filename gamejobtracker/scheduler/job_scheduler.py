"""APScheduler-based job scheduler for periodic scrape/score/notify pipeline."""

import logging
import signal
import time

from apscheduler.schedulers.background import BackgroundScheduler

from gamejobtracker.db.models import init_db
from gamejobtracker.db.repository import JobRepository

logger = logging.getLogger(__name__)


def _run_pipeline(config: dict) -> None:
    """Execute the full scrape -> score -> notify pipeline."""
    from gamejobtracker.scrapers.scraper_manager import ScraperManager
    from gamejobtracker.scrapers.jsearch import JSearchScraper
    from gamejobtracker.scrapers.workwithindies import WorkWithIndiesScraper
    from gamejobtracker.scrapers.gamejobsco import GameJobsCoScraper
    from gamejobtracker.scrapers.hitmarker import HitmarkerScraper
    from gamejobtracker.scoring.scorer_manager import ScorerManager
    from gamejobtracker.notifications.notification_manager import NotificationManager

    conn = init_db(config["database"]["path"])
    repo = JobRepository(conn)

    # Scrape
    logger.info("=== Pipeline: Scraping ===")
    scraper_mgr = ScraperManager(config, repo)
    scraper_mgr.register(WorkWithIndiesScraper(config))
    scraper_mgr.register(JSearchScraper(config))
    scraper_mgr.register(GameJobsCoScraper(config))
    scraper_mgr.register(HitmarkerScraper(config))
    new_jobs = scraper_mgr.run_all()
    logger.info("Pipeline: %d new jobs scraped", len(new_jobs))

    # Score
    logger.info("=== Pipeline: Scoring ===")
    scorer = ScorerManager(config, repo)
    unscored = repo.get_unscored_jobs()
    if unscored:
        scorer.score_batch(unscored)
        logger.info("Pipeline: %d jobs scored", len(unscored))

    # Notify
    logger.info("=== Pipeline: Notifying ===")
    notifier = NotificationManager(config, repo)
    notifier.send_all()

    logger.info("=== Pipeline complete ===")
    conn.close()


def start_scheduler(config: dict) -> None:
    """Start the background scheduler and block until interrupted."""
    schedule_hours = config.get("scraping", {}).get("schedule_hours", [8, 20])
    timezone = config.get("scraping", {}).get("timezone", "US/Eastern")

    scheduler = BackgroundScheduler(timezone=timezone)
    scheduler.add_job(
        _run_pipeline,
        "cron",
        hour=",".join(str(h) for h in schedule_hours),
        minute=0,
        args=[config],
        id="scrape_pipeline",
        replace_existing=True,
        max_instances=1,
    )

    # Run once immediately on startup
    scheduler.add_job(
        _run_pipeline,
        args=[config],
        id="initial_run",
    )

    scheduler.start()
    logger.info(
        "Scheduler started — pipeline runs daily at %s %s",
        ", ".join(f"{h}:00" for h in schedule_hours),
        timezone,
    )

    # Block until Ctrl+C
    shutdown = False

    def _signal_handler(signum, frame):
        nonlocal shutdown
        shutdown = True

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    try:
        while not shutdown:
            time.sleep(1)
    finally:
        logger.info("Shutting down scheduler...")
        scheduler.shutdown(wait=False)

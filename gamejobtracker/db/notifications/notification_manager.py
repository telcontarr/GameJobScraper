"""Notification orchestration — manages all notification channels."""

import logging

from gamejobtracker.db.repository import JobRepository
from gamejobtracker.notifications.discord_notifier import DiscordNotifier
from gamejobtracker.notifications.email_notifier import EmailNotifier

logger = logging.getLogger(__name__)


class NotificationManager:
    """Sends notifications across all configured channels."""

    def __init__(self, config: dict, repo: JobRepository):
        self.config = config
        self.repo = repo
        self.discord = DiscordNotifier(config)
        self.email = EmailNotifier(config)

        notification_cfg = config.get("scoring", {})
        self.min_score = notification_cfg.get("notification_threshold", 0.5)

    def send_all(self) -> None:
        """Send notifications for all un-notified high-scoring jobs."""
        if self.discord.is_available():
            self._send_channel("discord")

        if self.email.is_available():
            self._send_channel("email")

    def _send_channel(self, channel: str) -> None:
        """Send notifications for a specific channel."""
        jobs = self.repo.get_unnotified_jobs(channel, self.min_score)

        if not jobs:
            logger.info("No new jobs to notify via %s", channel)
            return

        logger.info("Sending %d job(s) via %s", len(jobs), channel)

        if channel == "discord":
            results = self.discord.send_jobs(jobs)
        elif channel == "email":
            results = self.email.send_jobs(jobs)
        else:
            logger.error("Unknown channel: %s", channel)
            return

        for job_id, success, error in results:
            self.repo.record_notification(
                job_id=job_id,
                channel=channel,
                status="sent" if success else "failed",
                error=error if error else None,
            )

        sent_count = sum(1 for _, s, _ in results if s)
        logger.info("Notified %d/%d jobs via %s", sent_count, len(results), channel)

"""Discord webhook notifications with rich embeds."""

import logging
import sqlite3

from discord_webhook import DiscordWebhook, DiscordEmbed

logger = logging.getLogger(__name__)


def _score_color(score: float) -> str:
    """Return hex color based on score — green/yellow/red."""
    if score >= 0.7:
        return "2ecc71"  # Green
    elif score >= 0.4:
        return "f39c12"  # Yellow/orange
    return "e74c3c"  # Red


class DiscordNotifier:
    """Sends job notifications to a Discord channel via webhook."""

    def __init__(self, config: dict):
        discord_cfg = config.get("notifications", {}).get("discord", {})
        self.webhook_url = discord_cfg.get("webhook_url", "")
        self.enabled = discord_cfg.get("enabled", False) and bool(self.webhook_url)
        self.min_score = discord_cfg.get("min_score", 0.6)

    def is_available(self) -> bool:
        return self.enabled

    def send_jobs(self, jobs: list[sqlite3.Row]) -> list[tuple[int, bool, str]]:
        """Send job notifications as Discord embeds.

        Returns list of (job_id, success, error_message).
        """
        if not self.enabled:
            return []

        results = []

        # Discord allows up to 10 embeds per message — batch accordingly
        batches = [jobs[i:i + 10] for i in range(0, len(jobs), 10)]

        for batch in batches:
            webhook = DiscordWebhook(
                url=self.webhook_url,
                content="**New matching jobs found!**" if len(batches) <= 1 else None,
            )

            for job in batch:
                score = job["combined_score"] or 0
                embed = DiscordEmbed(
                    title=f"{job['title']} @ {job['company']}",
                    url=job["url"],
                    color=_score_color(score),
                )
                embed.add_embed_field(name="Score", value=f"{score:.0%}", inline=True)
                embed.add_embed_field(
                    name="Location",
                    value=job["location"] or ("Remote" if job["is_remote"] else "N/A"),
                    inline=True,
                )
                embed.add_embed_field(name="Source", value=job["source"], inline=True)

                webhook.add_embed(embed)

            try:
                response = webhook.execute()
                success = response.status_code in (200, 204) if response else False
                for job in batch:
                    results.append((job["id"], success, "" if success else "Webhook failed"))
            except Exception as e:
                logger.exception("Discord webhook error")
                for job in batch:
                    results.append((job["id"], False, str(e)))

        return results

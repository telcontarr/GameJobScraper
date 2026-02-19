"""Email notifications via SMTP."""

import logging
import smtplib
import sqlite3
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


class EmailNotifier:
    """Sends job digest emails via SMTP."""

    def __init__(self, config: dict):
        email_cfg = config.get("notifications", {}).get("email", {})
        self.enabled = email_cfg.get("enabled", False)
        self.smtp_host = email_cfg.get("smtp_host", "smtp.gmail.com")
        self.smtp_port = email_cfg.get("smtp_port", 587)
        self.smtp_use_tls = email_cfg.get("smtp_use_tls", True)
        self.smtp_username = email_cfg.get("smtp_username", "")
        self.smtp_password = email_cfg.get("smtp_password", "")
        self.from_address = email_cfg.get("from_address", "")
        self.to_address = email_cfg.get("to_address", "")

        if self.enabled and not all([self.smtp_username, self.smtp_password, self.from_address, self.to_address]):
            logger.warning("Email notifications enabled but credentials incomplete")
            self.enabled = False

    def is_available(self) -> bool:
        return self.enabled

    def send_jobs(self, jobs: list[sqlite3.Row]) -> list[tuple[int, bool, str]]:
        """Send a digest email with all matching jobs.

        Returns list of (job_id, success, error_message).
        """
        if not self.enabled or not jobs:
            return []

        html_body = self._build_html(jobs)
        subject = f"GameJobTracker: {len(jobs)} new matching job(s)"

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.from_address
        msg["To"] = self.to_address

        # Plain text fallback
        text_body = self._build_text(jobs)
        msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                if self.smtp_use_tls:
                    server.starttls()
                server.login(self.smtp_username, self.smtp_password)
                server.sendmail(self.from_address, [self.to_address], msg.as_string())

            logger.info("Sent digest email with %d jobs to %s", len(jobs), self.to_address)
            return [(job["id"], True, "") for job in jobs]

        except Exception as e:
            logger.exception("Failed to send email")
            return [(job["id"], False, str(e)) for job in jobs]

    def _build_html(self, jobs: list[sqlite3.Row]) -> str:
        cards = []
        for job in jobs:
            score = job["combined_score"] or 0
            color = "#2ecc71" if score >= 0.7 else "#f39c12" if score >= 0.4 else "#e74c3c"
            location = job["location"] or ("Remote" if job["is_remote"] else "N/A")

            cards.append(f"""
            <div style="border:1px solid #ddd; border-left:4px solid {color}; padding:12px; margin:8px 0; border-radius:4px;">
                <h3 style="margin:0 0 4px 0;">
                    <a href="{job['url']}" style="color:#2c3e50; text-decoration:none;">{job['title']}</a>
                </h3>
                <p style="margin:0 0 8px 0; color:#7f8c8d;">
                    {job['company']} &bull; {location} &bull; Score: {score:.0%}
                </p>
                <p style="margin:0; font-size:0.9em; color:#555;">
                    Source: {job['source']}
                    {(' &bull; ' + job['score_reasoning'][:150]) if job['score_reasoning'] else ''}
                </p>
            </div>""")

        return f"""
        <html>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width:600px; margin:0 auto;">
            <h2 style="color:#2c3e50;">New Job Matches</h2>
            <p>{len(jobs)} new job(s) matching your profile:</p>
            {''.join(cards)}
            <hr style="border:none; border-top:1px solid #eee; margin:20px 0;">
            <p style="font-size:0.8em; color:#95a5a6;">Sent by GameJobTracker</p>
        </body>
        </html>"""

    def _build_text(self, jobs: list[sqlite3.Row]) -> str:
        lines = [f"GameJobTracker: {len(jobs)} new matching job(s)\n"]
        for job in jobs:
            score = job["combined_score"] or 0
            location = job["location"] or ("Remote" if job["is_remote"] else "N/A")
            lines.append(
                f"- {job['title']} @ {job['company']} ({location}) "
                f"[{score:.0%}]\n  {job['url']}\n"
            )
        return "\n".join(lines)

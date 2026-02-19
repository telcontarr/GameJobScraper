"""CLI interface for GameJobTracker."""

import click

from gamejobtracker.config import load_config, DEFAULT_CONFIG_DIR, DEFAULT_DATA_DIR
from gamejobtracker.db.models import init_db
from gamejobtracker.db.repository import JobRepository
from gamejobtracker.utils.logging_config import setup_logging


def _get_repo(config: dict) -> JobRepository:
    conn = init_db(config["database"]["path"])
    return JobRepository(conn)


def _build_scraper_manager(config: dict, repo: JobRepository):
    from gamejobtracker.scrapers.scraper_manager import ScraperManager
    from gamejobtracker.scrapers.jsearch import JSearchScraper
    from gamejobtracker.scrapers.workwithindies import WorkWithIndiesScraper
    from gamejobtracker.scrapers.gamejobsco import GameJobsCoScraper
    from gamejobtracker.scrapers.hitmarker import HitmarkerScraper

    manager = ScraperManager(config, repo)
    manager.register(WorkWithIndiesScraper(config))
    manager.register(JSearchScraper(config))
    manager.register(GameJobsCoScraper(config))
    manager.register(HitmarkerScraper(config))
    return manager


def _build_scorer_manager(config: dict, repo: JobRepository):
    from gamejobtracker.scoring.scorer_manager import ScorerManager
    return ScorerManager(config, repo)


def _build_notification_manager(config: dict, repo: JobRepository):
    from gamejobtracker.notifications.notification_manager import NotificationManager
    return NotificationManager(config, repo)


@click.group()
@click.option("--config-dir", default=None, help="Path to config directory")
@click.pass_context
def cli(ctx, config_dir):
    """GameJobTracker - AI-powered game industry job tracker."""
    ctx.ensure_object(dict)
    config = load_config(config_dir)
    setup_logging(
        config.get("logging", {}).get("level", "INFO"),
        config.get("logging", {}).get("file"),
    )
    ctx.obj["config"] = config


@cli.command()
@click.pass_context
def init(ctx):
    """Initialize database and create default config files."""
    import shutil
    from pathlib import Path

    config = ctx.obj["config"]

    # Create config directory with templates
    config_dir = DEFAULT_CONFIG_DIR
    config_dir.mkdir(parents=True, exist_ok=True)

    config_yaml = config_dir / "config.yaml"
    if not config_yaml.exists():
        template = Path(__file__).parent.parent / "config" / "config.yaml"
        if template.exists():
            shutil.copy(template, config_yaml)
            click.echo(f"Created {config_yaml}")
        else:
            click.echo(f"Config template not found — create {config_yaml} manually")

    profile_yaml = config_dir / "profile.yaml"
    if not profile_yaml.exists():
        template = Path(__file__).parent.parent / "config" / "profile.yaml"
        if template.exists():
            shutil.copy(template, profile_yaml)
            click.echo(f"Created {profile_yaml}")

    env_example = config_dir.parent / ".env.example"
    env_file = config_dir.parent / ".env"
    if not env_file.exists() and env_example.exists():
        shutil.copy(env_example, env_file)
        click.echo(f"Created {env_file} — fill in your API keys")

    # Init database
    db_path = config["database"]["path"]
    init_db(db_path)
    click.echo(f"Database initialized at {db_path}")
    click.echo("Setup complete! Edit config/config.yaml and .env to configure.")


@cli.command()
@click.option("--source", type=click.Choice(["jsearch", "workwithindies", "gamejobsco", "hitmarker", "all"]), default="all")
@click.pass_context
def scrape(ctx, source):
    """Run scrapers to find new job listings."""
    config = ctx.obj["config"]
    repo = _get_repo(config)
    manager = _build_scraper_manager(config, repo)

    if source == "all":
        new_jobs = manager.run_all()
    else:
        new_jobs = manager.run_source(source)

    click.echo(f"Found {len(new_jobs)} new job(s)")
    for job_id, job in new_jobs[:10]:
        click.echo(f"  [{job.source}] {job.title} @ {job.company}")
    if len(new_jobs) > 10:
        click.echo(f"  ... and {len(new_jobs) - 10} more")


@cli.command()
@click.pass_context
def score(ctx):
    """Score all unscored jobs."""
    config = ctx.obj["config"]
    repo = _get_repo(config)
    scorer = _build_scorer_manager(config, repo)

    unscored = repo.get_unscored_jobs()
    if not unscored:
        click.echo("No unscored jobs found.")
        return

    click.echo(f"Scoring {len(unscored)} job(s)...")
    scorer.score_batch(unscored)
    click.echo("Done.")


@cli.command()
@click.pass_context
def notify(ctx):
    """Send notifications for high-scoring un-notified jobs."""
    config = ctx.obj["config"]
    repo = _get_repo(config)
    notifier = _build_notification_manager(config, repo)
    notifier.send_all()
    click.echo("Notifications sent.")


@cli.command("list-jobs")
@click.option("--min-score", default=0.0, type=float, help="Minimum combined score")
@click.option("--status", type=click.Choice(["new", "reviewed", "applied", "rejected", "saved"]), default=None)
@click.option("--source", default=None, help="Filter by source")
@click.option("--group", default=None, help="Filter by query group (e.g. priority, us_canada)")
@click.option("--limit", default=20, type=int, help="Max results")
@click.pass_context
def list_jobs(ctx, min_score, status, source, group, limit):
    """List tracked jobs with filters."""
    config = ctx.obj["config"]
    repo = _get_repo(config)
    jobs = repo.get_jobs(min_score=min_score, status=status, source=source, group=group, limit=limit)

    if not jobs:
        click.echo("No jobs found matching filters.")
        return

    for job in jobs:
        score_str = f"{job['combined_score']:.2f}" if job["combined_score"] is not None else "-.--"
        remote_tag = " [REMOTE]" if job["is_remote"] else ""
        group_tag = f" [{job['query_group']}]" if job["query_group"] else ""
        click.echo(
            f"  #{job['id']:>4}  [{score_str}]  {job['title']}"
            f" @ {job['company']}  ({job['source']}){remote_tag}"
            f"{group_tag}  [{job['user_status']}]"
        )

    click.echo(f"\n{len(jobs)} job(s) shown")


@cli.command("set-status")
@click.argument("job_id", type=int)
@click.argument("new_status", type=click.Choice(["reviewed", "applied", "rejected", "saved"]))
@click.option("--notes", default=None, help="Add notes")
@click.pass_context
def set_status(ctx, job_id, new_status, notes):
    """Update the status of a tracked job."""
    config = ctx.obj["config"]
    repo = _get_repo(config)

    job = repo.get_job_by_id(job_id)
    if not job:
        click.echo(f"Job #{job_id} not found.")
        return

    repo.set_user_status(job_id, new_status, notes)
    click.echo(f"Job #{job_id} status updated to '{new_status}'")


@cli.command()
@click.pass_context
def stats(ctx):
    """Show tracker statistics."""
    config = ctx.obj["config"]
    repo = _get_repo(config)
    s = repo.get_stats()

    click.echo("=== GameJobTracker Stats ===")
    click.echo(f"  Total jobs:     {s['total']}")
    click.echo(f"  Active:         {s['active']}")
    click.echo(f"  Scored:         {s['scored']}")
    click.echo(f"  High matches:   {s['high_matches']} (score >= 0.7)")
    click.echo(f"  Avg score:      {s['avg_score']}")
    click.echo()
    click.echo("  By source:")
    for src, cnt in s["by_source"].items():
        click.echo(f"    {src}: {cnt}")
    click.echo()
    click.echo("  By status:")
    for status, cnt in s["by_status"].items():
        click.echo(f"    {status}: {cnt}")


@cli.command()
@click.pass_context
def run(ctx):
    """Start the scheduler daemon (runs scrape/score/notify pipeline on interval)."""
    from gamejobtracker.scheduler.job_scheduler import start_scheduler

    config = ctx.obj["config"]
    click.echo("Starting GameJobTracker scheduler... (Ctrl+C to stop)")
    start_scheduler(config)

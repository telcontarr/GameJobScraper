"""Configuration loader — merges YAML settings with .env secrets."""

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv


DEFAULT_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base."""
    merged = base.copy()
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(config_dir: str | Path | None = None) -> dict:
    """Load configuration from YAML files and environment variables.

    Returns a merged config dict with all settings + secrets.
    """
    config_dir = Path(config_dir) if config_dir else DEFAULT_CONFIG_DIR

    # Load .env from config dir or project root
    # Use override=True so .env values take precedence over any empty
    # system environment variables
    for env_path in [config_dir / ".env", config_dir.parent / ".env"]:
        if env_path.exists():
            load_dotenv(env_path, override=True)
            break

    # Load main config
    config_path = config_dir / "config.yaml"
    if config_path.exists():
        with open(config_path, "r") as f:
            config = yaml.safe_load(f) or {}
    else:
        config = {}

    # Load profile
    profile_path = config_dir / "profile.yaml"
    if profile_path.exists():
        with open(profile_path, "r") as f:
            config["profile"] = yaml.safe_load(f) or {}

    # Inject environment secrets
    config.setdefault("api_keys", {})
    config["api_keys"]["rapidapi"] = os.getenv("RAPIDAPI_KEY", "")
    config["api_keys"]["anthropic"] = os.getenv("ANTHROPIC_API_KEY", "")

    config.setdefault("notifications", {})
    config["notifications"].setdefault("email", {})
    config["notifications"]["email"]["smtp_username"] = os.getenv("SMTP_USERNAME", "")
    config["notifications"]["email"]["smtp_password"] = os.getenv("SMTP_PASSWORD", "")
    config["notifications"]["email"]["from_address"] = os.getenv(
        "EMAIL_FROM", config["notifications"]["email"].get("from_address", "")
    )
    config["notifications"]["email"]["to_address"] = os.getenv(
        "EMAIL_TO", config["notifications"]["email"].get("to_address", "")
    )

    config["notifications"].setdefault("discord", {})
    config["notifications"]["discord"]["webhook_url"] = os.getenv(
        "DISCORD_WEBHOOK_URL", ""
    )

    # Ensure data dir exists
    data_dir = Path(config.get("database", {}).get("path", DEFAULT_DATA_DIR / "gamejobtracker.db")).parent
    data_dir.mkdir(parents=True, exist_ok=True)

    # Set default database path
    config.setdefault("database", {})
    config["database"].setdefault("path", str(DEFAULT_DATA_DIR / "gamejobtracker.db"))

    return config

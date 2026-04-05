import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass
class Config:
    # Slack
    slack_bot_token: str
    slack_app_token: str
    slack_summary_channel_id: str

    # Anthropic
    anthropic_api_key: str

    # Gmail
    gmail_credentials_path: str
    gmail_token_path: str

    # Storage
    db_path: str


def load_config() -> Config:
    """Load configuration from environment variables.

    Reads from .env file if present, then validates all required
    values are set.
    """
    load_dotenv()

    required = {
        "SLACK_BOT_TOKEN": "Slack bot token (xoxb-...)",
        "SLACK_APP_TOKEN": "Slack app-level token (xapp-...)",
        "ANTHROPIC_API_KEY": "Anthropic API key",
    }

    missing = [
        f"  {key}: {desc}"
        for key, desc in required.items()
        if not os.environ.get(key)
    ]
    if missing:
        raise EnvironmentError(
            "Missing required environment variables:\n" + "\n".join(missing)
            + "\n\nCopy .env.example to .env and fill in the values."
        )

    return Config(
        slack_bot_token=os.environ["SLACK_BOT_TOKEN"],
        slack_app_token=os.environ["SLACK_APP_TOKEN"],
        slack_summary_channel_id=os.environ.get("SLACK_SUMMARY_CHANNEL_ID", ""),
        anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
        gmail_credentials_path=os.environ.get(
            "GMAIL_CREDENTIALS_PATH", "data/gmail_credentials.json"
        ),
        gmail_token_path=os.environ.get(
            "GMAIL_TOKEN_PATH", "data/gmail_token.json"
        ),
        db_path=os.environ.get("DB_PATH", "data/casa_mkali.db"),
    )

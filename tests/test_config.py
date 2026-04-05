import os
from unittest.mock import patch

import pytest

from src.config import load_config


class TestConfig:
    def test_load_config_with_all_vars(self):
        env = {
            "SLACK_BOT_TOKEN": "xoxb-test",
            "SLACK_APP_TOKEN": "xapp-test",
            "SLACK_UPDATE_CHANNEL_ID": "C123",
            "ANTHROPIC_API_KEY": "sk-ant-test",
            "GMAIL_CREDENTIALS_PATH": "test/creds.json",
            "GMAIL_TOKEN_PATH": "test/token.json",
            "GMAIL_POLL_INTERVAL_SECONDS": "30",
            "DB_PATH": "test/test.db",
        }
        with patch.dict(os.environ, env, clear=True):
            config = load_config()

        assert config.slack_bot_token == "xoxb-test"
        assert config.slack_app_token == "xapp-test"
        assert config.anthropic_api_key == "sk-ant-test"
        assert config.gmail_poll_interval_seconds == 30
        assert config.db_path == "test/test.db"

    def test_load_config_uses_defaults(self):
        env = {
            "SLACK_BOT_TOKEN": "xoxb-test",
            "SLACK_APP_TOKEN": "xapp-test",
            "SLACK_UPDATE_CHANNEL_ID": "C123",
            "ANTHROPIC_API_KEY": "sk-ant-test",
        }
        with patch.dict(os.environ, env, clear=True):
            config = load_config()

        assert config.gmail_credentials_path == "data/gmail_credentials.json"
        assert config.gmail_token_path == "data/gmail_token.json"
        assert config.gmail_poll_interval_seconds == 60
        assert config.db_path == "data/casa_mkali.db"

    def test_load_config_missing_required(self):
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(EnvironmentError, match="Missing required"):
                load_config()

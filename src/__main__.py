"""CM Secure Assistant — Casa Mkali Slack knowledge assistant.

Run with: python -m src
"""
import logging

from src.orchestrator import Orchestrator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
# Quiet noisy libraries
logging.getLogger("slack_bolt").setLevel(logging.WARNING)
logging.getLogger("slack_sdk").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

if __name__ == "__main__":
    orchestrator = Orchestrator()
    orchestrator.run()

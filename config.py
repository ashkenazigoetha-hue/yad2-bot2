"""
Configuration – reads from .env file
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


class Config:
    TELEGRAM_TOKEN: str = os.getenv("TELEGRAM_TOKEN", "")
    POLL_INTERVAL_MINUTES: int = int(os.getenv("POLL_INTERVAL_MINUTES", "15"))
    DATA_DIR: str = os.getenv("DATA_DIR", "data")

    def __post_init__(self):
        if not self.TELEGRAM_TOKEN:
            raise ValueError("TELEGRAM_TOKEN must be set in .env")

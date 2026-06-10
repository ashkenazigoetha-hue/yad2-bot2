"""
Configuration – reads from .env file
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


class Config:
    def __init__(self):
        self.TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
        self.POLL_INTERVAL_MINUTES = int(os.getenv("POLL_INTERVAL_MINUTES", "15"))
        self.DATA_DIR = os.getenv("DATA_DIR", "data")
        if not self.TELEGRAM_TOKEN:
            raise ValueError("TELEGRAM_TOKEN must be set in .env")
        if not os.getenv("SUPABASE_SERVICE_KEY"):
            import logging
            logging.getLogger(__name__).warning("⚠️ SUPABASE_SERVICE_KEY not set – bot will not be able to read searches")

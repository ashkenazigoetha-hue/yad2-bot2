"""
SearchManager – persists user searches and seen listing IDs to disk (JSON).
"""

import json
import logging
import uuid
from pathlib import Path
from typing import Dict, List

logger = logging.getLogger(__name__)


class SearchManager:
    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "searches.json"
        self._db: Dict = self._load()

    # ── Persistence ────────────────────────────────────────────────────────────
    def _load(self) -> dict:
        if self.db_path.exists():
            try:
                with open(self.db_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load DB: {e}")
        return {}

    def _save(self):
        try:
            with open(self.db_path, "w", encoding="utf-8") as f:
                json.dump(self._db, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save DB: {e}")

    # ── User helpers ───────────────────────────────────────────────────────────
    def _ensure_user(self, user_id: str):
        if user_id not in self._db:
            self._db[user_id] = {}

    def get_all_users(self) -> List[str]:
        return list(self._db.keys())

    # ── Search CRUD ────────────────────────────────────────────────────────────
    def add_search(self, user_id: str, search: dict) -> str:
        self._ensure_user(user_id)
        sid = str(uuid.uuid4())[:8]
        self._db[user_id][sid] = {**search, "seen_ids": []}
        self._save()
        logger.info(f"Added search '{search.get('name')}' for user {user_id} → {sid}")
        return sid

    def get_searches(self, user_id: str) -> Dict[str, dict]:
        return self._db.get(user_id, {})

    def delete_search(self, user_id: str, search_id: str):
        if user_id in self._db and search_id in self._db[user_id]:
            del self._db[user_id][search_id]
            self._save()

    def delete_all_searches(self, user_id: str) -> int:
        count = len(self._db.get(user_id, {}))
        self._db[user_id] = {}
        self._save()
        return count

    # ── Seen IDs ───────────────────────────────────────────────────────────────
    def get_seen_ids(self, user_id: str, search_id: str) -> List[str]:
        return self._db.get(user_id, {}).get(search_id, {}).get("seen_ids", [])

    def mark_seen(self, user_id: str, search_id: str, ids: List[str]):
        self._ensure_user(user_id)
        if search_id not in self._db[user_id]:
            return
        current = set(self._db[user_id][search_id].get("seen_ids", []))
        current.update(ids)
        # Keep last 2000 to avoid unbounded growth
        self._db[user_id][search_id]["seen_ids"] = list(current)[-2000:]
        self._save()

"""
SearchManager – persists searches to PostgreSQL (if DATABASE_URL set) or JSON file.
"""

import json
import logging
import os
import threading
import uuid
from pathlib import Path
from typing import Dict, List

logger = logging.getLogger(__name__)


class SearchManager:
    def __init__(self, data_dir: str):
        raw_url = os.getenv("DATABASE_URL", "")
        # Railway uses postgres:// but psycopg2 needs postgresql://
        self._db_url = raw_url.replace("postgres://", "postgresql://", 1) if raw_url else ""
        self._local = threading.local()

        if self._db_url:
            self._mode = "postgres"
            self._init_schema()
            logger.info("SearchManager: using PostgreSQL")
        else:
            self._mode = "file"
            self._data_dir = Path(data_dir)
            self._data_dir.mkdir(parents=True, exist_ok=True)
            self._db_path = self._data_dir / "searches.json"
            self._db: Dict = self._load()
            logger.info(f"SearchManager: using file at {self._db_path}")

    # ── PostgreSQL helpers ─────────────────────────────────────────────────────

    def _conn(self):
        import psycopg2
        if not hasattr(self._local, "conn") or self._local.conn.closed:
            self._local.conn = psycopg2.connect(self._db_url)
        return self._local.conn

    def _init_schema(self):
        conn = self._conn()
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS searches (
                    user_id   TEXT NOT NULL,
                    search_id TEXT NOT NULL,
                    data      TEXT NOT NULL,
                    PRIMARY KEY (user_id, search_id)
                )
            """)
        conn.commit()

    # ── File helpers ───────────────────────────────────────────────────────────

    def _load(self) -> dict:
        if self._db_path.exists():
            try:
                with open(self._db_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load DB: {e}")
        return {}

    def _save(self):
        try:
            with open(self._db_path, "w", encoding="utf-8") as f:
                json.dump(self._db, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save DB: {e}")

    # ── User helpers ───────────────────────────────────────────────────────────

    def get_all_users(self) -> List[str]:
        if self._mode == "postgres":
            conn = self._conn()
            with conn.cursor() as cur:
                cur.execute("SELECT DISTINCT user_id FROM searches")
                return [row[0] for row in cur.fetchall()]
        return list(self._db.keys())

    # ── Search CRUD ────────────────────────────────────────────────────────────

    def add_search(self, user_id: str, search: dict) -> str:
        sid = str(uuid.uuid4())[:8]
        data = {**search, "seen_ids": []}
        if self._mode == "postgres":
            conn = self._conn()
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO searches (user_id, search_id, data) VALUES (%s, %s, %s)",
                    (user_id, sid, json.dumps(data, ensure_ascii=False)),
                )
            conn.commit()
        else:
            if user_id not in self._db:
                self._db[user_id] = {}
            self._db[user_id][sid] = data
            self._save()
        logger.info(f"Added search '{search.get('name')}' for user {user_id} → {sid}")
        return sid

    def get_searches(self, user_id: str) -> Dict[str, dict]:
        if self._mode == "postgres":
            conn = self._conn()
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT search_id, data FROM searches WHERE user_id = %s",
                    (user_id,),
                )
                return {row[0]: json.loads(row[1]) for row in cur.fetchall()}
        return self._db.get(user_id, {})

    def delete_search(self, user_id: str, search_id: str):
        if self._mode == "postgres":
            conn = self._conn()
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM searches WHERE user_id = %s AND search_id = %s",
                    (user_id, search_id),
                )
            conn.commit()
        else:
            if user_id in self._db and search_id in self._db[user_id]:
                del self._db[user_id][search_id]
                self._save()

    def delete_all_searches(self, user_id: str) -> int:
        if self._mode == "postgres":
            conn = self._conn()
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM searches WHERE user_id = %s", (user_id,))
                count = cur.fetchone()[0]
                cur.execute("DELETE FROM searches WHERE user_id = %s", (user_id,))
            conn.commit()
            return count
        count = len(self._db.get(user_id, {}))
        self._db[user_id] = {}
        self._save()
        return count

    # ── Seen IDs ───────────────────────────────────────────────────────────────

    def get_seen_ids(self, user_id: str, search_id: str) -> List[str]:
        if self._mode == "postgres":
            conn = self._conn()
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT data FROM searches WHERE user_id = %s AND search_id = %s",
                    (user_id, search_id),
                )
                row = cur.fetchone()
                if row:
                    return json.loads(row[0]).get("seen_ids", [])
            return []
        return self._db.get(user_id, {}).get(search_id, {}).get("seen_ids", [])

    def mark_seen(self, user_id: str, search_id: str, ids: List[str]):
        if self._mode == "postgres":
            conn = self._conn()
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT data FROM searches WHERE user_id = %s AND search_id = %s",
                    (user_id, search_id),
                )
                row = cur.fetchone()
                if row:
                    data = json.loads(row[0])
                    current = set(data.get("seen_ids", []))
                    current.update(ids)
                    data["seen_ids"] = list(current)[-2000:]
                    cur.execute(
                        "UPDATE searches SET data = %s WHERE user_id = %s AND search_id = %s",
                        (json.dumps(data, ensure_ascii=False), user_id, search_id),
                    )
            conn.commit()
        else:
            if user_id not in self._db or search_id not in self._db[user_id]:
                return
            current = set(self._db[user_id][search_id].get("seen_ids", []))
            current.update(ids)
            self._db[user_id][search_id]["seen_ids"] = list(current)[-2000:]
            self._save()

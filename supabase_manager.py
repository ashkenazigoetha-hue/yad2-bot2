"""
SupabaseManager – reads/writes searches and profiles from Supabase.
"""

from __future__ import annotations
import logging
import os
import httpx

logger = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://exydxtitrmqulahfomxj.supabase.co")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")


def _headers():
    return {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def _get(path: str, params: dict = None) -> list:
    r = httpx.get(f"{SUPABASE_URL}/rest/v1/{path}", headers=_headers(), params=params, timeout=10)
    r.raise_for_status()
    return r.json()


def _patch(path: str, params: dict, body: dict) -> list:
    r = httpx.patch(f"{SUPABASE_URL}/rest/v1/{path}", headers=_headers(), params=params, json=body, timeout=10)
    r.raise_for_status()
    return r.json()


class SupabaseManager:
    # ── Profile / linking ─────────────────────────────────────────────────────

    def link_email(self, chat_id: str, email: str) -> bool:
        rows = _get("profiles", {"email": f"eq.{email}", "select": "id,email"})
        if not rows:
            return False
        profile_id = rows[0]["id"]
        _patch("profiles", {"id": f"eq.{profile_id}"}, {"telegram_chat_id": chat_id})
        logger.info(f"Linked chat_id={chat_id} to email={email} (profile={profile_id})")
        return True

    def get_profile_by_chat(self, chat_id: str) -> dict | None:
        rows = _get("profiles", {"telegram_chat_id": f"eq.{chat_id}", "select": "id,email,telegram_chat_id"})
        return rows[0] if rows else None

    def get_all_linked_profiles(self) -> list[dict]:
        return _get("profiles", {"telegram_chat_id": "not.is.null", "select": "id,telegram_chat_id"})

    # ── Searches ──────────────────────────────────────────────────────────────

    def get_searches(self, chat_id: str) -> list[dict]:
        profile = self.get_profile_by_chat(chat_id)
        if not profile:
            return []
        return _get("searches", {"user_id": f"eq.{profile['id']}", "select": "*"})

    def get_all_searches(self) -> list[tuple[str, dict]]:
        profiles = self.get_all_linked_profiles()
        result = []
        for p in profiles:
            searches = _get("searches", {"user_id": f"eq.{p['id']}", "select": "*"})
            for s in searches:
                result.append((p["telegram_chat_id"], s))
        return result

    # ── seen_ids + seen_prices ────────────────────────────────────────────────

    def get_seen_state(self, search_id: str) -> tuple[list[str] | None, dict]:
        """Single DB call — returns (seen_ids, seen_prices). seen_ids is None if never seeded."""
        rows = _get("searches", {"id": f"eq.{search_id}", "select": "seen_ids,seen_prices"})
        if not rows:
            return None, {}
        return rows[0].get("seen_ids"), (rows[0].get("seen_prices") or {})

    def get_seen_ids(self, search_id: str) -> list[str]:
        ids, _ = self.get_seen_state(search_id)
        return ids or []

    def get_searches_by_email(self, email: str) -> tuple[dict | None, list[dict]]:
        rows = _get("profiles", {"email": f"eq.{email}", "select": "id,email,telegram_chat_id"})
        if not rows:
            return None, []
        profile = rows[0]
        searches = _get("searches", {"user_id": f"eq.{profile['id']}", "select": "*"})
        return profile, searches

    def reset_seen_ids(self, search_id: str):
        _patch("searches", {"id": f"eq.{search_id}"}, {"seen_ids": None, "seen_prices": None})

    def mark_seen(self, search_id: str, new_ids: list[str], current: list[str] = None,
                  price_map: dict = None, current_prices: dict = None, force_write: bool = False):
        if not new_ids and not price_map and not force_write:
            return
        if current is None:
            current_ids, current_prices_fetched = self.get_seen_state(search_id)
            current = current_ids or []
            if current_prices is None:
                current_prices = current_prices_fetched
        elif current_prices is None:
            # current provided but current_prices omitted — fetch to avoid wiping seen_prices
            _, current_prices = self.get_seen_state(search_id)

        seen_set = set(current)
        merged = list(current)
        for nid in new_ids:
            if nid not in seen_set:
                merged.append(nid)
                seen_set.add(nid)
        trimmed = merged[-5000:]

        body: dict = {"seen_ids": trimmed}
        if price_map is not None:
            active = set(trimmed)
            merged_prices = {k: v for k, v in (current_prices or {}).items() if k in active}
            merged_prices.update({k: v for k, v in price_map.items() if k in active})
            body["seen_prices"] = merged_prices

        _patch("searches", {"id": f"eq.{search_id}"}, body)
        logger.debug(f"mark_seen {search_id}: {len(current)} → {len(trimmed)} ids")

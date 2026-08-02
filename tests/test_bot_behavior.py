import importlib
import os
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch


def _install_dependency_stubs():
    """Allow logic tests to run without installing the production integrations."""
    dotenv = types.ModuleType("dotenv")
    dotenv.load_dotenv = lambda: None
    sys.modules.setdefault("dotenv", dotenv)

    httpx = types.ModuleType("httpx")
    httpx.get = lambda *args, **kwargs: None
    httpx.patch = lambda *args, **kwargs: None
    sys.modules.setdefault("httpx", httpx)

    telegram = types.ModuleType("telegram")

    class ValueObject:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    telegram.Update = object
    telegram.InlineKeyboardButton = ValueObject
    telegram.InlineKeyboardMarkup = ValueObject
    telegram.BotCommand = ValueObject
    sys.modules.setdefault("telegram", telegram)

    telegram_error = types.ModuleType("telegram.error")
    telegram_error.Conflict = type("Conflict", (Exception,), {})
    sys.modules.setdefault("telegram.error", telegram_error)

    telegram_ext = types.ModuleType("telegram.ext")
    telegram_ext.Application = object
    telegram_ext.CommandHandler = object
    telegram_ext.CallbackQueryHandler = object
    telegram_ext.MessageHandler = object
    telegram_ext.filters = types.SimpleNamespace(TEXT=object(), COMMAND=object())
    telegram_ext.ContextTypes = types.SimpleNamespace(DEFAULT_TYPE=object)
    sys.modules.setdefault("telegram.ext", telegram_ext)

    curl_cffi = types.ModuleType("curl_cffi")
    curl_requests = types.ModuleType("curl_cffi.requests")
    curl_requests.AsyncSession = object
    curl_cffi.requests = curl_requests
    sys.modules.setdefault("curl_cffi", curl_cffi)
    sys.modules.setdefault("curl_cffi.requests", curl_requests)

    api = types.ModuleType("api")
    api.set_bot = lambda **kwargs: None
    api.start_api_thread = lambda *args, **kwargs: None
    sys.modules.setdefault("api", api)


os.environ.setdefault("TELEGRAM_TOKEN", "test-token")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-key")
_install_dependency_stubs()
bot_module = importlib.import_module("bot")
supabase_module = importlib.import_module("supabase_manager")


class FakeStore:
    def __init__(self, seen_ids, seen_prices=None):
        self.state = (seen_ids, seen_prices or {})
        self.mark_calls = []
        self.status_calls = []

    def get_seen_state(self, _search_id):
        return self.state

    def mark_seen(self, *args):
        self.mark_calls.append(args)

    def update_search_status(self, *args):
        self.status_calls.append(args)


class FakeScraper:
    consecutive_failures = 0

    def __init__(self, listings):
        self.listings = listings

    async def fetch_listings(self, _search, seen_ids=None):
        return [dict(item) for item in self.listings], True

    def _is_recent(self, _value):
        return True

    async def enrich_with_km(self, listings):
        return listings


class BotBehaviorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        bot_module._fetch_locks.clear()
        bot_module._poll_sem = None

    async def test_first_run_silently_seeds_every_existing_listing(self):
        listings = [
            {"id": "old-1", "price": 100, "listing_date": "2026-08-01"},
            {"id": "old-2", "price": 200, "listing_date": "2026-08-01"},
        ]
        store = FakeStore(None)
        with patch.object(bot_module, "sb", store), patch.object(
            bot_module, "scraper", FakeScraper(listings)
        ):
            result, first_run, pending_ids = await bot_module._fetch_new({"id": "search-1"})

        self.assertEqual(result, [])
        self.assertTrue(first_run)
        self.assertEqual(pending_ids, [])
        self.assertEqual(store.mark_calls[0][1], ["old-1", "old-2"])

    async def test_items_over_batch_limit_remain_pending(self):
        listings = [
            {"id": f"new-{i}", "price": i, "listing_date": "2026-08-02"}
            for i in range(16)
        ]
        store = FakeStore([])
        with patch.object(bot_module, "sb", store), patch.object(
            bot_module, "scraper", FakeScraper(listings)
        ):
            result, _, _ = await bot_module._fetch_new({"id": "search-2"})

        self.assertEqual(len(result), 15)
        ids_marked_before_delivery = {
            listing_id
            for call in store.mark_calls
            for listing_id in call[1]
        }
        self.assertNotIn("new-15", ids_marked_before_delivery)

    async def test_final_telegram_failure_is_not_hidden(self):
        telegram_bot = types.SimpleNamespace(send_message=AsyncMock(side_effect=RuntimeError("offline")))
        listing = {"id": "new-1", "url": "https://example.test/item/new-1"}

        with self.assertRaises(RuntimeError):
            await bot_module.send_listing(telegram_bot, 123, listing, "test")

    async def test_rich_listing_message_keeps_vehicle_details_and_actions(self):
        telegram_bot = types.SimpleNamespace(send_message=AsyncMock())
        listing = {
            "id": "new-2",
            "url": "https://example.test/item/new-2",
            "title": "טויוטה קורולה",
            "trim": "Comfort",
            "price": 82500,
            "year": 2021,
            "hand": 2,
            "km": 67000,
            "ownership": "פרטית",
            "engine_cc": 1800,
            "engine_type": "היברידי",
            "horsepower": 122,
            "test_date": "12/2026",
            "city": "חיפה",
            "features": "בקרת שיוט, מצלמת רוורס",
            "description": "שמור מאוד, ללא תאונות",
        }

        await bot_module.send_listing(
            telegram_bot, 123, listing, "קורולה למשפחה", "search-7"
        )

        text = telegram_bot.send_message.await_args.args[1]
        for expected in [
            "יד 2", "67,000", "פרטית", "1.8 ל׳", "היברידי", "122 כ\"ס",
            "טסט עד", "חיפה", "בקרת שיוט", "שמור מאוד", "קורולה למשפחה",
        ]:
            self.assertIn(expected, text)
        markup = telegram_bot.send_message.await_args.kwargs["reply_markup"]
        self.assertEqual(markup.args[0][1][0].kwargs["callback_data"], "pause_search-7")


class TelegramLinkTests(unittest.TestCase):
    def test_one_time_token_links_chat_and_is_cleared(self):
        token = "123e4567-e89b-12d3-a456-426614174000"
        expires = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
        patches = []

        with patch.object(
            supabase_module,
            "_get",
            return_value=[{"id": "profile-1", "email": "user@example.com", "telegram_link_expires_at": expires}],
        ), patch.object(
            supabase_module,
            "_patch",
            side_effect=lambda path, params, body: patches.append((path, params, body)) or [{}],
        ):
            linked = supabase_module.SupabaseManager().link_telegram_token("987", token)

        self.assertEqual(linked["id"], "profile-1")
        final_body = patches[-1][2]
        self.assertEqual(final_body["telegram_chat_id"], "987")
        self.assertIsNone(final_body["telegram_link_token"])

    def test_invalid_token_is_rejected_before_database_query(self):
        with patch.object(supabase_module, "_get") as get_mock:
            result = supabase_module.SupabaseManager().link_telegram_token("987", "not-a-token")
        self.assertIsNone(result)
        get_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()

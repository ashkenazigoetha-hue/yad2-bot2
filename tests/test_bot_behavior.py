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
    telegram_ext.TypeHandler = object
    telegram_ext.filters = types.SimpleNamespace(TEXT=object(), COMMAND=object())
    telegram_ext.ContextTypes = types.SimpleNamespace(DEFAULT_TYPE=object)
    sys.modules.setdefault("telegram.ext", telegram_ext)

    curl_cffi = types.ModuleType("curl_cffi")
    curl_requests = types.ModuleType("curl_cffi.requests")
    curl_requests.AsyncSession = object
    curl_cffi.requests = curl_requests
    sys.modules.setdefault("curl_cffi", curl_cffi)
    sys.modules.setdefault("curl_cffi.requests", curl_requests)

    playwright = types.ModuleType("playwright")
    playwright_async = types.ModuleType("playwright.async_api")
    playwright_async.async_playwright = lambda: None
    playwright.async_api = playwright_async
    sys.modules.setdefault("playwright", playwright)
    sys.modules.setdefault("playwright.async_api", playwright_async)

    playwright_stealth = types.ModuleType("playwright_stealth")
    playwright_stealth.Stealth = object
    sys.modules.setdefault("playwright_stealth", playwright_stealth)

    api = types.ModuleType("api")
    api.set_bot = lambda **kwargs: None
    api.start_api_thread = lambda *args, **kwargs: None
    sys.modules.setdefault("api", api)


os.environ.setdefault("TELEGRAM_TOKEN", "test-token")
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
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


class AccountAccessTests(unittest.TestCase):
    def test_blocked_profile_has_no_searches(self):
        manager = supabase_module.SupabaseManager()

        def fake_get(path, _params=None):
            if path == "profiles":
                return [{"id": "profile-1", "email": "user@example.com", "telegram_chat_id": "987"}]
            if path == "user_access":
                return [{"is_blocked": True, "blocked_reason": "test", "trial_ends_at": None, "access_exempt": False}]
            if path == "searches":
                self.fail("blocked accounts must not query searches")
            return []

        with patch.object(supabase_module, "_get", side_effect=fake_get):
            self.assertEqual(manager.get_searches("987"), [])

    def test_unlimited_profile_is_in_scheduled_scans(self):
        manager = supabase_module.SupabaseManager()

        def fake_get(path, params=None):
            if path == "profiles":
                return [{"id": "profile-1", "telegram_chat_id": "987"}]
            if path == "user_access":
                return [{"user_id": "profile-1", "is_blocked": False, "trial_ends_at": "2000-01-01T00:00:00+00:00", "access_exempt": True}]
            if path == "searches":
                return [{"id": "search-1", "is_active": True}]
            return []

        with patch.object(supabase_module, "_get", side_effect=fake_get):
            self.assertEqual(manager.get_all_searches(), [("987", {"id": "search-1", "is_active": True})])


class AdminCommandQueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_personal_message_job_targets_the_profile_chat(self):
        class Store:
            def get_profile_by_id(self, user_id):
                self.user_id = user_id
                return {"id": user_id, "telegram_chat_id": "987"}

        store = Store()
        telegram_bot = types.SimpleNamespace(send_message=AsyncMock())
        context = types.SimpleNamespace(bot=telegram_bot)
        job = {
            "job_type": "send_message",
            "target_user_id": "profile-1",
            "payload": {"message": "הודעת שירות"},
        }

        with patch.object(bot_module, "sb", store):
            result = await bot_module._execute_admin_job(context, job)

        self.assertEqual(store.user_id, "profile-1")
        self.assertEqual(result["sent"], 1)
        telegram_bot.send_message.assert_awaited_once_with(987, "הודעת שירות")

    async def test_reset_baseline_job_does_not_send_telegram(self):
        class Store:
            def __init__(self):
                self.reset = []

            def get_profile_by_id(self, user_id):
                return {"id": user_id, "telegram_chat_id": "987"}

            def get_search_by_id(self, search_id, user_id):
                return {"id": search_id, "user_id": user_id, "name": "test"}

            def reset_seen_ids(self, search_id):
                self.reset.append(search_id)

        store = Store()
        context = types.SimpleNamespace(bot=types.SimpleNamespace(send_message=AsyncMock()))
        job = {
            "job_type": "reset_baseline",
            "target_user_id": "profile-1",
            "target_search_id": "search-1",
            "payload": {},
        }

        with patch.object(bot_module, "sb", store):
            result = await bot_module._execute_admin_job(context, job)

        self.assertEqual(store.reset, ["search-1"])
        self.assertTrue(result["baseline_reset"])
        context.bot.send_message.assert_not_awaited()


class AdminQueuePersistenceTests(unittest.TestCase):
    def test_claim_uses_compare_and_set_on_queued_status(self):
        manager = supabase_module.SupabaseManager()
        patches = []
        with patch.object(supabase_module, "_get", return_value=[{"id": "job-1", "status": "queued"}]), patch.object(
            supabase_module,
            "_patch",
            side_effect=lambda path, params, body: patches.append((path, params, body)) or [{"id": "job-1", "status": "processing"}],
        ):
            claimed = manager.claim_next_admin_job()

        self.assertEqual(claimed["status"], "processing")
        self.assertEqual(patches[0][1]["status"], "eq.queued")


class ConversationLoggingTests(unittest.TestCase):
    def _chat(self, cid="123"):
        return types.SimpleNamespace(id=cid)

    def test_inbound_command_is_classified_and_link_token_redacted(self):
        update = types.SimpleNamespace(
            effective_chat=self._chat(),
            callback_query=None,
            message=types.SimpleNamespace(
                message_id=7, text="/start link_abc123DEF456ghi", caption=None,
                photo=None, voice=None, audio=None, video=None, video_note=None,
                document=None, animation=None, sticker=None, location=None, contact=None,
            ),
            edited_message=None,
        )
        info = bot_module._classify_inbound(update)
        self.assertEqual(info["message_type"], "command")
        self.assertEqual(info["direction"], "inbound")
        self.assertEqual(info["sender"], "user")
        self.assertIn("[redacted]", info["content"])
        self.assertNotIn("abc123DEF456ghi", info["content"])

    def test_inbound_photo_captures_safe_media_only(self):
        photo = types.SimpleNamespace(file_id="AgACfileID", file_unique_id="uq1", file_size=2048,
                                      width=800, height=600)
        update = types.SimpleNamespace(
            effective_chat=self._chat(),
            callback_query=None,
            message=types.SimpleNamespace(
                message_id=8, text=None, caption="רכב יפה", photo=[photo],
                voice=None, audio=None, video=None, video_note=None, document=None,
                animation=None, sticker=None, location=None, contact=None,
            ),
            edited_message=None,
        )
        info = bot_module._classify_inbound(update)
        self.assertEqual(info["message_type"], "photo")
        self.assertEqual(info["content"], "רכב יפה")
        self.assertEqual(info["media"]["file_id"], "AgACfileID")
        # No token or URL ever stored in media metadata.
        self.assertNotIn("token", info["media"])
        for value in info["media"].values():
            self.assertNotIn("http", str(value))

    def test_inbound_callback_button_is_logged(self):
        update = types.SimpleNamespace(
            effective_chat=self._chat(),
            callback_query=types.SimpleNamespace(data="chk_42", message=types.SimpleNamespace(message_id=9)),
            message=None,
            edited_message=None,
        )
        info = bot_module._classify_inbound(update)
        self.assertEqual(info["message_type"], "callback")
        self.assertIn("chk_42", info["content"])

    def test_outbound_defaults_to_bot_sender(self):
        captured = {}

        class Rec:
            def log_message(self, **kwargs):
                captured.update(kwargs)

        with patch.object(bot_module, "sb", Rec()):
            bot_module._record_outbound_sync("123", "text", "שלום", 11, "sent", None)
        self.assertEqual(captured["sender"], "bot")
        self.assertEqual(captured["direction"], "outbound")
        self.assertEqual(captured["delivery_status"], "sent")

    def test_admin_message_is_attributed_to_admin(self):
        captured = {}

        class Rec:
            def log_message(self, **kwargs):
                captured.update(kwargs)

        token = bot_module._send_attrib.set(
            {"sender": "admin", "admin_email": "ido.goetha5@gmail.com", "admin_user_id": "u-1"}
        )
        try:
            with patch.object(bot_module, "sb", Rec()):
                bot_module._record_outbound_sync("123", "text", "בדיקה", 12, "sent", None)
        finally:
            bot_module._send_attrib.reset(token)
        self.assertEqual(captured["sender"], "admin")
        self.assertEqual(captured["admin_email"], "ido.goetha5@gmail.com")

    def test_delivery_failure_is_recorded(self):
        captured = {}

        class Rec:
            def log_message(self, **kwargs):
                captured.update(kwargs)

        with patch.object(bot_module, "sb", Rec()):
            bot_module._record_outbound_sync("123", "text", "נכשל", None, "failed", "chat not found")
        self.assertEqual(captured["delivery_status"], "failed")
        self.assertEqual(captured["delivery_error"], "chat not found")

    def test_logging_failure_never_raises(self):
        class Boom:
            def log_message(self, **kwargs):
                raise RuntimeError("db down")

        with patch.object(bot_module, "sb", Boom()):
            # Must not raise — logging is best-effort.
            bot_module._record_outbound_sync("1", "text", "x", 1, "sent", None)
            bot_module._record_inbound_sync(
                {"chat_id": "1", "message_type": "text", "content": "x"}
            )


class EmailOutboxTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        os.environ["EMAIL_USER"] = "sender@gmail.com"
        os.environ["EMAIL_APP_PASSWORD"] = "app-pass"
        os.environ["ADMIN_ALERT_EMAILS"] = "ido.goetha5@gmail.com,erelash27@gmail.com"

    def _alert(self, attempts=0, max_attempts=8):
        return {"id": "a-1", "attempts": attempts, "max_attempts": max_attempts,
                "payload": {"user_id": "u-1", "email": "new@user.test"}}

    async def test_skips_without_burning_attempts_when_not_configured(self):
        os.environ.pop("EMAIL_APP_PASSWORD", None)
        touched = {"claimed": False}
        store = types.SimpleNamespace(
            get_due_email_alerts=lambda limit=10: (_ for _ in ()).throw(AssertionError("should not query")),
            claim_email_alert=lambda aid: touched.__setitem__("claimed", True),
        )
        with patch.object(bot_module, "sb", store):
            await bot_module.process_email_outbox(types.SimpleNamespace())
        self.assertFalse(touched["claimed"])

    async def test_successful_send_marks_sent(self):
        store = types.SimpleNamespace(
            get_due_email_alerts=lambda limit=10: [self._alert()],
            claim_email_alert=lambda aid: self._alert(),
            mark_email_sent=lambda aid, recips: setattr(store, "sent", (aid, recips)),
            mark_email_retry=lambda *a: setattr(store, "retried", a),
        )
        store.sent = None
        store.retried = None
        os.environ["ADMIN_ALERT_EMAILS"] = "ido.goetha5@gmail.com,erelash27@gmail.com"
        with patch.object(bot_module, "sb", store), patch.object(
            bot_module, "_send_new_user_email", lambda alert, recips: None
        ):
            await bot_module.process_email_outbox(types.SimpleNamespace())
        self.assertEqual(store.sent[0], "a-1")
        self.assertEqual(len(store.sent[1]), 2)
        self.assertIsNone(store.retried)

    async def test_failed_send_schedules_backoff_without_giving_up(self):
        store = types.SimpleNamespace(
            get_due_email_alerts=lambda limit=10: [self._alert()],
            claim_email_alert=lambda aid: self._alert(attempts=0),
            mark_email_sent=lambda aid, recips: setattr(store, "sent", True),
            mark_email_retry=lambda aid, attempts, error, nxt, exhausted: setattr(
                store, "retried", (attempts, exhausted)
            ),
        )
        store.sent = None
        store.retried = None
        os.environ["ADMIN_ALERT_EMAILS"] = "ido.goetha5@gmail.com"

        def boom(alert, recips):
            raise RuntimeError("smtp offline")

        with patch.object(bot_module, "sb", store), patch.object(
            bot_module, "_send_new_user_email", boom
        ):
            await bot_module.process_email_outbox(types.SimpleNamespace())
        self.assertIsNone(store.sent)
        self.assertEqual(store.retried, (1, False))  # attempt 1, not exhausted

    async def test_last_attempt_marks_failed(self):
        store = types.SimpleNamespace(
            get_due_email_alerts=lambda limit=10: [self._alert(attempts=7)],
            claim_email_alert=lambda aid: self._alert(attempts=7, max_attempts=8),
            mark_email_sent=lambda aid, recips: None,
            mark_email_retry=lambda aid, attempts, error, nxt, exhausted: setattr(
                store, "retried", (attempts, exhausted)
            ),
        )
        store.retried = None
        os.environ["ADMIN_ALERT_EMAILS"] = "ido.goetha5@gmail.com"
        with patch.object(bot_module, "sb", store), patch.object(
            bot_module, "_send_new_user_email", lambda a, r: (_ for _ in ()).throw(RuntimeError("x"))
        ):
            await bot_module.process_email_outbox(types.SimpleNamespace())
        self.assertEqual(store.retried, (8, True))  # attempt 8 of 8 -> exhausted


if __name__ == "__main__":
    unittest.main()

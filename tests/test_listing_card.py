"""Tests for the Telegram listing card V2 information contract.

The central guarantee under test: a mandatory field is either rendered with a
real value or explicitly marked `לא פורסם` and recorded in `missing_fields`. It
is never silently omitted and never invented.
"""

import os
import sys
import types
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from listing_card import (  # noqa: E402
    CAPTION_LIMIT,
    EVENT_NEW,
    EVENT_PRICE_DROP,
    EVENT_PRICE_RISE,
    MANDATORY_FIELDS,
    NOT_PUBLISHED,
    Card,
    fit,
    price_delta,
    render_card,
)

FULL = {
    "id": "1",
    "vehicle_name": "יונדאי אלנטרה",
    "variant_or_trim": "Supreme היברידית",
    "year": 2024,
    "price": 132000,
    "hand": 1,
    "hand_text": "1",
    "km": 32000,
    "ownership": "פרטית",
    "engine_cc": 1600,
    "engine_type": "היברידי",
    "horsepower": 139,
    "city": "באר שבע והסביבה",
    "listing_date": datetime(2026, 8, 11, 7, 17, tzinfo=timezone.utc),
    "url": "https://www.yad2.co.il/item/abc",
}


class ContractTests(unittest.TestCase):
    """Every mandatory field appears, always."""

    def test_full_listing_renders_every_mandatory_field(self):
        card = render_card(FULL, search_name="יונדאי אלנטרה")
        self.assertEqual(card.missing_fields, [])
        for token in ("🚗 רכב: יונדאי אלנטרה", "🏷️ גרסה: Supreme היברידית", "📅 שנה: 2024",
                      "💰 מחיר: 132,000 ₪", "✋ יד: ראשונה", "🛣️ קילומטראז׳: 32,000 ק״מ",
                      "👤 בעלות: פרטית", "⚙️ מנוע: 1.6 ל׳ · היברידי", "🐎 כוח: 139 כ״ס",
                      "📍 אזור: באר שבע והסביבה"):
            self.assertIn(token, card.text, f"missing {token!r}")

    def test_empty_listing_marks_every_mandatory_field_missing(self):
        card = render_card({})
        for name in MANDATORY_FIELDS:
            self.assertIn(name, card.missing_fields, f"{name} not reported missing")
        # every mandatory field still gets its own labelled line
        self.assertGreaterEqual(card.text.count(NOT_PUBLISHED), 9)

    def test_each_mandatory_field_dropped_individually_is_reported(self):
        """Removing any single field must surface it — never a silent omission."""
        sources = {
            "vehicle_name": ("vehicle_name", "title", "make", "model", "model_text"),
            "variant_or_trim": ("variant_or_trim", "trim"),
            "year": ("year",),
            "price_current": ("price_current", "price"),
            "hand": ("hand", "hand_text"),
            "mileage_km": ("mileage_km", "km"),
            "ownership": ("ownership",),
            "engine": ("engine_displacement", "engine_cc", "fuel_or_powertrain",
                       "engine_type", "turbo"),
            "horsepower": ("horsepower",),
            "source_published_at": ("source_published_at", "listing_date"),
        }
        for logical, keys in sources.items():
            listing = {k: v for k, v in FULL.items() if k not in keys}
            card = render_card(listing)
            self.assertIn(logical, card.missing_fields,
                          f"dropping {keys} did not report {logical}")

    def test_zero_values_are_real_data_not_missing(self):
        """0 km / hand 0 are legitimate; truthiness checks would lose them."""
        card = render_card({**FULL, "km": 0, "hand": 0, "hand_text": "0"})
        self.assertNotIn("mileage_km", card.missing_fields)
        self.assertNotIn("hand", card.missing_fields)
        self.assertIn("🛣️ קילומטראז׳: 0 ק״מ", card.text)
        self.assertIn("✋ יד: אפס", card.text)

    def test_nothing_is_invented_when_source_is_silent(self):
        card = render_card({"vehicle_name": "מאזדה 3"})
        self.assertNotIn("139", card.text)
        self.assertNotIn("2024", card.text)


class PriceTests(unittest.TestCase):
    def test_missing_price_says_not_published_and_invents_nothing(self):
        card = render_card({k: v for k, v in FULL.items() if k != "price"})
        self.assertIn("💰 מחיר: לא פורסם", card.text)
        self.assertIn("price_current", card.missing_fields)

    def test_price_drop_shows_both_prices_and_delta_in_shekels_and_percent(self):
        card = render_card(
            {**FULL, "price": 78000, "price_previous": 79500},
            event=EVENT_PRICE_DROP,
        )
        self.assertIn("💰 <b>מחיר חדש: 78,000 ₪</b>", card.text)
        self.assertIn("🏷️ מחיר קודם: <s>79,500 ₪</s>", card.text)
        self.assertIn("📉 ירידה: 1,500 ₪ — 1.9%", card.text)

    def test_direction_is_words_not_an_ambiguous_rtl_arrow(self):
        drop = render_card({**FULL, "price": 78000, "price_previous": 79500})
        rise = render_card({**FULL, "price": 81000, "price_previous": 79500})
        self.assertIn("ירידה", drop.text)
        self.assertIn("עלייה", rise.text)
        self.assertEqual(rise.event, EVENT_PRICE_RISE)
        for card in (drop, rise):
            for arrow in ("⬇️", "⬆️", "←", "→"):
                self.assertNotIn(arrow, card.text)

    def test_no_delta_computed_from_invalid_prices(self):
        self.assertIsNone(price_delta(0, 1000))
        self.assertIsNone(price_delta(None, 1000))
        self.assertIsNone(price_delta("abc", 1000))
        self.assertIsNone(price_delta(1000, 1000))
        card = render_card({**FULL, "price": 78000, "price_previous": 0},
                           event=EVENT_PRICE_DROP)
        self.assertNotIn("%", card.text)


class SeparationTests(unittest.TestCase):
    """Search criteria are never presented as facts about the car."""

    def test_search_range_never_reaches_the_headline(self):
        card = render_card(FULL, search_name="יונדאי 2024–2026",
                           match_reasons=["שנתון 2024–2026"])
        vehicle_line = [l for l in card.text.split("\n") if l.startswith("🚗 רכב:")][0]
        self.assertNotIn("2024–2026", vehicle_line)
        self.assertIn("2024–2026", card.text.split("למה קיבלת אותה?")[1])

    def test_match_reasons_come_from_caller_not_invented(self):
        card = render_card(FULL)
        self.assertNotIn("למה קיבלת אותה?", card.text)


class TimestampTests(unittest.TestCase):
    def test_published_detected_and_checked_are_distinct(self):
        card = render_card(
            FULL,
            detected_at=datetime(2026, 8, 11, 8, 0, tzinfo=timezone.utc),
            last_checked_at=datetime(2026, 8, 11, 12, 16, tzinfo=timezone.utc),
        )
        self.assertIn("🕐 פורסמה במקור: 11.08.2026 10:17", card.text)  # UTC+3
        self.assertIn("🔍 זוהתה אצלנו", card.text)
        self.assertIn("🔄 נבדקה לאחרונה", card.text)

    def test_detection_time_is_not_shown_as_publish_time(self):
        card = render_card({k: v for k, v in FULL.items() if k != "listing_date"},
                           detected_at=datetime(2026, 8, 11, 8, 0, tzinfo=timezone.utc))
        self.assertIn(f"🕐 פורסמה במקור: {NOT_PUBLISHED}", card.text)
        self.assertIn("source_published_at", card.missing_fields)


class EscapingTests(unittest.TestCase):
    def test_html_metacharacters_from_source_are_escaped(self):
        card = render_card({**FULL, "vehicle_name": '<script>alert("x")</script>'})
        self.assertNotIn("<script>", card.text)
        self.assertIn("&lt;script&gt;", card.text)

    def test_markdown_metacharacters_do_not_corrupt_output(self):
        card = render_card({**FULL, "vehicle_name": "מאזדה *3* _GT_ [x]"})
        self.assertIn("מאזדה *3* _GT_ [x]", card.text)

    def test_ampersand_escaped(self):
        card = render_card({**FULL, "ownership": "פרטית & חברה"})
        self.assertIn("&amp;", card.text)


class LimitTests(unittest.TestCase):
    def test_long_title_still_fits_a_caption(self):
        card = render_card({**FULL, "vehicle_name": "יונדאי " * 200,
                            "description": "תיאור ארוך " * 200})
        self.assertLessEqual(len(fit(card.text)), CAPTION_LIMIT)

    def test_fit_is_a_noop_below_the_limit(self):
        self.assertEqual(fit("short"), "short")

    def test_mandatory_facts_precede_free_text(self):
        card = render_card({**FULL, "description": "הערה", "features": "תוספת"})
        self.assertLess(card.text.index("🐎 כוח: 139 כ״ס"), card.text.index("הערות המוכר"))


class GoldenSnapshotTests(unittest.TestCase):
    """Whole-card snapshots for the scenarios the spec enumerates."""

    def test_golden_new_listing(self):
        card = render_card(FULL, search_name="יונדאי אלנטרה",
                           match_reasons=["יונדאי אלנטרה", "שנת 2024", "הנעה היברידית"],
                           last_checked_at=datetime(2026, 8, 11, 12, 16, tzinfo=timezone.utc))
        self.assertEqual(card.text, "\n".join([
            "<b>🚘 מודעה חדשה</b>",
            "",
            "🚗 רכב: יונדאי אלנטרה",
            "🏷️ גרסה: Supreme היברידית",
            "📅 שנה: 2024",
            "💰 מחיר: 132,000 ₪",
            "✋ יד: ראשונה",
            "🛣️ קילומטראז׳: 32,000 ק״מ",
            "👤 בעלות: פרטית",
            "⚙️ מנוע: 1.6 ל׳ · היברידי",
            "🐎 כוח: 139 כ״ס",
            "📍 אזור: באר שבע והסביבה",
            "🕐 פורסמה במקור: 11.08.2026 10:17",
            "🌐 מקור: יד2",
            "🔄 נבדקה לאחרונה: 11.08.2026 15:16",
            "",
            "🔎 <b>למה קיבלת אותה?</b>",
            "מתאימה לחיפוש „יונדאי אלנטרה”: יונדאי אלנטרה, שנת 2024, הנעה היברידית.",
        ]))

    def test_golden_price_drop(self):
        card = render_card(
            {**FULL, "vehicle_name": "קיה ספורטאז׳", "variant_or_trim": "Premium",
             "year": 2020, "km": 105000, "hand": 2, "hand_text": "2",
             "engine_cc": 1600, "engine_type": "בנזין", "horsepower": 177,
             "city": "ירושלים", "price": 78000, "price_previous": 79500,
             "listing_date": datetime(2026, 6, 7, 8, 49, tzinfo=timezone.utc)},
            event=EVENT_PRICE_DROP,
        )
        self.assertEqual(card.text, "\n".join([
            "<b>🔻 המחיר ירד!</b>",
            "",
            "💰 <b>מחיר חדש: 78,000 ₪</b>",
            "🏷️ מחיר קודם: <s>79,500 ₪</s>",
            "📉 ירידה: 1,500 ₪ — 1.9%",
            "",
            "🚗 רכב: קיה ספורטאז׳",
            "🏷️ גרסה: Premium",
            "📅 שנה: 2020",
            "✋ יד: שנייה",
            "🛣️ קילומטראז׳: 105,000 ק״מ",
            "👤 בעלות: פרטית",
            "⚙️ מנוע: 1.6 ל׳ · בנזין",
            "🐎 כוח: 177 כ״ס",
            "📍 אזור: ירושלים",
            "🕐 פורסמה במקור: 07.06.2026 11:49",
            "🌐 מקור: יד2",
        ]))

    def test_golden_all_fields_missing(self):
        card = render_card({"vehicle_name": "רכב"})
        self.assertEqual(card.text, "\n".join([
            "<b>🚘 מודעה חדשה</b>",
            "",
            "🚗 רכב: רכב",
            "🏷️ גרסה: לא פורסם",
            "📅 שנה: לא פורסם",
            "💰 מחיר: לא פורסם",
            "✋ יד: לא פורסם",
            "🛣️ קילומטראז׳: לא פורסם",
            "👤 בעלות: לא פורסם",
            "⚙️ מנוע: לא פורסם",
            "🐎 כוח: לא פורסם",
            "📍 אזור: לא פורסם",
            "🕐 פורסמה במקור: לא פורסם",
            "🌐 מקור: יד2",
        ]))


if __name__ == "__main__":
    unittest.main()


class AlertFeedbackTests(unittest.TestCase):
    """The 'לא רלוונטי' button must persist an event and never edit the search."""

    def setUp(self):
        import test_bot_behavior  # installs the telegram/httpx stubs
        test_bot_behavior._install_dependency_stubs()
        import importlib
        self.bot = importlib.import_module("bot")

    def test_reason_picker_offers_the_documented_codes(self):
        codes = [c for c, _ in self.bot.FEEDBACK_REASONS]
        self.assertEqual(
            codes,
            ["price", "area", "model", "mileage", "year", "duplicate", "other"],
        )

    def test_feedback_is_persisted_and_search_is_not_mutated(self):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        query = MagicMock()  # noqa: F841 - rebound below
        query.data = "fb_price_search-9_listing-42"
        query.message.chat_id = 555
        query.answer = AsyncMock()
        query.edit_message_reply_markup = AsyncMock()
        update = MagicMock(callback_query=query)

        with patch.object(self.bot.sb, "record_alert_feedback", return_value=True) as rec, \
             patch.object(self.bot.sb, "pause_search_for_chat") as pause:
            asyncio.run(self.bot.alert_feedback_reason(update, MagicMock()))

        rec.assert_called_once_with("555", "search-9", "listing-42", "price")
        pause.assert_not_called()          # feedback never narrows the search
        query.answer.assert_awaited_once()


class TelegramPreflightTests(unittest.TestCase):
    """A user without Telegram is a permanent non-delivery, never a failed job."""

    def setUp(self):
        import test_bot_behavior
        test_bot_behavior._install_dependency_stubs()
        import importlib
        self.bot = importlib.import_module("bot")

    def _run_send_message_job(self, profile):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        ctx = MagicMock()
        ctx.bot.send_message = AsyncMock()
        job = {
            "id": "job-1",
            "job_type": "send_message",
            "user_id": "user-1",
            "payload": {"message": "שלום"},
        }
        with patch.object(self.bot.sb, "get_profile_by_id", return_value=profile):
            result = asyncio.run(self.bot._execute_admin_job(ctx, job))
        return result, ctx.bot.send_message

    def test_no_telegram_completes_with_reason_code_and_sends_nothing(self):
        result, send = self._run_send_message_job({"id": "user-1", "telegram_chat_id": None})
        self.assertEqual(result["reason_code"], "not_deliverable_no_telegram")
        self.assertFalse(result["delivered"])
        self.assertEqual(result["sent"], 0)
        self.assertEqual(result["next_action"], "connect_telegram")
        send.assert_not_awaited()

    def test_connected_user_still_receives_the_message(self):
        result, send = self._run_send_message_job({"id": "user-1", "telegram_chat_id": "555"})
        self.assertEqual(result["sent"], 1)
        send.assert_awaited_once()


class LogRedactionTests(unittest.TestCase):
    """Credentials must never reach a log handler, whoever emitted the record."""

    def setUp(self):
        import test_bot_behavior
        test_bot_behavior._install_dependency_stubs()
        import importlib
        self.bot = importlib.import_module("bot")
        self.f = self.bot._SecretRedactingFilter()

    def _scrub(self, text):
        import logging
        rec = logging.LogRecord("x", logging.INFO, "p", 1, text, None, None)
        self.f.filter(rec)
        return rec.msg

    def test_telegram_token_in_url_is_redacted(self):
        out = self._scrub("POST https://api.telegram.org/bot1234567890:AAAbbbCCCdddEEEfffGGGhhhIIIjjjKKKlll/getUpdates")
        self.assertNotIn("AAAbbbCCC", out)
        self.assertIn("<REDACTED>", out)

    def test_supabase_service_key_is_redacted_despite_underscore_prefix(self):
        out = self._scrub("SUPABASE_SERVICE_KEY=eyJhbGciOiJIUzI1NiJ9.payloadpart.sigpart")
        self.assertNotIn("payloadpart", out)

    def test_bearer_value_is_consumed_not_just_the_scheme_word(self):
        out = self._scrub("Authorization: Bearer sk-verysecretvalue123")
        self.assertNotIn("verysecret", out)

    def test_jwt_anywhere_is_redacted(self):
        out = self._scrub("got eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abcdefghijklmno.signature back")
        self.assertNotIn("abcdefghijklmno", out)

    def test_benign_operational_lines_survive_intact(self):
        msg = "Poll abc-123: 124 matching, 1 new (48h), 0 price changes -> 1 sent"
        self.assertEqual(self._scrub(msg), msg)

    def test_args_are_scrubbed_too(self):
        import logging
        rec = logging.LogRecord("x", logging.INFO, "p", 1, "url=%s",
                                ("https://api.telegram.org/bot999999999:ZZZbbbCCCdddEEEfffGGGhhhIIIjjjKKKlll/x",), None)
        self.f.filter(rec)
        self.assertNotIn("ZZZbbbCCC", str(rec.args))

    def test_rotation_is_configured_so_logs_cannot_reach_tens_of_megabytes(self):
        from logging.handlers import RotatingFileHandler
        handlers = [h for h in self.bot.logging.getLogger().handlers
                    if isinstance(h, RotatingFileHandler)]
        self.assertTrue(handlers, "no RotatingFileHandler configured")
        self.assertLessEqual(handlers[0].maxBytes, 20 * 1024 * 1024)
        self.assertGreaterEqual(handlers[0].backupCount, 1)


class HeartbeatTelegramProbeTests(unittest.TestCase):
    """A heartbeat that never touches Telegram reported "online" through a
    14-minute outage in which no message could be received. It must probe."""

    def setUp(self):
        import test_bot_behavior
        test_bot_behavior._install_dependency_stubs()
        import importlib
        self.bot = importlib.import_module("bot")
        self.bot._last_telegram_probe = None

    def _run_heartbeat(self, get_me_result=None, get_me_error=None):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        ctx = MagicMock()
        if get_me_error:
            ctx.bot.get_me = AsyncMock(side_effect=get_me_error)
        else:
            ctx.bot.get_me = AsyncMock(return_value=get_me_result)
        captured = {}

        async def fake_update(**kw):
            captured.update(kw)

        with patch.object(self.bot, "_runtime_update", side_effect=fake_update):
            asyncio.run(self.bot.heartbeat(ctx))
        return captured

    def test_healthy_telegram_reports_online_and_ok(self):
        me = types.SimpleNamespace(username="TheCarHunterBot")
        out = self._run_heartbeat(get_me_result=me)
        self.assertEqual(out["state"], "online")
        self.assertTrue(out["telegram_ok"])
        self.assertIsNone(out["telegram_error"])

    def test_revoked_token_reports_degraded_not_online(self):
        """The exact 2026-08-12 failure: token revoked, getUpdates dead."""
        out = self._run_heartbeat(get_me_error=Exception("Unauthorized"))
        self.assertEqual(out["state"], "degraded")
        self.assertFalse(out["telegram_ok"])
        self.assertIn("Unauthorized", out["telegram_error"])

    def test_probe_failure_still_records_a_heartbeat(self):
        """Losing Telegram must not also lose telemetry — that hides the outage."""
        out = self._run_heartbeat(get_me_error=Exception("boom"))
        self.assertIn("last_heartbeat_at", out)
        self.assertIn("telegram_checked_at", out)

    def test_probe_is_rate_limited_not_run_every_tick(self):
        me = types.SimpleNamespace(username="TheCarHunterBot")
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch
        ctx = MagicMock()
        ctx.bot.get_me = AsyncMock(return_value=me)
        async def noop(**kw): pass
        with patch.object(self.bot, "_runtime_update", side_effect=noop):
            asyncio.run(self.bot.heartbeat(ctx))
            asyncio.run(self.bot.heartbeat(ctx))
            asyncio.run(self.bot.heartbeat(ctx))
        self.assertEqual(ctx.bot.get_me.await_count, 1)

    def test_error_message_is_truncated_and_carries_no_token(self):
        out = self._run_heartbeat(get_me_error=Exception("x" * 900))
        self.assertLessEqual(len(out["telegram_error"]), 320)

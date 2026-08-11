"""Tests for the Telegram listing card V2 information contract.

The central guarantee under test: a mandatory field is either rendered with a
real value or explicitly marked `לא פורסם` and recorded in `missing_fields`. It
is never silently omitted and never invented.
"""

import os
import sys
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
        for token in ("יונדאי אלנטרה", "Supreme", "2024", "132,000",
                      "יד 1", "32,000 ק״מ", "פרטית", "1.6 ל׳", "היברידי", "139 כ״ס"):
            self.assertIn(token, card.text, f"missing {token!r}")

    def test_empty_listing_marks_every_mandatory_field_missing(self):
        card = render_card({})
        for name in MANDATORY_FIELDS:
            self.assertIn(name, card.missing_fields, f"{name} not reported missing")
        # and the user is told so explicitly rather than shown a gap
        self.assertGreaterEqual(card.text.count(NOT_PUBLISHED), 5)

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
        self.assertIn("0 ק״מ", card.text)

    def test_nothing_is_invented_when_source_is_silent(self):
        card = render_card({"vehicle_name": "מאזדה 3"})
        self.assertNotIn("139", card.text)
        self.assertNotIn("2024", card.text)


class PriceTests(unittest.TestCase):
    def test_missing_price_says_not_published_and_invents_nothing(self):
        card = render_card({k: v for k, v in FULL.items() if k != "price"})
        self.assertIn("מחיר לא פורסם", card.text)
        self.assertIn("price_current", card.missing_fields)

    def test_price_drop_shows_both_prices_and_delta_in_shekels_and_percent(self):
        card = render_card(
            {**FULL, "price": 78000, "price_previous": 79500},
            event=EVENT_PRICE_DROP,
        )
        self.assertIn("₪78,000 מחיר חדש", card.text)
        self.assertIn("<s>₪79,500</s>", card.text)   # struck through, per spec
        self.assertIn("₪1,500", card.text)
        self.assertIn("1.9%", card.text)
        self.assertIn("ירידה", card.text)

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
        headline = card.text.split("\n")[1]
        self.assertNotIn("2024–2026", headline)
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
        self.assertIn("פורסמה במקור: 11.08.2026 10:17", card.text)  # UTC+3
        self.assertIn("זוהתה אצלנו", card.text)
        self.assertIn("נבדקה לאחרונה", card.text)

    def test_detection_time_is_not_shown_as_publish_time(self):
        card = render_card({k: v for k, v in FULL.items() if k != "listing_date"},
                           detected_at=datetime(2026, 8, 11, 8, 0, tzinfo=timezone.utc))
        self.assertIn(f"פורסמה במקור: {NOT_PUBLISHED}", card.text)
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
        self.assertLess(card.text.index("139 כ״ס"), card.text.index("הערות המוכר"))


class GoldenSnapshotTests(unittest.TestCase):
    """Whole-card snapshots for the scenarios the spec enumerates."""

    def test_golden_new_listing(self):
        card = render_card(FULL, search_name="יונדאי אלנטרה",
                           match_reasons=["יונדאי אלנטרה", "שנת 2024", "הנעה היברידית"],
                           last_checked_at=datetime(2026, 8, 11, 12, 16, tzinfo=timezone.utc))
        self.assertEqual(card.text, "\n".join([
            "<b>🚘 מודעה חדשה</b>",
            "<b>יונדאי אלנטרה Supreme היברידית</b>",
            "",
            "<b>₪132,000</b>",
            "",
            "2024 · 32,000 ק״מ · יד 1 · פרטית",
            "מנוע: 1.6 ל׳ · היברידי · 139 כ״ס",
            "אזור באר שבע והסביבה",
            "",
            "<b>למה קיבלת אותה?</b>",
            "יונדאי אלנטרה · שנת 2024 · הנעה היברידית",
            "",
            "פורסמה במקור: 11.08.2026 10:17",
            "מקור: יד2 · נבדקה לאחרונה 11.08.2026 15:16",
            "חיפוש: יונדאי אלנטרה",
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
            "<b>🔻 המחיר ירד</b>",
            "<b>קיה ספורטאז׳ Premium</b>",
            "",
            "<b>₪78,000 מחיר חדש</b>",
            "<s>₪79,500</s> מחיר קודם · ירידה של ₪1,500 (1.9%)",
            "",
            "2020 · 105,000 ק״מ · יד 2 · פרטית",
            "מנוע: 1.6 ל׳ · בנזין · 177 כ״ס",
            "אזור ירושלים",
            "",
            "פורסמה במקור: 07.06.2026 11:49",
            "מקור: יד2",
        ]))

    def test_golden_all_fields_missing(self):
        card = render_card({"vehicle_name": "רכב"})
        self.assertEqual(card.text, "\n".join([
            "<b>🚘 מודעה חדשה</b>",
            "<b>רכב</b>",
            f"גרסה/רמת גימור: {NOT_PUBLISHED}",
            "",
            "<b>מחיר לא פורסם</b>",
            "",
            f"{NOT_PUBLISHED} · {NOT_PUBLISHED} · {NOT_PUBLISHED} · {NOT_PUBLISHED}",
            f"מנוע: {NOT_PUBLISHED} · {NOT_PUBLISHED}",
            "",
            f"פורסמה במקור: {NOT_PUBLISHED}",
            "מקור: יד2",
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

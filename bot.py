#!/usr/bin/env python3
"""
Yad2 Car Search Telegram Bot
Searches are created on the website; the bot links users with a one-time token and sends alerts.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import re
import socket
import sys
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.error import Conflict
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

from config import Config
from supabase_manager import SupabaseManager
from yad2_scraper import Yad2Scraper
import api
from api import start_api_thread

os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler("logs/bot.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)
# httpx INFO lines include full request URLs. Telegram URLs contain the bot
# token, so dependency request logging must never be written to bot.log.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

config = Config()
sb = SupabaseManager()
scraper = Yad2Scraper()

_runtime_counters = {"searches_processed": 0, "messages_sent": 0}
_admin_schema_missing_logged = False


def esc(text: str) -> str:
    """Escape special characters for MarkdownV2."""
    return re.sub(r'([_*\[\]()~`>#+\-=|{}.!\\])', r'\\\1', str(text))


def _safe(s) -> str:
    """Strip Markdown-special chars from dynamic content (titles, cities, trims)."""
    return str(s or "").replace("*", "").replace("_", "").replace("`", "").replace("[", "").replace("]", "")


try:
    from zoneinfo import ZoneInfo
    _IL_TZ = ZoneInfo("Asia/Jerusalem")
except Exception:  # pragma: no cover
    _IL_TZ = None


def _fmt_il_time(iso_ts: Optional[str]) -> str:
    """Format a UTC ISO timestamp from Supabase as local Israel time (HH:MM DD/MM).
    Timestamps are stored in UTC; showing them raw confused users (looked hours stale)."""
    if not iso_ts:
        return "עדיין לא בוצעה"
    try:
        dt = datetime.fromisoformat(str(iso_ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC")) if _IL_TZ else dt
        if _IL_TZ is not None:
            dt = dt.astimezone(_IL_TZ)
        return dt.strftime("%H:%M %d/%m")
    except Exception:
        return _safe(str(iso_ts)[:16].replace("T", " "))

# ── /start ────────────────────────────────────────────────────────────────────

SITE_URL = os.getenv("SITE_URL", "https://carconnoisseur-web-iota.vercel.app").rstrip("/")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = str(update.effective_chat.id)

    # Secure one-click linking from the signed-in website.
    if context.args and context.args[0].startswith("link_"):
        token = context.args[0][len("link_"):].strip()
        linked = await asyncio.to_thread(sb.link_telegram_token, chat_id, token)
        if not linked:
            await update.message.reply_text(
                "❌ קישור החיבור אינו תקין או שפג תוקפו.\n\n"
                "חזור לאתר ולחץ שוב על „פתח וחבר Telegram“ כדי לקבל קישור חדש.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🌐 חזרה לאתר", url=f"{SITE_URL}/dashboard")
                ]]),
            )
            return

        searches = await asyncio.to_thread(sb.get_searches, chat_id)
        await update.message.reply_text(
            "🎉 *החשבון חובר בהצלחה!*\n\n"
            f"📧 {_safe(linked.get('email') or '')}\n"
            f"🔍 {len(searches)} חיפושים פעילים\n\n"
            "המודעות שכבר קיימות יסומנו כבסיס ולא יישלחו. "
            "מעכשיו תקבל כאן רק מודעות חדשות שמתאימות לחיפושים שלך.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⚙️ ניהול החיפושים", url=f"{SITE_URL}/dashboard")
            ]]),
        )
        return

    profile = await asyncio.to_thread(sb.get_profile_by_chat, chat_id)

    if profile:
        access = await asyncio.to_thread(sb.get_access_by_chat, chat_id)
        if access and not access.get("allowed"):
            blocked = access.get("state") == "blocked"
            reason = access.get("blocked_reason")
            await update.message.reply_text(
                ("🔒 *הגישה לחשבון נעצרה*" if blocked else "⏳ *תקופת הניסיון הסתיימה*")
                + "\n\n"
                + (_safe(reason) if blocked and reason else "החיפושים נשמרו, אך הסריקות וההתראות מושהות כרגע.")
                + "\n\nאפשר לפנות אלינו דרך האתר כדי לחדש את הגישה.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🌐 מעבר לאתר", url=f"{SITE_URL}/access")
                ]]),
            )
            return
        searches = await asyncio.to_thread(sb.get_searches, chat_id)
        count = len(searches)
        count_str = f"{count} חיפושים פעילים" if count != 1 else "חיפוש פעיל אחד"
        await update.message.reply_text(
            f"👋 ברוך השב, {user.first_name}!\n\n"
            f"✅ החשבון שלך מחובר ({profile['email']})\n"
            f"🔍 יש לך {count_str}\n\n"
            f"🌐 לניהול חיפושים: {SITE_URL}\n\n"
            "━━━━━━━━━━━━━━━\n"
            "📋 /my_searches – החיפושים שלי\n"
            "🔄 /check_now – בדוק מודעות עכשיו",
        )
    else:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🌐 פתח את האתר", url=SITE_URL)
        ]])
        await update.message.reply_text(
            f"👋 שלום {user.first_name}, ברוך הבא ל-*CarConnoisseur*!\n\n"
            "🚗 *מה זה?*\n"
            "בוט שסורק את יד2 כל 15 דקות ושולח לך התראה ישירות לטלגרם רק כשמתפרסמת מודעת רכב חדשה שמתאימה לחיפוש שלך.\n\n"
            "━━━━━━━━━━━━━━━\n"
            "*איך מתחילים?*\n\n"
            "1️⃣ היכנס לאתר וצור חשבון\n"
            "2️⃣ הגדר את החיפושים שלך\n"
            "3️⃣ לחץ באתר על „פתח וחבר Telegram“\n\n"
            "👇 לחץ כדי לפתוח את האתר:",
            parse_mode="Markdown",
            reply_markup=keyboard,
        )


# ── /my_searches ──────────────────────────────────────────────────────────────

async def my_searches(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    profile = await asyncio.to_thread(sb.get_profile_by_chat, chat_id)

    if not profile:
        await update.message.reply_text(
            "⚠️ החשבון עדיין לא מחובר.\n\nהיכנס לאתר ולחץ על „פתח וחבר Telegram“.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🌐 חיבור דרך האתר", url=f"{SITE_URL}/dashboard")
            ]]),
        )
        return

    access = await asyncio.to_thread(sb.get_access_by_chat, chat_id)
    if access and not access.get("allowed"):
        await update.message.reply_text(
            "🔒 החיפושים שלך שמורים, אבל הגישה וההתראות מושהות כרגע.\n\n"
            "אפשר לפנות אלינו דרך האתר לחידוש הגישה.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🌐 מעבר לאתר", url=f"{SITE_URL}/access")
            ]]),
        )
        return

    searches = await asyncio.to_thread(sb.get_searches, chat_id)
    if not searches:
        await update.message.reply_text(
            "📭 אין לך חיפושים שמורים.\n\n"
            f"כנס לאתר {SITE_URL.split('//')[-1]} להוספת חיפוש 🚗"
        )
        return

    keyboard = []
    for s in searches:
        keyboard.append([InlineKeyboardButton(f"🔍 {s['name']}", callback_data=f"view_{s['id']}")])
    keyboard.append([InlineKeyboardButton("⚙️ עריכה, השהיה וחיפוש חדש", url=f"{SITE_URL}/dashboard")])
    await update.message.reply_text(
        f"📋 *החיפושים שלך* ({len(searches)}):",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ── view / check callbacks ────────────────────────────────────────────────────

async def view_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = str(query.message.chat_id)
    sid = query.data.replace("view_", "")

    searches = await asyncio.to_thread(sb.get_searches, chat_id)
    s = next((x for x in searches if x["id"] == sid), None)
    if not s:
        await query.edit_message_text("❌ החיפוש לא נמצא.")
        return

    lines = [f"🔍 *{s['name']}*\n"]
    lines.append(f"🏭 יצרן: {s.get('manufacturer') or 'כל היצרנים'}")
    lines.append(f"🚘 דגם: {s.get('model') or 'כל הדגמים'}")
    if s.get("price_min") or s.get("price_max"):
        mn = f"₪{s['price_min']:,}" if s.get("price_min") else "ללא"
        mx = f"₪{s['price_max']:,}" if s.get("price_max") else "ללא"
        lines.append(f"💰 מחיר: {mn} – {mx}")
    if s.get("year_min") or s.get("year_max"):
        lines.append(f"📅 שנה: {s.get('year_min', '—')} – {s.get('year_max', '—')}")
    if s.get("km_max"):
        lines.append(f"🛣 ק\"מ מקס': {s['km_max']:,}")
    seen = len(s.get("seen_ids") or [])
    lines.append(f"\n👁 מודעות שנראו: {seen}")
    if s.get("last_scanned_at"):
        lines.append(f"🕐 סריקה אחרונה: {_fmt_il_time(s['last_scanned_at'])}")

    keyboard = [
        [
            InlineKeyboardButton("🔄 בדוק עכשיו", callback_data=f"chk_{sid}"),
            InlineKeyboardButton("⏸️ השהה", callback_data=f"pause_{sid}"),
        ],
        [
            InlineKeyboardButton("« חזרה", callback_data="back_to_list"),
            InlineKeyboardButton("⚙️ עריכה באתר", url=f"{SITE_URL}/dashboard"),
        ],
    ]
    await query.edit_message_text(
        "\n".join(lines), parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def check_single(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("🔄 בודק...")
    chat_id = str(query.message.chat_id)
    sid = query.data.replace("chk_", "")

    searches = await asyncio.to_thread(sb.get_searches, chat_id)
    s = next((x for x in searches if x["id"] == sid), None)
    if not s:
        await query.edit_message_text("❌ החיפוש לא נמצא.")
        return

    await query.edit_message_text(f"🔄 בודק את *{s['name']}*...", parse_mode="Markdown")
    new_listings, was_first_run, ids_to_mark = await _fetch_new(s)
    if new_listings:
        sent_ids = []
        for listing in new_listings:
            try:
                await send_listing(context.bot, int(chat_id), listing, s["name"], s["id"], is_welcome=was_first_run)
                sent_ids.append(listing["id"])
            except Exception as se:
                logger.error(f"send failed {listing['id']} → {chat_id}: {se}")
        if sent_ids:
            sent_prices = {l["id"]: l["price"] for l in new_listings if l["id"] in sent_ids and l.get("price") is not None}
            await asyncio.to_thread(sb.mark_seen, s["id"], sent_ids, None, sent_prices)
            await asyncio.to_thread(sb.mark_notified, s["id"])
            await context.bot.send_message(int(chat_id), f"✅ נשלחו {len(sent_ids)} מודעות חדשות!")
        else:
            await context.bot.send_message(int(chat_id), "⚠️ נמצאו מודעות, אך לא הצלחתי לשלוח אותן. אנסה שוב בסריקה הבאה.")
    else:
        await context.bot.send_message(int(chat_id), "😴 אין מודעות חדשות כרגע.")


async def back_to_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = str(query.message.chat_id)
    searches = await asyncio.to_thread(sb.get_searches, chat_id)
    if not searches:
        await query.edit_message_text("📭 אין חיפושים שמורים.")
        return
    keyboard = [[InlineKeyboardButton(f"🔍 {s['name']}", callback_data=f"view_{s['id']}")] for s in searches]
    keyboard.append([InlineKeyboardButton("⚙️ ניהול באתר", url=f"{SITE_URL}/dashboard")])
    await query.edit_message_text(
        f"📋 *החיפושים שלך* ({len(searches)}):",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def pause_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Pause an active search directly from a listing notification."""
    query = update.callback_query
    search_id = query.data.replace("pause_", "", 1)
    chat_id = str(query.message.chat_id)
    paused = await asyncio.to_thread(sb.pause_search_for_chat, search_id, chat_id)
    if not paused:
        await query.answer("לא הצלחתי להשהות את החיפוש", show_alert=True)
        return
    await query.answer("החיפוש הושהה")
    await query.edit_message_reply_markup(
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⚙️ ניהול והפעלה מחדש", url=f"{SITE_URL}/dashboard")
        ]])
    )
    await context.bot.send_message(
        int(chat_id),
        "⏸️ החיפוש הושהה ולא ישלח התראות נוספות. אפשר להפעיל אותו מחדש באתר בכל רגע.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⚙️ מעבר לחיפושים", url=f"{SITE_URL}/dashboard")
        ]]),
    )


# ── /check_now ────────────────────────────────────────────────────────────────

async def check_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    profile = await asyncio.to_thread(sb.get_profile_by_chat, chat_id)
    if not profile:
        await update.message.reply_text(
            "⚠️ החשבון עדיין לא מחובר. החיבור מתבצע בלחיצה אחת מתוך האתר.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🌐 חיבור דרך האתר", url=f"{SITE_URL}/dashboard")
            ]]),
        )
        return

    searches = await asyncio.to_thread(sb.get_searches, chat_id)
    if not searches:
        await update.message.reply_text("📭 אין חיפושים. הוסף חיפוש באתר.")
        return

    await update.message.reply_text(f"🔄 בודק {len(searches)} חיפושים...")
    total = 0
    failed = 0
    for s in searches:
        try:
            new_listings, was_first_run, ids_to_mark = await _fetch_new(s)
            sent_ids = []
            for listing in new_listings[:15]:
                try:
                    await send_listing(context.bot, int(chat_id), listing, s["name"], s["id"], is_welcome=was_first_run)
                    sent_ids.append(listing["id"])
                    total += 1
                except Exception as se:
                    logger.error(f"send failed {listing['id']} → {chat_id}: {se}")
                    failed += 1
            if sent_ids:
                sent_prices = {l["id"]: l["price"] for l in new_listings if l["id"] in sent_ids and l.get("price") is not None}
                await asyncio.to_thread(sb.mark_seen, s["id"], sent_ids, None, sent_prices)
                await asyncio.to_thread(sb.mark_notified, s["id"])
        except Exception as e:
            logger.error(f"check_now error for {s['id']}: {e}", exc_info=True)
            failed += 1
    if total:
        suffix = f"\n⚠️ {failed} הודעות יישלחו שוב בסריקה הבאה." if failed else ""
        await update.message.reply_text(f"✅ הבדיקה הסתיימה — נשלחו {total} מודעות חדשות.{suffix}")
    elif failed:
        await update.message.reply_text("⚠️ נמצאו מודעות, אך לא הצלחתי לשלוח אותן. אנסה שוב בסריקה הבאה.")
    else:
        await update.message.reply_text("😴 הבדיקה הסתיימה — אין כרגע מודעות חדשות באף חיפוש.")


# ── Scheduled poll ────────────────────────────────────────────────────────────

_poll_sem: Optional[asyncio.Semaphore] = None  # initialized lazily inside _fetch_new


def _apply_km_filter(listings: list, search: dict) -> list:
    km_max = search.get("km_max")
    if not km_max:
        return listings
    try:
        limit = int(km_max)
    except (ValueError, TypeError):
        return listings
    return [l for l in listings if l.get("km") is None or l["km"] <= limit]


async def _process_search_with_listings(bot, chat_id: str, search: dict, all_listings: list):
    """Match pre-fetched manufacturer listings against one search, send new/price-changed."""
    sid = search["id"]
    if _active_search_ids is not None and sid not in _active_search_ids:
        logger.info(f"Search {sid} was deleted — skipping")
        return
    async with _fetch_locks.setdefault(sid, asyncio.Lock()):
        seen_ids_list, seen_prices = await asyncio.to_thread(sb.get_seen_state, sid)
        is_first_run = seen_ids_list is None
        seen = set(seen_ids_list or [])

        # Client-side filter: model, sub_model, price, year (km after enrich)
        # Use dict() copies — enrich_with_km mutates in-place and all_listings is shared
        matching = [dict(l) for l in all_listings if scraper._matches_search(l, search)]

        # price_map tracks current prices for ALL matching (for price-change detection)
        price_map = {l["id"]: l["price"] for l in matching if l.get("price") is not None}

        if is_first_run:
            # First-run burn: every listing that already exists becomes the baseline.
            # Nothing is sent; only listings discovered in later polls are "new".
            await asyncio.to_thread(
                sb.mark_seen, sid,
                [l["id"] for l in matching], seen_ids_list or [],
                price_map if matching else None, seen_prices,
                True,  # force_write
            )
            await asyncio.to_thread(sb.update_search_status, sid, len(matching))
            logger.info(f"First run {sid}: seeded {len(matching)} existing listings; sent 0")
            return

        # Unseen listings from the last 7 days (the full recency window)
        unseen_7d = [l for l in matching if l["id"] not in seen and scraper._is_recent(l.get("listing_date"))]

        # For steady-state "new" alerts, only send listings from the last 48 hours.
        # Older unseen listings exist because seeding was incomplete (e.g. old bot bug,
        # URL mismatch between welcome fetch and manufacturer fetch). We mark them seen
        # silently so they stop appearing, but don't send them as "מודעה חדשה!".
        def _is_48h(date_val) -> bool:
            dt = scraper._parse_listing_date(date_val)
            if dt is None:
                return True  # no date → assume new
            return (datetime.utcnow() - dt).total_seconds() < 48 * 3600

        new = [l for l in unseen_7d if _is_48h(l.get("listing_date"))]

        price_changed = []
        for l in matching:
            if l["id"] in seen and l.get("price") is not None:
                old_price = seen_prices.get(l["id"])
                if old_price is not None and l["price"] != old_price:
                    l["_price_change"] = {"old": old_price, "new": l["price"]}
                    price_changed.append(l)

        # Send bounded batches. Anything beyond the batch limit stays pending for the
        # next poll instead of being marked seen and silently lost.
        new_candidates = new[:15]
        price_candidates = price_changed[:10]
        deferred_price_ids = {l["id"] for l in price_changed[10:]}

        # Enrich first, then km-filter. Candidates rejected by the km filter are safe
        # to mark now because they should never be delivered for this search.
        new_raw = await scraper.enrich_with_km(new_candidates)
        price_raw = await scraper.enrich_with_km(price_candidates)
        new_enriched = _apply_km_filter(new_raw, search)
        price_enriched = _apply_km_filter(price_raw, search)
        to_send = new_enriched + price_enriched
        to_send_ids = {l["id"] for l in to_send}

        # Mark silently-absorbed (2-7 day gap) and km-filtered listings now —
        # they are NOT being sent so it is safe to mark them immediately.
        # Listings that WILL be sent are marked only after successful delivery
        # so a send failure doesn't permanently lose them.
        new_ids = {l["id"] for l in new}
        silently_absorbed_ids = {
            l["id"] for l in matching if l["id"] not in seen and l["id"] not in new_ids
        }
        filtered_candidate_ids = {l["id"] for l in new_raw + price_raw} - to_send_ids
        ids_mark_now = list(silently_absorbed_ids | filtered_candidate_ids)

        # Do not advance the stored price for an alert that still needs delivery.
        # Otherwise a Telegram failure would make the price change disappear forever.
        pending_price_ids = deferred_price_ids | {
            l["id"] for l in price_enriched if l.get("_price_change")
        }
        safe_price_map = {k: v for k, v in price_map.items() if k not in pending_price_ids}
        await asyncio.to_thread(
            sb.mark_seen, sid,
            ids_mark_now, seen_ids_list,
            safe_price_map, seen_prices,
        )

        logger.info(f"Poll {sid}: {len(matching)} matching, {len(unseen_7d)} unseen (7d), {len(new)} new (48h), {len(price_changed)} price changes → {len(to_send)} sent")
        sent_ids = []
        for listing in to_send:
            try:
                await send_listing(bot, int(chat_id), listing, search["name"], search["id"])
                sent_ids.append(listing["id"])
            except Exception as e:
                logger.error(f"send failed {listing['id']} → {chat_id}: {e}")
        if sent_ids:
            sent_prices = {
                l["id"]: l["price"] for l in to_send
                if l["id"] in sent_ids and l.get("price") is not None
            }
            await asyncio.to_thread(sb.mark_seen, sid, sent_ids, None, sent_prices)
        await asyncio.to_thread(sb.update_search_status, sid, len(matching), bool(sent_ids))
        _runtime_counters["searches_processed"] += 1
        _runtime_counters["messages_sent"] += len(sent_ids)


_full_poll_lock: Optional[asyncio.Lock] = None


async def _runtime_update(**changes):
    """Best-effort operational telemetry; an unavailable status table must not stop alerts."""
    try:
        await asyncio.to_thread(sb.update_runtime_status, **changes)
    except Exception as exc:
        logger.debug(f"Runtime status update skipped: {exc}")


async def poll_all_searches(context: ContextTypes.DEFAULT_TYPE):
    global _full_poll_lock
    if _full_poll_lock is None:
        _full_poll_lock = asyncio.Lock()
    if _full_poll_lock.locked():
        logger.info("Full poll already running — duplicate request skipped")
        return
    async with _full_poll_lock:
        started = datetime.now(timezone.utc).isoformat()
        await _runtime_update(state="scanning", last_heartbeat_at=started, last_poll_started_at=started)
        try:
            await _poll_all_searches_impl(context)
            completed = datetime.now(timezone.utc).isoformat()
            await _runtime_update(
                state="online",
                last_heartbeat_at=completed,
                last_poll_completed_at=completed,
                last_error=None,
                **_runtime_counters,
            )
        except Exception as exc:
            await _runtime_update(
                state="degraded",
                last_heartbeat_at=datetime.now(timezone.utc).isoformat(),
                last_error=str(exc)[:1000],
                **_runtime_counters,
            )


async def _poll_all_searches_impl(context: ContextTypes.DEFAULT_TYPE):
    logger.info("⏱ Running scheduled poll...")
    try:
        all_searches = await asyncio.to_thread(sb.get_all_searches)
        logger.info(f"Poll: {len(all_searches)} searches")

        # New (unseeded) searches are handled by welcome_new_searches — skip them here
        seeded = [(chat_id, s) for chat_id, s in all_searches if s.get("seen_ids") is not None]

        # Group by (manufacturer, model) so each distinct model is fetched from
        # yad2 filtered to that model. This keeps a brand-new model-specific
        # listing on page 1 of the result set instead of being pushed past the
        # 3 fetched pages by other models / promoted ads of the same manufacturer
        # (which delayed model-specific alerts by hours). Searches with a
        # manufacturer but no specific model still fetch the whole brand feed.
        by_key: dict[tuple[str, str], list[tuple[str, dict]]] = defaultdict(list)
        no_mfr: list[tuple[str, dict]] = []
        for chat_id, s in seeded:
            mfr = (s.get("manufacturer") or "").strip()
            model = (s.get("model") or "").strip()
            if mfr:
                by_key[(mfr, model)].append((chat_id, s))
            else:
                no_mfr.append((chat_id, s))

        logger.info(f"Poll: {len(by_key)} unique (manufacturer, model) groups, {len(no_mfr)} no-manufacturer searches")

        fetch_sem = asyncio.Semaphore(5)    # max 5 concurrent yad2 fetches
        process_sem = asyncio.Semaphore(10)  # max 10 concurrent per-search processing tasks

        async def _process_one(chat_id: str, s: dict, listings: list):
            async with process_sem:
                await _process_search_with_listings(context.bot, chat_id, s, listings)

        async def _fetch_and_process_mfr(key: tuple[str, str], group: list):
            mfr, model = key
            params = {"manufacturer": mfr}
            if model:
                params["model"] = model
            async with fetch_sem:
                try:
                    listings, _ = await scraper.fetch_listings(dict(params))
                except Exception as e:
                    logger.error(f"Poll fetch failed for {mfr}/{model}: {e}")
                    return
            if not listings:
                return
            results = await asyncio.gather(
                *[_process_one(chat_id, s, listings) for chat_id, s in group],
                return_exceptions=True,
            )
            for (chat_id, s), res in zip(group, results):
                if isinstance(res, Exception):
                    logger.error(f"Poll task {s['id']} for {chat_id}: {res}", exc_info=True)

        async def _process_no_mfr(chat_id: str, s: dict):
            if _active_search_ids is not None and s["id"] not in _active_search_ids:
                return
            new_listings, was_first_run, ids_to_mark = await _fetch_new(s)
            if not new_listings:
                return
            sent_ids = []
            for listing in new_listings:
                try:
                    await send_listing(context.bot, int(chat_id), listing, s["name"], s["id"], is_welcome=was_first_run)
                    sent_ids.append(listing["id"])
                    logger.info(f"Sent {listing['id']} to {chat_id}")
                except Exception as e:
                    logger.error(f"send failed {listing['id']} → {chat_id}: {e}")
            if sent_ids:
                sent_prices = {
                    l["id"]: l["price"] for l in new_listings
                    if l["id"] in sent_ids and l.get("price") is not None
                }
                await asyncio.to_thread(sb.mark_seen, s["id"], sent_ids, None, sent_prices)
                await asyncio.to_thread(sb.mark_notified, s["id"])

        tasks = [_fetch_and_process_mfr(key, group) for key, group in by_key.items()]
        tasks += [_process_no_mfr(chat_id, s) for chat_id, s in no_mfr]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, res in enumerate(results):
            if isinstance(res, Exception):
                logger.error(f"Poll task {i} failed: {res}", exc_info=(type(res), res, res.__traceback__))

        if scraper.consecutive_failures >= 3 and ADMIN_CHAT_IDS:
            alert = (
                f"⚠️ *יד2 לא מגיבה*\n\n"
                f"{scraper.consecutive_failures} כשלונות ברצף — ייתכן שה-IP נחסם.\n"
                f"נסה `/debug_now` לבדיקה."
            )
            for cid in ADMIN_CHAT_IDS:
                try:
                    await context.bot.send_message(int(cid), alert, parse_mode="Markdown")
                except Exception:
                    pass

        if _active_search_ids is not None:
            for sid in list(_fetch_locks.keys()):
                if sid not in _active_search_ids:
                    del _fetch_locks[sid]

    except Exception as e:
        logger.error(f"poll_all_searches crashed: {e}", exc_info=True)
        raise


# ── Admin command queue ──────────────────────────────────────────────────────

async def _run_search_now(bot, profile: dict, search: dict) -> dict:
    chat_id = profile.get("telegram_chat_id")
    if not chat_id:
        raise ValueError("למשתמש אין חשבון Telegram מחובר")
    if search.get("is_active") is False:
        raise ValueError("החיפוש מושהה")

    listings, was_first_run, _ = await _fetch_new(search)
    sent_ids = []
    for listing in listings[:25]:
        try:
            await send_listing(bot, int(chat_id), listing, search["name"], search["id"], is_welcome=was_first_run)
            sent_ids.append(listing["id"])
        except Exception as exc:
            logger.error(f"Admin scan send failed {listing.get('id')} → {chat_id}: {exc}")

    if sent_ids:
        sent_prices = {
            listing["id"]: listing["price"]
            for listing in listings
            if listing["id"] in sent_ids and listing.get("price") is not None
        }
        await asyncio.to_thread(sb.mark_seen, search["id"], sent_ids, None, sent_prices)
        await asyncio.to_thread(sb.mark_notified, search["id"])

    _runtime_counters["searches_processed"] += 1
    _runtime_counters["messages_sent"] += len(sent_ids)
    return {"search_id": search["id"], "found": len(listings), "sent": len(sent_ids), "seeded": was_first_run}


async def _execute_admin_job(context: ContextTypes.DEFAULT_TYPE, job: dict) -> dict:
    job_type = job["job_type"]
    user_id = job.get("target_user_id")
    search_id = job.get("target_search_id")
    payload = job.get("payload") or {}

    if job_type == "scan_all":
        await poll_all_searches(context)
        return {"scope": "all", **_runtime_counters}

    if job_type == "send_broadcast":
        message = str(payload.get("message") or "").strip()
        if not message:
            raise ValueError("הודעת השידור ריקה")
        profiles = await asyncio.to_thread(sb.get_all_connected_profiles)
        sent = 0
        failed = 0
        for profile in profiles:
            try:
                await context.bot.send_message(int(profile["telegram_chat_id"]), message)
                sent += 1
            except Exception as exc:
                failed += 1
                logger.warning(f"Broadcast failed for profile={profile.get('id')}: {exc}")
        _runtime_counters["messages_sent"] += sent
        return {"recipients": len(profiles), "sent": sent, "failed": failed}

    profile = await asyncio.to_thread(sb.get_profile_by_id, user_id)
    if not profile:
        raise ValueError("המשתמש לא נמצא")

    if job_type == "send_message":
        if not profile.get("telegram_chat_id"):
            raise ValueError("למשתמש אין חשבון Telegram מחובר")
        message = str(payload.get("message") or "").strip()
        if not message:
            raise ValueError("ההודעה ריקה")
        await context.bot.send_message(int(profile["telegram_chat_id"]), message)
        _runtime_counters["messages_sent"] += 1
        return {"sent": 1, "user_id": user_id}

    if job_type in ("scan_user", "scan_search"):
        access = await asyncio.to_thread(sb.get_user_access, user_id)
        if not access.get("allowed"):
            raise ValueError("המשתמש חסום או שהגישה שלו פגה; הסריקה לא הופעלה")

    if job_type == "scan_user":
        searches = await asyncio.to_thread(sb.get_searches_by_user_id, user_id, True)
        results = []
        for search in searches:
            results.append(await _run_search_now(context.bot, profile, search))
        return {
            "user_id": user_id,
            "searches": len(results),
            "sent": sum(item["sent"] for item in results),
            "results": results,
        }

    search = await asyncio.to_thread(sb.get_search_by_id, search_id, user_id)
    if not search:
        raise ValueError("החיפוש לא נמצא או אינו שייך למשתמש")
    if job_type == "reset_baseline":
        await asyncio.to_thread(sb.reset_seen_ids, search_id)
        return {"search_id": search_id, "baseline_reset": True}
    if job_type == "scan_search":
        return await _run_search_now(context.bot, profile, search)
    raise ValueError(f"Unsupported admin job type: {job_type}")


_admin_job_lock: Optional[asyncio.Lock] = None


async def process_admin_jobs(context: ContextTypes.DEFAULT_TYPE):
    global _admin_job_lock
    if _admin_job_lock is None:
        _admin_job_lock = asyncio.Lock()
    if _admin_job_lock.locked():
        return
    async with _admin_job_lock:
        await _process_admin_jobs_impl(context)


async def _process_admin_jobs_impl(context: ContextTypes.DEFAULT_TYPE):
    global _admin_schema_missing_logged
    try:
        job = await asyncio.to_thread(sb.claim_next_admin_job)
        _admin_schema_missing_logged = False
    except Exception as exc:
        if not _admin_schema_missing_logged:
            logger.warning(f"Admin command queue unavailable (run migration 0006 before enabling it): {exc}")
            _admin_schema_missing_logged = True
        return
    if not job:
        return

    logger.info(f"Admin job started: {job['job_type']} id={job['id']}")
    try:
        result = await _execute_admin_job(context, job)
        await asyncio.to_thread(sb.finish_admin_job, job["id"], result, None)
        await _runtime_update(
            state="online",
            last_heartbeat_at=datetime.now(timezone.utc).isoformat(),
            last_job_at=datetime.now(timezone.utc).isoformat(),
            **_runtime_counters,
        )
        logger.info(f"Admin job completed: id={job['id']} result={result}")
    except Exception as exc:
        logger.error(f"Admin job failed: id={job['id']} {exc}", exc_info=True)
        try:
            await asyncio.to_thread(sb.finish_admin_job, job["id"], None, str(exc))
        except Exception as finish_exc:
            logger.error(f"Failed to persist admin job failure: {finish_exc}")


async def heartbeat(context: ContextTypes.DEFAULT_TYPE):
    await _runtime_update(
        state="online" if not (_full_poll_lock and _full_poll_lock.locked()) else "scanning",
        last_heartbeat_at=datetime.now(timezone.utc).isoformat(),
        version=os.getenv("BOT_VERSION", "dev"),
        host_name=socket.gethostname()[:120],
        **_runtime_counters,
    )


# ── Fetch helper (replaces scraper.fetch_new_listings) ────────────────────────

_fetch_locks: dict[str, asyncio.Lock] = {}
_active_search_ids: Optional[set[str]] = None  # None until first successful fetch


async def _fetch_new(search: dict) -> tuple[list, bool, list[str]]:
    """Fetch listings not yet seen, update seen_ids in Supabase.
    Returns (listings_to_send, was_first_run, ids_to_mark_after_send).

    For first-run: ids_to_mark_after_send is [] — seeding happens immediately inside.
    For steady-state: background listings are marked immediately; new/price-changed
    listings are returned with their IDs so the caller can mark them AFTER a
    successful send. This prevents a failed send from permanently losing a listing.
    """
    global _poll_sem
    if _poll_sem is None:
        _poll_sem = asyncio.Semaphore(5)

    sid = search["id"]
    async with _fetch_locks.setdefault(sid, asyncio.Lock()):
        seen_ids_list, seen_prices = await asyncio.to_thread(sb.get_seen_state, sid)
        is_first_run = seen_ids_list is None
        seen = set(seen_ids_list or [])

        async with _poll_sem:
            listings, yad2_responded = await scraper.fetch_listings(search, seen_ids=seen)

        if yad2_responded:
            await asyncio.to_thread(sb.update_search_status, sid, len(listings))

        price_map = {l["id"]: l["price"] for l in listings if l.get("price") is not None}

        if is_first_run:
            # Seed ALL current listings and send none. From now on, only listings first
            # discovered in a later poll can produce a notification.
            if listings:
                await asyncio.to_thread(
                    sb.mark_seen, sid,
                    [l["id"] for l in listings], seen_ids_list or [],
                    price_map, seen_prices,
                )
            elif yad2_responded:
                # yad2 responded but nothing matched — write empty seed to stop welcome loop
                await asyncio.to_thread(
                    sb.mark_seen, sid,
                    [], seen_ids_list or [],
                    None, seen_prices,
                    True,
                )
            # if not yad2_responded: leave unseeded — welcome_new_searches will retry
            logger.info(f"First run {sid}: seeded {len(listings)} existing listings; sent 0")
            return [], True, []

        # Steady-state — compute new/price-changed BEFORE any mark_seen call
        new = [l for l in listings if l["id"] not in seen and scraper._is_recent(l.get("listing_date"))]

        price_changed = []
        for l in listings:
            if l["id"] in seen and l.get("price") is not None:
                old_price = seen_prices.get(l["id"])
                if old_price is not None and l["price"] != old_price:
                    l["_price_change"] = {"old": old_price, "new": l["price"]}
                    price_changed.append(l)

        new_candidates = new[:15]
        price_candidates = price_changed[:10]
        deferred_price_ids = {l["id"] for l in price_changed[10:]}
        new_raw = await scraper.enrich_with_km(new_candidates)
        price_raw = await scraper.enrich_with_km(price_candidates)
        result = _apply_km_filter(new_raw, search) + _apply_km_filter(price_raw, search)

        # Mark only listings that are not waiting for a later batch or delivery retry.
        to_send_ids = {l["id"] for l in result}
        filtered_candidate_ids = {l["id"] for l in new_raw + price_raw} - to_send_ids
        price_changed_ids = {l["id"] for l in price_changed}
        stable_seen_ids = {
            l["id"] for l in listings
            if l["id"] in seen and l["id"] not in price_changed_ids
        }
        new_ids = {l["id"] for l in new}
        silently_absorbed_ids = {
            l["id"] for l in listings if l["id"] not in seen and l["id"] not in new_ids
        }
        background_ids = list(filtered_candidate_ids | stable_seen_ids | silently_absorbed_ids)
        pending_price_ids = deferred_price_ids | {
            l["id"] for l in result if l.get("_price_change")
        }
        safe_price_map = {k: v for k, v in price_map.items() if k not in pending_price_ids}
        await asyncio.to_thread(
            sb.mark_seen, sid,
            background_ids, seen_ids_list or [],
            safe_price_map, seen_prices,
        )

        logger.info(f"Poll {sid}: {len(listings)} fetched, {len(new)} new, {len(price_changed)} price changes → {len(result)} to send")
        return result, False, [l["id"] for l in result]


# ── send_listing ──────────────────────────────────────────────────────────────

async def send_listing(
    bot,
    chat_id: int,
    listing: dict,
    search_name: str,
    search_id: str | None = None,
    is_welcome: bool = False,
):
    title       = listing.get("title") or "רכב"
    trim        = listing.get("trim") or ""
    price       = listing.get("price")
    year        = listing.get("year") or "—"
    km          = listing.get("km")
    city        = listing.get("city") or "—"
    hand_text   = listing.get("hand_text") or (f"יד {listing['hand']}" if listing.get("hand") else "—")
    ownership   = listing.get("ownership") or "—"
    engine_cc   = listing.get("engine_cc")
    engine_type = listing.get("engine_type") or ""
    horsepower  = listing.get("horsepower")
    turbo       = listing.get("turbo", False)
    test_date   = listing.get("test_date") or ""
    description = listing.get("description") or ""
    features    = listing.get("features") or ""
    contact_phone = listing.get("contact_phone") or ""
    contact_name  = listing.get("contact_name") or ""
    photo_url   = listing.get("photo_url")

    header = _safe(title)
    if trim:
        header += f" | {_safe(trim)}"

    engine_parts = []
    if engine_cc:
        liters = round(engine_cc / 1000, 1)
        engine_parts.append(f"{liters} ל׳")
    if engine_type:
        engine_parts.append(_safe(engine_type))
    if turbo:
        engine_parts.append("טורבו")
    if horsepower:
        engine_parts.append(f"{horsepower} כ\"ס")
    engine_str = " · ".join(engine_parts)

    price_change = listing.get("_price_change")
    if price_change:
        old_p = price_change["old"]
        new_p = price_change["new"]
        arrow = "⬇️" if new_p < old_p else "⬆️"
        price_header = f"💰 *עודכן מחיר!* {arrow} ₪{old_p:,} ← ₪{new_p:,}"
    else:
        price_header = None

    if price_change:
        listing_header = "🔄 *עודכן מחיר!*"
    else:
        listing_header = "🚗 *מודעה חדשה*"

    lines = [
        listing_header,
        f"*{header}*",
    ]
    if price_change:
        lines.append(price_header)
    else:
        lines.append(f"💰 *{price:,} ₪*" if price else "💰 מחיר לא צוין")

    lines.extend([
        "━━━━━━━━━━━━━━",
        f"📅 שנה: {year}",
        f"✋ יד: {_safe(hand_text)}",
        f"🛣️ קילומטראז׳: {km:,} ק\"מ" if km is not None else "🛣️ קילומטראז׳: לא צוין",
        f"🏷️ בעלות: {_safe(ownership)}",
    ])
    if engine_str:
        lines.append(f"⚙️ מנוע: {engine_str}")
    if test_date:
        lines.append(f"🧪 טסט עד: {_safe(test_date)}")
    lines.append(f"📍 אזור מכירה: {_safe(city)}")
    if contact_phone:
        contact_line = f"📞 {_safe(contact_phone)}"
        if contact_name:
            contact_line += f" {_safe(contact_name)}"
        lines.append(contact_line)
    lines.append(f"🔎 חיפוש: {_safe(search_name)}")

    listing_dt = scraper._parse_listing_date(listing.get("listing_date"))
    if listing_dt:
        lines.append(f"🕐 פורסמה: {listing_dt.strftime('%d/%m/%Y %H:%M')}")
    # Optional free text stays last so Telegram's photo-caption limit never hides
    # the mandatory vehicle facts, seller contact or the originating search.
    if features:
        lines.append(f"✨ תוספות: {_safe(features)[:220]}")
    if description:
        lines.append(f"📝 הערות המוכר: {_safe(description)[:240]}")

    text = "\n".join(l for l in lines if l is not None)
    if len(text) > 1020:
        text = text[:1020] + "..."

    keyboard = [[InlineKeyboardButton("🔗 פתיחת המודעה ביד2", url=listing["url"])]]
    actions = [InlineKeyboardButton("⚙️ ניהול באתר", url=f"{SITE_URL}/dashboard")]
    if search_id:
        actions.insert(0, InlineKeyboardButton("⏸️ השהה חיפוש", callback_data=f"pause_{search_id}"))
    keyboard.append(actions)
    markup = InlineKeyboardMarkup(keyboard)

    if photo_url:
        try:
            await bot.send_photo(chat_id, photo=photo_url, caption=text, parse_mode="Markdown", reply_markup=markup)
            return
        except Exception as e:
            logger.info(f"Direct URL failed for {listing['id']}: {e} — trying download")
        photo_bytes = await scraper.download_photo(photo_url)
        if photo_bytes:
            try:
                await bot.send_photo(chat_id, photo=io.BytesIO(photo_bytes), caption=text, parse_mode="Markdown", reply_markup=markup)
                return
            except Exception as e:
                logger.warning(f"Photo bytes failed for {listing['id']}: {e}")

    try:
        await bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=markup)
    except Exception:
        # Fallback: strip all formatting in case Markdown parsing failed
        plain = re.sub(r"[*_`\[\]]", "", text)
        try:
            await bot.send_message(chat_id, plain, reply_markup=markup)
        except Exception as e:
            logger.error(f"Failed to send listing {listing['id']} to {chat_id}: {e}")
            raise


# ── Misc commands ─────────────────────────────────────────────────────────────

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 *פקודות:*\n\n"
        "*/my\\_searches* – החיפושים שלי\n"
        "*/check\\_now* – בדוק עכשיו\n"
        "*/status* – סטטוס הבוט\n"
        "*/clear\\_history* – אפס את נקודת ההתחלה של המעקב\n\n"
        f"⏱ הבוט בודק אוטומטית כל *{config.POLL_INTERVAL_MINUTES}* דקות.\n"
        f"🌐 חיפושים מנוהלים באתר: {SITE_URL.split('//')[-1]}",
        parse_mode="Markdown",
    )


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    profile = await asyncio.to_thread(sb.get_profile_by_chat, chat_id)
    if not profile:
        await update.message.reply_text(
            "⚠️ החשבון עדיין לא מחובר.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🌐 חיבור דרך האתר", url=f"{SITE_URL}/dashboard")
            ]]),
        )
        return
    access = await asyncio.to_thread(sb.get_access_by_chat, chat_id)
    if access and not access.get("allowed"):
        blocked = access.get("state") == "blocked"
        reason = access.get("blocked_reason")
        await update.message.reply_text(
            ("🔒 *הגישה לחשבון נעצרה*" if blocked else "⏳ *תקופת הניסיון הסתיימה*")
            + "\n\n"
            + (_safe(reason) if blocked and reason else "הסריקות וההתראות מושהות, אבל החיפושים שלך נשמרו.")
            + "\n\nלחידוש הגישה אפשר לפנות אלינו דרך האתר.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🌐 מעבר לאתר", url=f"{SITE_URL}/access")
            ]]),
        )
        return
    searches = await asyncio.to_thread(sb.get_searches, chat_id)
    if not searches:
        await update.message.reply_text(
            "📭 אין לך חיפושים שמורים עדיין.\n\nהיכנס לאתר כדי להוסיף חיפוש 🚗",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⚙️ הוספת חיפוש", url=f"{SITE_URL}/dashboard")
            ]]),
        )
        return

    # Show only THIS user's own searches, each with its state — nothing about
    # other users or system-wide totals.
    lines = ["📋 *הסטטוס שלך*\n"]
    for s in searches:
        active = s.get("is_active", True)
        state = "🟢 פעיל" if active else "⏸️ מושהה"
        lines.append(f"• *{_safe(s.get('name') or 'חיפוש')}* — {state}")
    scanned = [s.get("last_scanned_at") for s in searches if s.get("last_scanned_at")]
    last_scan = _fmt_il_time(max(scanned)) if scanned else "עדיין לא בוצעה"
    lines.append(f"\n🕐 סריקה אחרונה: {last_scan}")
    lines.append(f"⏱ הבוט סורק אוטומטית כל {config.POLL_INTERVAL_MINUTES} דקות")
    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⚙️ ניהול החיפושים", url=f"{SITE_URL}/dashboard")
        ]]),
    )


async def clear_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    searches = await asyncio.to_thread(sb.get_searches, chat_id)
    if not searches:
        await update.message.reply_text("אין חיפושים שמורים.")
        return

    def _do_clear():
        for s in searches:
            sb.reset_seen_ids(s["id"])

    await asyncio.to_thread(_do_clear)
    await update.message.reply_text(
        f"✅ נקודת ההתחלה אופסה ל-{len(searches)} חיפושים.\n"
        "בבדיקה הבאה המודעות הקיימות יסומנו כבסיס ולא יישלחו; לאחר מכן יישלחו רק מודעות חדשות.",
    )


async def logs_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        await update.message.reply_text("⛔ הפקודה הזו זמינה למנהלי הבוט בלבד.")
        return
    log_path = "logs/bot.log"
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        filtered = [l for l in lines if "httpx" not in l]
        last_lines = "".join(filtered[-60:])
        if len(last_lines) > 4000:
            last_lines = last_lines[-4000:]
        await update.message.reply_text(f"📋 *לוג:*\n```\n{last_lines}\n```", parse_mode="Markdown")
    except FileNotFoundError:
        await update.message.reply_text("❌ קובץ לוג לא נמצא.")


async def debug_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        await update.message.reply_text("⛔ הפקודה הזו זמינה למנהלי הבוט בלבד.")
        return
    await update.message.reply_text("🔍 בודק חיבור ליד2...")
    try:
        info = await scraper.debug_page()
        lines = ["*Debug Report*\n"]
        for k, v in info.items():
            if k == "html_preview":
                continue
            lines.append(f"`{k}`: {v}")
        if "html_preview" in info:
            lines.append(f"\n*HTML:*\n```\n{str(info['html_preview'])[:500]}\n```")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ שגיאה: {e}")


async def debug_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Diagnose search: show raw Supabase data, URL sent to yad2, and per-listing filter result."""
    if not _is_admin(update):
        await update.message.reply_text("⛔ הפקודה הזו זמינה למנהלי הבוט בלבד.")
        return
    import json as _json
    chat_id = str(update.effective_chat.id)
    searches = await asyncio.to_thread(sb.get_searches, chat_id)
    if not searches:
        await update.message.reply_text("אין חיפושים.")
        return
    s = searches[0]

    # Show raw Supabase data (minus seen_ids)
    raw_data = {k: v for k, v in s.items() if k != "seen_ids"}
    await update.message.reply_text(
        f"📦 *נתונים מ-Supabase:*\n```\n{_json.dumps(raw_data, ensure_ascii=False, indent=2)}\n```",
        parse_mode="Markdown",
    )

    from urllib.parse import urlencode
    params = scraper._build_params(s)
    url = f"https://www.yad2.co.il/vehicles/cars?{urlencode(params)}" if params else "https://www.yad2.co.il/vehicles/cars"
    await update.message.reply_text(f"🔗 URL: `{url}`", parse_mode="Markdown")

    try:
        raw = await scraper._fetch_url(url)
        filtered = [r for r in raw if scraper._matches_search(r, s)]
        seen_ids = set(await asyncio.to_thread(sb.get_seen_ids, s["id"]))
        lines = [f"גולמי: {len(raw)} | אחרי סינון: {len(filtered)} | כבר-נראו: {len(seen_ids)}\n"]
        for item in raw[:12]:
            mt = item.get("model_text", "—")
            raw_date = item.get("listing_date")
            dt = scraper._parse_listing_date(raw_date)
            date_str = dt.strftime("%d/%m %H:%M") if dt else str(raw_date or "—")[:16]
            match = "✅" if scraper._matches_search(item, s) else "❌"
            seen_mark = "👁" if item["id"] in seen_ids else "🆕"
            lines.append(f"{match}{seen_mark} [{mt}] | {date_str}")
        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        await update.message.reply_text(f"שגיאה: {e}")


# ── Seed newly-created searches (runs every 60s) ─────────────────────────────

async def welcome_new_searches(context: ContextTypes.DEFAULT_TYPE):
    """Seed new searches silently + detect deletions (runs every 60s).

    Uses the same manufacturer-based fetch as poll_all_searches so that seeding
    covers the full result set. Every listing present at creation time becomes
    part of the baseline; users receive only listings discovered later.
    """
    global _active_search_ids
    try:
        all_searches = await asyncio.to_thread(sb.get_all_searches)
        current_ids = {s["id"] for _, s in all_searches}

        removed = (_active_search_ids - current_ids) if _active_search_ids is not None else set()
        if removed:
            logger.info(f"Detected {len(removed)} deleted search(es): {removed}")
            for sid in removed:
                _fetch_locks.pop(sid, None)
        _active_search_ids = current_ids

        new_searches = [
            (chat_id, s) for chat_id, s in all_searches
            if s.get("seen_ids") is None
        ]
        if not new_searches:
            return
        logger.info(f"welcome_new_searches: {len(new_searches)} new search(es) found")

        # Group by manufacturer — same pattern as poll_all_searches so seeding is consistent
        by_mfr: dict[str, list[tuple[str, dict]]] = defaultdict(list)
        no_mfr: list[tuple[str, dict]] = []
        for chat_id, s in new_searches:
            mfr = (s.get("manufacturer") or "").strip()
            if mfr:
                by_mfr[mfr].append((chat_id, s))
            else:
                no_mfr.append((chat_id, s))

        # Manufacturer searches: fetch once, process with bounded concurrency (max 3 at a time)
        _welcome_sem = asyncio.Semaphore(3)

        async def _welcome_one(mfr_listings, w_chat_id, w_s):
            async with _welcome_sem:
                await _process_search_with_listings(context.bot, w_chat_id, w_s, mfr_listings)

        for mfr, group in by_mfr.items():
            try:
                listings, _ = await scraper.fetch_listings({"manufacturer": mfr})
                if not listings:
                    continue
                results = await asyncio.gather(
                    *[_welcome_one(listings, chat_id, s) for chat_id, s in group],
                    return_exceptions=True,
                )
                for (chat_id, s), res in zip(group, results):
                    if isinstance(res, Exception):
                        logger.error(f"welcome {s.get('id')} for {chat_id}: {res}", exc_info=True)
            except Exception as e:
                logger.error(f"welcome_new_searches mfr={mfr}: {e}", exc_info=True)

        # No-manufacturer searches: _fetch_new performs the same silent first-run burn.
        for chat_id, s in no_mfr:
            try:
                await _fetch_new(s)
            except Exception as e:
                logger.error(f"welcome_new_searches {s.get('id')}: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"welcome_new_searches crashed: {e}", exc_info=True)


# ── Error handling ────────────────────────────────────────────────────────────

async def my_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(f"🔑 ה-Chat ID שלך:\n\n`{chat_id}`", parse_mode="Markdown")


ADMIN_CHAT_IDS = set(filter(None, os.getenv("ADMIN_CHAT_IDS", "").split(",")))


def _is_admin(update: Update) -> bool:
    return str(update.effective_chat.id) in ADMIN_CHAT_IDS


async def admin_debug(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Usage: /admin_debug <email>"""
    if not _is_admin(update):
        return
    if not context.args:
        await update.message.reply_text("שימוש: /admin_debug <email>")
        return
    email = context.args[0].strip().lower()
    profile, searches = await asyncio.to_thread(sb.get_searches_by_email, email)
    if not profile:
        await update.message.reply_text(f"❌ לא נמצא פרופיל עם המייל {email}")
        return

    lines = [
        f"👤 *{email}*",
        f"telegram\\_chat\\_id: `{profile.get('telegram_chat_id') or 'לא מחובר'}`",
        f"חיפושים: {len(searches)}",
        "",
    ]
    for s in searches:
        seen_count = len(s.get("seen_ids") or [])
        is_seeded = s.get("seen_ids") is not None
        lines.append(
            f"🔍 *{s.get('name', '—')}*\n"
            f"  יצרן: {s.get('manufacturer') or 'כל'} | דגם: {s.get('model') or 'כל'}\n"
            f"  מחיר: {s.get('price_min') or '—'}–{s.get('price_max') or '—'} | "
            f"שנה: {s.get('year_min') or '—'}–{s.get('year_max') or '—'}\n"
            f"  seen\\_ids: {'NULL (לא נזרע!)' if not is_seeded else str(seen_count)}"
        )
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def admin_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Usage: /admin_reset <email>  — resets seen_ids to NULL so welcome batch re-runs"""
    if not _is_admin(update):
        return
    if not context.args:
        await update.message.reply_text("שימוש: /admin_reset <email>")
        return
    email = context.args[0].strip().lower()
    profile, searches = await asyncio.to_thread(sb.get_searches_by_email, email)
    if not profile:
        await update.message.reply_text(f"❌ לא נמצא פרופיל עם המייל {email}")
        return
    if not searches:
        await update.message.reply_text(f"⚠️ לא נמצאו חיפושים עבור {email}")
        return

    def _do_reset():
        for s in searches:
            sb.reset_seen_ids(s["id"])

    await asyncio.to_thread(_do_reset)
    await update.message.reply_text(
        f"✅ אופסו {len(searches)} חיפושים עבור {email}\n"
        "בסריקה הבאה המודעות הקיימות יסומנו מחדש כבסיס ולא יישלחו."
    )


async def _error_handler(update, context: ContextTypes.DEFAULT_TYPE):
    if isinstance(context.error, Conflict):
        logger.warning("409 Conflict: another getUpdates session active — will retry automatically")
        return
    logger.error(f"Unhandled error: {context.error}", exc_info=context.error)


# ── post_init & main ──────────────────────────────────────────────────────────

async def _post_init(application):
    api.set_bot(
        bot=application.bot,
        loop=asyncio.get_running_loop(),
        scraper=scraper,
    )
    await application.bot.set_my_commands([
        BotCommand("start", "פתיחה וחיבור החשבון"),
        BotCommand("my_searches", "החיפושים שלי"),
        BotCommand("check_now", "בדיקת מודעות עכשיו"),
        BotCommand("status", "מצב הבוט"),
        BotCommand("help", "עזרה ופקודות"),
    ])
    await _runtime_update(
        state="starting",
        last_heartbeat_at=datetime.now(timezone.utc).isoformat(),
        version=os.getenv("BOT_VERSION", "dev"),
        host_name=socket.gethostname()[:120],
        **_runtime_counters,
    )


def main():
    token = config.TELEGRAM_TOKEN
    if not token:
        logger.error("❌ TELEGRAM_TOKEN לא מוגדר")
        sys.exit(1)

    api_port = int(os.getenv("API_PORT", os.getenv("PORT", "8080")))
    start_api_thread(api_port)
    logger.info(f"🌐 API thread started on port {api_port}")

    app = Application.builder().token(token).post_init(_post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("my_searches", my_searches))
    app.add_handler(CommandHandler("check_now", check_now))
    app.add_handler(CommandHandler("clear_history", clear_history))
    app.add_handler(CommandHandler("debug_now", debug_now))
    app.add_handler(CommandHandler("debug_search", debug_search))
    app.add_handler(CommandHandler("logs", logs_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("my_id", my_id))
    app.add_handler(CommandHandler("admin_debug", admin_debug))
    app.add_handler(CommandHandler("admin_reset", admin_reset))
    app.add_handler(CallbackQueryHandler(view_search, pattern="^view_"))
    app.add_handler(CallbackQueryHandler(check_single, pattern="^chk_"))
    app.add_handler(CallbackQueryHandler(pause_search, pattern="^pause_"))
    app.add_handler(CallbackQueryHandler(back_to_list, pattern="^back_to_list$"))
    app.add_error_handler(_error_handler)

    interval = config.POLL_INTERVAL_MINUTES * 60
    app.job_queue.run_repeating(poll_all_searches, interval=interval, first=30)
    app.job_queue.run_repeating(welcome_new_searches, interval=60, first=10)
    app.job_queue.run_repeating(process_admin_jobs, interval=5, first=5)
    app.job_queue.run_repeating(heartbeat, interval=30, first=2)

    logger.info(f"🚀 Bot started! Polling every {config.POLL_INTERVAL_MINUTES} minutes.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

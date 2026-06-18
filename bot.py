#!/usr/bin/env python3
"""
Yad2 Car Search Telegram Bot
Searches are created on the website; the bot links users by email and sends alerts.
"""

import asyncio
import io
import logging
import os
import re
import sys
from collections import defaultdict
from datetime import datetime
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import Conflict
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
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

config = Config()
sb = SupabaseManager()
scraper = Yad2Scraper()


def esc(text: str) -> str:
    """Escape special characters for MarkdownV2."""
    return re.sub(r'([_*\[\]()~`>#+\-=|{}.!\\])', r'\\\1', str(text))


def _safe(s) -> str:
    """Strip Markdown-special chars from dynamic content (titles, cities, trims)."""
    return str(s or "").replace("*", "").replace("_", "").replace("`", "").replace("[", "").replace("]", "")

# context.user_data key: True = waiting for user to type their email
WAITING_EMAIL = "waiting_for_email"


# ── /start ────────────────────────────────────────────────────────────────────

SITE_URL = "https://carconnoisseur-web.vercel.app"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = str(update.effective_chat.id)
    profile = await asyncio.to_thread(sb.get_profile_by_chat, chat_id)

    if profile:
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
        # Send up to 10 current listings for each search immediately
        for s in searches:
            try:
                new_listings, was_first_run, ids_to_mark = await _fetch_new(s)
                if new_listings:
                    await update.message.reply_text(f"🚗 *{s['name']}* — {len(new_listings)} מודעות עכשיו:", parse_mode="Markdown")
                    sent_ids = []
                    for listing in new_listings:
                        try:
                            await send_listing(context.bot, int(chat_id), listing, s["name"], is_welcome=was_first_run)
                            sent_ids.append(listing["id"])
                        except Exception as se:
                            logger.error(f"send failed {listing['id']} → {chat_id}: {se}")
                    if sent_ids:
                        await asyncio.to_thread(sb.mark_seen, s["id"], sent_ids)
            except Exception as e:
                logger.error(f"start fetch error for {s.get('id')}: {e}")
    else:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🌐 פתח את האתר", url=SITE_URL)
        ]])
        await update.message.reply_text(
            f"👋 שלום {user.first_name}, ברוך הבא ל-*CarConnoisseur*!\n\n"
            "🚗 *מה זה?*\n"
            "בוט שסורק את יד2 כל 15 דקות ושולח לך התראה ישירות לטלגרם כשמודעת רכב חדשה תואמת לחיפוש שלך.\n\n"
            "━━━━━━━━━━━━━━━\n"
            "*איך מתחילים?*\n\n"
            "1️⃣ היכנס לאתר וצור חשבון חינם\n"
            "2️⃣ הגדר את החיפושים שלך\n"
            "3️⃣ חזור לכאן ושלח לי את כתובת המייל שלך לחיבור החשבון\n\n"
            "👇 לחץ כדי לפתוח את האתר:",
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
        context.user_data[WAITING_EMAIL] = True
        await update.message.reply_text(
            "📧 *שלח לי את המייל שלך* כדי לחבר את החשבון:",
            parse_mode="Markdown",
        )


# ── Handle email input ────────────────────────────────────────────────────────

async def handle_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get(WAITING_EMAIL):
        return  # not waiting for email — ignore

    email = update.message.text.strip().lower()
    chat_id = str(update.effective_chat.id)

    if "@" not in email or "." not in email:
        await update.message.reply_text(
            "❌ זה לא נראה כמו כתובת מייל תקינה. נסה שוב:"
        )
        return

    await update.message.reply_text("🔄 מחפש את החשבון...")

    found = await asyncio.to_thread(sb.link_email, chat_id, email)
    context.user_data[WAITING_EMAIL] = False

    if not found:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🌐 הרשם לאתר", url=SITE_URL)
        ]])
        await update.message.reply_text(
            f"❌ לא נמצא חשבון עם המייל *{email}*\n\n"
            "ייתכן שעדיין לא נרשמת לאתר, או שהמייל שגוי.\n\n"
            "👇 הירשם באתר ואז חזור ושלח שוב את המייל:",
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
        return

    searches = await asyncio.to_thread(sb.get_searches, chat_id)
    count = len(searches)
    count_str = f"{count} חיפושים" if count != 1 else "חיפוש אחד"
    await update.message.reply_text(
        "🎉 *החשבון חובר בהצלחה!*\n\n"
        f"📧 {email}\n"
        f"🔍 נמצאו {count_str} פעילים\n\n"
        "מעכשיו תקבל התראה ישירות לכאן בכל פעם שמודעה חדשה תואמת לחיפוש שלך.\n\n"
        "━━━━━━━━━━━━━━━\n"
        "לניהול חיפושים נוספים — היכנס לאתר:\n"
        f"{SITE_URL}",
        parse_mode="Markdown",
    )

    # Send 10 most recent listings immediately after linking
    for s in searches:
        new_listings, was_first_run, ids_to_mark = await _fetch_new(s)
        if new_listings:
            await update.message.reply_text(
                f"🚗 *{s['name']}* — {len(new_listings)} מודעות עכשיו:",
                parse_mode="Markdown",
            )
            sent_ids = []
            for listing in new_listings:
                try:
                    await send_listing(context.bot, int(chat_id), listing, s["name"], is_welcome=was_first_run)
                    sent_ids.append(listing["id"])
                except Exception as se:
                    logger.error(f"send failed {listing['id']} → {chat_id}: {se}")
            if sent_ids:
                await asyncio.to_thread(sb.mark_seen, s["id"], sent_ids)


# ── /my_searches ──────────────────────────────────────────────────────────────

async def my_searches(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    profile = await asyncio.to_thread(sb.get_profile_by_chat, chat_id)

    if not profile:
        context.user_data[WAITING_EMAIL] = True
        await update.message.reply_text(
            "⚠️ חשבונך אינו מחובר עדיין.\n\nשלח לי את כתובת המייל שלך:"
        )
        return

    searches = await asyncio.to_thread(sb.get_searches, chat_id)
    if not searches:
        await update.message.reply_text(
            "📭 אין לך חיפושים שמורים.\n\n"
            "כנס לאתר carconnoisseur-web.vercel.app להוספת חיפוש 🚗"
        )
        return

    keyboard = []
    for s in searches:
        keyboard.append([InlineKeyboardButton(f"🔍 {s['name']}", callback_data=f"view_{s['id']}")])
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

    keyboard = [
        [
            InlineKeyboardButton("🔄 בדוק עכשיו", callback_data=f"chk_{sid}"),
        ],
        [InlineKeyboardButton("« חזרה", callback_data="back_to_list")],
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
                await send_listing(context.bot, int(chat_id), listing, s["name"], is_welcome=was_first_run)
                sent_ids.append(listing["id"])
            except Exception as se:
                logger.error(f"send failed {listing['id']} → {chat_id}: {se}")
        if sent_ids:
            await asyncio.to_thread(sb.mark_seen, s["id"], sent_ids)
        await context.bot.send_message(int(chat_id), f"✅ נמצאו {len(new_listings)} מודעות חדשות!")
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
    await query.edit_message_text(
        f"📋 *החיפושים שלך* ({len(searches)}):",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ── /check_now ────────────────────────────────────────────────────────────────

async def check_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    profile = await asyncio.to_thread(sb.get_profile_by_chat, chat_id)
    if not profile:
        context.user_data[WAITING_EMAIL] = True
        await update.message.reply_text("⚠️ חשבונך אינו מחובר. שלח לי את המייל שלך:")
        return

    searches = await asyncio.to_thread(sb.get_searches, chat_id)
    if not searches:
        await update.message.reply_text("📭 אין חיפושים. הוסף חיפוש באתר.")
        return

    await update.message.reply_text(f"🔄 בודק {len(searches)} חיפושים...")
    total = 0
    for s in searches:
        try:
            new_listings, was_first_run, ids_to_mark = await _fetch_new(s)
            sent_ids = []
            for listing in new_listings[:15]:
                try:
                    await send_listing(context.bot, int(chat_id), listing, s["name"], is_welcome=was_first_run)
                    sent_ids.append(listing["id"])
                    total += 1
                except Exception as se:
                    logger.error(f"send failed {listing['id']} → {chat_id}: {se}")
            if sent_ids:
                await asyncio.to_thread(sb.mark_seen, s["id"], sent_ids)
            if not new_listings:
                await update.message.reply_text(f"😴 *{s['name']}* – אין מודעות חדשות.", parse_mode="Markdown")
        except Exception as e:
            logger.error(f"check_now error for {s['id']}: {e}", exc_info=True)
    if total:
        await update.message.reply_text(f"✅ נמצאו {total} מודעות חדשות!")


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
            fresh = [l for l in matching if scraper._is_recent(l.get("listing_date"))]
            # Pick the 10 most recent, then reverse so we send oldest → newest
            fresh.sort(key=lambda l: scraper._parse_listing_date(l.get("listing_date")) or datetime.min, reverse=True)
            top10 = fresh[:10]
            to_send = _apply_km_filter(await scraper.enrich_with_km(top10), search)
            to_send.sort(key=lambda l: scraper._parse_listing_date(l.get("listing_date")) or datetime.min)
            # Seed baseline even if empty, so welcome loop doesn't repeat for zero-result searches
            await asyncio.to_thread(
                sb.mark_seen, sid,
                [l["id"] for l in matching], seen_ids_list or [],
                price_map if matching else None, seen_prices,
                True,  # force_write
            )
            logger.info(f"First run {sid}: {len(matching)} matching, {len(fresh)} recent → {len(to_send)} sent")
            if to_send:
                try:
                    await bot.send_message(
                        int(chat_id),
                        f"📋 *{search['name']}* — {len(to_send)} מודעות אחרונות מהשבוע:",
                        parse_mode="Markdown",
                    )
                except Exception:
                    pass
            for listing in to_send:
                await send_listing(bot, int(chat_id), listing, search["name"], is_welcome=True)
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

        # Enrich first, then km-filter. Mark ALL enriched IDs as seen (including km-filtered
        # ones) so they aren't re-enriched every poll when they never pass the km limit.
        new_raw = await scraper.enrich_with_km(new[:15])
        price_raw = await scraper.enrich_with_km(price_changed[:10])
        new_enriched = _apply_km_filter(new_raw, search)
        price_enriched = _apply_km_filter(price_raw, search)
        to_send = new_enriched + price_enriched
        to_send_ids = {l["id"] for l in to_send}

        # Mark silently-absorbed (2-7 day gap) and km-filtered listings now —
        # they are NOT being sent so it is safe to mark them immediately.
        # Listings that WILL be sent are marked only after successful delivery
        # so a send failure doesn't permanently lose them.
        ids_mark_now = list(
            ({l["id"] for l in unseen_7d} | {l["id"] for l in new_raw + price_raw})
            - to_send_ids
        )
        await asyncio.to_thread(
            sb.mark_seen, sid,
            ids_mark_now, seen_ids_list,
            price_map, seen_prices,
        )

        logger.info(f"Poll {sid}: {len(matching)} matching, {len(unseen_7d)} unseen (7d), {len(new)} new (48h), {len(price_changed)} price changes → {len(to_send)} sent")
        sent_ids = []
        for listing in to_send:
            try:
                await send_listing(bot, int(chat_id), listing, search["name"])
                sent_ids.append(listing["id"])
            except Exception as e:
                logger.error(f"send failed {listing['id']} → {chat_id}: {e}")
        if sent_ids:
            await asyncio.to_thread(sb.mark_seen, sid, sent_ids)


async def poll_all_searches(context: ContextTypes.DEFAULT_TYPE):
    logger.info("⏱ Running scheduled poll...")
    try:
        all_searches = await asyncio.to_thread(sb.get_all_searches)
        logger.info(f"Poll: {len(all_searches)} searches")

        # New (unseeded) searches are handled by welcome_new_searches — skip them here
        seeded = [(chat_id, s) for chat_id, s in all_searches if s.get("seen_ids") is not None]

        # Group by manufacturer so each manufacturer is fetched from yad2 only once
        by_mfr: dict[str, list[tuple[str, dict]]] = defaultdict(list)
        no_mfr: list[tuple[str, dict]] = []
        for chat_id, s in seeded:
            mfr = (s.get("manufacturer") or "").strip()
            if mfr:
                by_mfr[mfr].append((chat_id, s))
            else:
                no_mfr.append((chat_id, s))

        logger.info(f"Poll: {len(by_mfr)} unique manufacturers, {len(no_mfr)} no-manufacturer searches")

        fetch_sem = asyncio.Semaphore(5)    # max 5 concurrent yad2 fetches
        process_sem = asyncio.Semaphore(10)  # max 10 concurrent per-search processing tasks

        async def _process_one(chat_id: str, s: dict, listings: list):
            async with process_sem:
                await _process_search_with_listings(context.bot, chat_id, s, listings)

        async def _fetch_and_process_mfr(mfr: str, group: list):
            async with fetch_sem:
                try:
                    listings, _ = await scraper.fetch_listings({"manufacturer": mfr})
                except Exception as e:
                    logger.error(f"Poll fetch failed for mfr={mfr}: {e}")
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
                    await send_listing(context.bot, int(chat_id), listing, s["name"], is_welcome=was_first_run)
                    sent_ids.append(listing["id"])
                    logger.info(f"Sent {listing['id']} to {chat_id}")
                except Exception as e:
                    logger.error(f"send failed {listing['id']} → {chat_id}: {e}")
            if sent_ids:
                await asyncio.to_thread(sb.mark_seen, s["id"], sent_ids)

        tasks = [_fetch_and_process_mfr(mfr, group) for mfr, group in by_mfr.items()]
        tasks += [_process_no_mfr(chat_id, s) for chat_id, s in no_mfr]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, res in enumerate(results):
            if isinstance(res, Exception):
                logger.error(f"Poll task {i} failed: {res}", exc_info=(type(res), res, res.__traceback__))

        if _active_search_ids is not None:
            for sid in list(_fetch_locks.keys()):
                if sid not in _active_search_ids:
                    del _fetch_locks[sid]

    except Exception as e:
        logger.error(f"poll_all_searches crashed: {e}", exc_info=True)


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

        price_map = {l["id"]: l["price"] for l in listings if l.get("price") is not None}

        if is_first_run:
            # Seed ALL listings immediately — this is the intentional first-run baseline.
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
            fresh = [l for l in listings if scraper._is_recent(l.get("listing_date"))]
            fresh.sort(key=lambda l: scraper._parse_listing_date(l.get("listing_date")) or datetime.min, reverse=True)
            logger.info(f"First run {sid}: {len(listings)} total, {len(fresh)} recent → sending top 10")
            return _apply_km_filter(await scraper.enrich_with_km(fresh[:10]), search), True, []

        # Steady-state — compute new/price-changed BEFORE any mark_seen call
        new = [l for l in listings if l["id"] not in seen and scraper._is_recent(l.get("listing_date"))]

        price_changed = []
        for l in listings:
            if l["id"] in seen and l.get("price") is not None:
                old_price = seen_prices.get(l["id"])
                if old_price is not None and l["price"] != old_price:
                    l["_price_change"] = {"old": old_price, "new": l["price"]}
                    price_changed.append(l)

        result = _apply_km_filter(await scraper.enrich_with_km(new[:15]), search)
        result += _apply_km_filter(await scraper.enrich_with_km(price_changed[:10]), search)

        # Mark background listings (already-seen, not pending send) immediately
        to_send_ids = {l["id"] for l in result}
        background_ids = [l["id"] for l in listings if l["id"] not in to_send_ids]
        if background_ids:
            await asyncio.to_thread(
                sb.mark_seen, sid,
                background_ids, seen_ids_list or [],
                price_map, seen_prices,
            )

        logger.info(f"Poll {sid}: {len(listings)} fetched, {len(new)} new, {len(price_changed)} price changes → {len(result)} to send")
        return result, False, [l["id"] for l in result]


# ── send_listing ──────────────────────────────────────────────────────────────

async def send_listing(bot, chat_id: int, listing: dict, search_name: str, is_welcome: bool = False):
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
    contact_phone = listing.get("contact_phone") or ""
    contact_name  = listing.get("contact_name") or ""
    photo_url   = listing.get("photo_url")

    header = _safe(title)
    if trim:
        header += f" | {_safe(trim)}"

    engine_str = ""
    if engine_cc:
        liters = round(engine_cc / 1000, 1)
        engine_str = str(liters)
        if engine_type:
            engine_str += f" {_safe(engine_type)}"
        if turbo:
            engine_str += " טורבו"
        if horsepower:
            engine_str += f" ({horsepower} כ\"ס)"

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
    elif is_welcome:
        listing_header = "📋 *מודעה אחרונה*"
    else:
        listing_header = "🚗 *מודעה חדשה!*"

    lines = [
        listing_header,
        header,
        f"🔹 שנה: {year}",
        f"🔹 יד: {_safe(hand_text)}",
        f"🔹 בעלות: {_safe(ownership)}",
        f"🔹 קילומטראז': {km:,} ק\"מ" if km is not None else "🔹 קילומטראז': —",
    ]
    if engine_str:
        lines.append(f"🔹 נפח מנוע: {engine_str}")
    if test_date:
        lines.append(f"🔹 טסט עד: {_safe(test_date)}")
    if price_change:
        lines.append(price_header)
    else:
        lines.append(f"💰 מחיר מבוקש: {price:,} ₪" if price else "💰 מחיר: לא צוין")
    lines.append(f"📍 אזור מכירה: {_safe(city)}")
    if description:
        lines.append(f"✨ תוספות: {_safe(description)}")
    if contact_phone:
        contact_line = f"📞 {_safe(contact_phone)}"
        if contact_name:
            contact_line += f" {_safe(contact_name)}"
        lines.append(contact_line)

    text = "\n".join(l for l in lines if l is not None)
    if len(text) > 1020:
        text = text[:1020] + "..."

    keyboard = [[InlineKeyboardButton("🔗 למעבר למודעה המקורית לחץ כאן", url=listing["url"])]]
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


# ── Misc commands ─────────────────────────────────────────────────────────────

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 *פקודות:*\n\n"
        "*/my\\_searches* – החיפושים שלי\n"
        "*/check\\_now* – בדוק עכשיו\n"
        "*/status* – סטטוס הבוט\n"
        "*/clear\\_history* – אפס היסטוריה (שלח שוב מודעות ישנות)\n\n"
        f"⏱ הבוט בודק אוטומטית כל *{config.POLL_INTERVAL_MINUTES}* דקות.\n"
        "🌐 חיפושים מנוהלים באתר: carconnoisseur-web.vercel.app",
        parse_mode="Markdown",
    )


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    profiles = await asyncio.to_thread(sb.get_all_linked_profiles)
    total = 0
    for p in profiles:
        searches = await asyncio.to_thread(sb.get_searches, p["telegram_chat_id"])
        total += len(searches)
    await update.message.reply_text(
        f"✅ *הבוט פעיל*\n\n"
        f"👥 משתמשים מחוברים: {len(profiles)}\n"
        f"🔍 סה\"כ חיפושים: {total}\n"
        f"⏱ סריקה כל {config.POLL_INTERVAL_MINUTES} דקות",
        parse_mode="Markdown",
    )


async def clear_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    searches = await asyncio.to_thread(sb.get_searches, chat_id)
    if not searches:
        await update.message.reply_text("אין חיפושים שמורים.")
        return

    def _do_clear():
        from supabase_manager import SUPABASE_URL, _headers
        import httpx
        for s in searches:
            httpx.patch(
                f"{SUPABASE_URL}/rest/v1/searches",
                headers=_headers(),
                params={"id": f"eq.{s['id']}"},
                json={"seen_ids": None},
                timeout=10,
            )

    await asyncio.to_thread(_do_clear)
    await update.message.reply_text(
        f"🗑 היסטוריה אופסה ל-{len(searches)} חיפושים.\n"
        "בבדיקה הבאה הבוט ישלח את המודעות העדכניות.",
    )


async def logs_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
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


# ── Welcome batch for new searches (runs every 60s) ──────────────────────────

async def welcome_new_searches(context: ContextTypes.DEFAULT_TYPE):
    """Welcome batch for new searches + deletion detection (runs every 60s).

    Uses the same manufacturer-based fetch as poll_all_searches so that seeding
    covers the full result set. This prevents poll_all_searches (running 20s later)
    from finding the same listings again as 'new' due to URL mismatch.
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

        # No-manufacturer searches: use _fetch_new (search-specific URL is fine here)
        for chat_id, s in no_mfr:
            try:
                listings, _, ids_to_mark = await _fetch_new(s)
                # Sort oldest→newest so the most recent listing lands last
                listings.sort(key=lambda l: scraper._parse_listing_date(l.get("listing_date")) or datetime.min)
                if listings:
                    await context.bot.send_message(
                        int(chat_id),
                        f"📋 *{s['name']}* — {len(listings)} מודעות אחרונות מהשבוע:",
                        parse_mode="Markdown",
                    )
                sent_ids = []
                for listing in listings:
                    try:
                        await send_listing(context.bot, int(chat_id), listing, s["name"], is_welcome=True)
                        sent_ids.append(listing["id"])
                    except Exception as se:
                        logger.error(f"send failed {listing['id']} → {chat_id}: {se}")
                if sent_ids:
                    await asyncio.to_thread(sb.mark_seen, s["id"], sent_ids)
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
        "הבוט ישלח את המודעות האחרונות בסריקה הבאה."
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
    app.add_handler(CallbackQueryHandler(back_to_list, pattern="^back_to_list$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_email))
    app.add_error_handler(_error_handler)

    interval = config.POLL_INTERVAL_MINUTES * 60
    app.job_queue.run_repeating(poll_all_searches, interval=interval, first=30)
    app.job_queue.run_repeating(welcome_new_searches, interval=60, first=10)

    logger.info(f"🚀 Bot started! Polling every {config.POLL_INTERVAL_MINUTES} minutes.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

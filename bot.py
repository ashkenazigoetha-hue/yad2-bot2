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

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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
                new_listings = await _fetch_new(s)
                if new_listings:
                    await update.message.reply_text(f"🚗 *{s['name']}* — {len(new_listings)} מודעות עכשיו:", parse_mode="Markdown")
                    for listing in new_listings:
                        await send_listing(context.bot, int(chat_id), listing, s["name"])
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
    new_listings = await _fetch_new(s)
    if new_listings:
        for listing in new_listings:
            await send_listing(context.bot, int(chat_id), listing, s["name"])
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
            new_listings = await _fetch_new(s)
            for listing in new_listings[:15]:
                await send_listing(context.bot, int(chat_id), listing, s["name"])
                total += 1
            if not new_listings:
                await update.message.reply_text(f"😴 *{s['name']}* – אין מודעות חדשות.", parse_mode="Markdown")
        except Exception as e:
            logger.error(f"check_now error for {s['id']}: {e}", exc_info=True)
    if total:
        await update.message.reply_text(f"✅ נמצאו {total} מודעות חדשות!")


# ── Scheduled poll ────────────────────────────────────────────────────────────

async def poll_all_searches(context: ContextTypes.DEFAULT_TYPE):
    logger.info("⏱ Running scheduled poll...")
    try:
        all_searches = await asyncio.to_thread(sb.get_all_searches)
        logger.info(f"Poll: {len(all_searches)} search(es) to check")
        for chat_id, s in all_searches:
            try:
                new_listings = await _fetch_new(s)
                for listing in new_listings:
                    await send_listing(context.bot, int(chat_id), listing, s["name"])
                    logger.info(f"Sent listing {listing['id']} to {chat_id}")
            except Exception as e:
                logger.error(f"Error polling search {s.get('id')} for {chat_id}: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"poll_all_searches crashed: {e}", exc_info=True)


# ── Fetch helper (replaces scraper.fetch_new_listings) ────────────────────────

_fetch_locks: dict[str, asyncio.Lock] = {}


async def _fetch_new(search: dict) -> list:
    """Fetch listings not yet seen, update seen_ids in Supabase."""
    sid = search["id"]
    # One lock per search — prevents /start and poll_all_searches running concurrently
    if sid not in _fetch_locks:
        _fetch_locks[sid] = asyncio.Lock()
    async with _fetch_locks[sid]:
        # Always read fresh seen_ids from Supabase to avoid stale cached dicts
        fresh_seen = await asyncio.to_thread(sb.get_seen_ids, sid)
        seen = set(fresh_seen or [])
        is_first_run = len(seen) == 0

        listings = await scraper.fetch_listings(search)

        if is_first_run:
            if listings:
                await asyncio.to_thread(sb.mark_seen, sid, [l["id"] for l in listings])
            return listings[:10]

        new = [l for l in listings if l["id"] not in seen]
        if new:
            await asyncio.to_thread(sb.mark_seen, sid, [l["id"] for l in new])
        return new[:15]


# ── send_listing ──────────────────────────────────────────────────────────────

async def send_listing(bot, chat_id: int, listing: dict, search_name: str):
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

    header = title
    if trim:
        header += f" | {trim}"

    engine_str = ""
    if engine_cc:
        liters = round(engine_cc / 1000, 1)
        engine_str = str(liters)
        if engine_type:
            engine_str += f" {engine_type}"
        if turbo:
            engine_str += " טורבו"
        if horsepower:
            engine_str += f" ({horsepower} כ\"ס)"

    lines = [
        "🚗 *מודעה חדשה נמצאה!* 🚗",
        header,
        f"🔹 שנה: {year}",
        f"🔹 יד: {hand_text}",
        f"🔹 בעלות: {ownership}",
        f"🔹 קילומטראז': {km:,} ק\"מ" if km else "🔹 קילומטראז': —",
    ]
    if engine_str:
        lines.append(f"🔹 נפח מנוע: {engine_str}")
    if test_date:
        lines.append(f"🔹 טסט עד: {test_date}")
    lines.append(f"💰 מחיר מבוקש: {price:,} ₪" if price else "💰 מחיר: לא צוין")
    lines.append(f"📍 אזור מכירה: {city}")
    if description:
        lines.append(f"✨ ציוד: {description}")
    if contact_phone:
        contact_line = f"📞 {contact_phone}"
        if contact_name:
            contact_line += f" {contact_name}"
        lines.append(contact_line)

    text = "\n".join(lines)
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
    total = sum(len(await asyncio.to_thread(sb.get_searches, p["telegram_chat_id"])) for p in profiles)
    await update.message.reply_text(
        f"✅ *הבוט פעיל*\n\n"
        f"👥 משתמשים מחוברים: {len(profiles)}\n"
        f"🔍 סה\"כ חיפושים: {total}\n"
        f"⏱ סריקה כל {config.POLL_INTERVAL_MINUTES} דקות",
        parse_mode="Markdown",
    )


async def clear_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import httpx
    from supabase_manager import SUPABASE_URL, _headers
    chat_id = str(update.effective_chat.id)
    searches = sb.get_searches(chat_id)
    for s in searches:
        httpx.patch(
            f"{SUPABASE_URL}/rest/v1/searches",
            headers=_headers(),
            params={"id": f"eq.{s['id']}"},
            json={"seen_ids": []},
            timeout=10,
        )
    await update.message.reply_text(
        f"🗑 היסטוריה אופסה ל-{len(searches)} חיפושים.\n"
        "בבדיקה הבאה הבוט ישלח שוב את המודעות העדכניות.",
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
        lines = [f"גולמי: {len(raw)} | אחרי סינון: {len(filtered)}\n"]
        for item in raw[:8]:
            mt = item.get("model_text", "—")
            tr = (item.get("trim") or "—")[:30]
            match = "✅" if scraper._matches_search(item, s) else "❌"
            lines.append(f"{match} [{mt}] | [{tr}]")
        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        await update.message.reply_text(f"שגיאה: {e}")


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
    start_api_thread(api_port, sm=None)
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
    app.add_handler(CallbackQueryHandler(view_search, pattern="^view_"))
    app.add_handler(CallbackQueryHandler(check_single, pattern="^chk_"))
    app.add_handler(CallbackQueryHandler(back_to_list, pattern="^back_to_list$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_email))

    interval = config.POLL_INTERVAL_MINUTES * 60
    app.job_queue.run_repeating(poll_all_searches, interval=interval, first=30)

    logger.info(f"🚀 Bot started! Polling every {config.POLL_INTERVAL_MINUTES} minutes.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

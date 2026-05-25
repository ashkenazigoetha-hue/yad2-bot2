#!/usr/bin/env python3
"""
Yad2 Car Search Telegram Bot
Monitors Yad2 for new car listings and sends Telegram notifications
"""

import asyncio
import json
import logging
import os
import re
import signal
import sys
from datetime import datetime
from pathlib import Path

import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

from config import Config
from search_manager import SearchManager
from yad2_scraper import Yad2Scraper

# Logging setup
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler("logs/bot.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# Conversation states
(
    SEARCH_NAME,
    SEARCH_MANUFACTURER,
    SEARCH_MODEL,
    SEARCH_PRICE_MIN,
    SEARCH_PRICE_MAX,
    SEARCH_YEAR_MIN,
    SEARCH_YEAR_MAX,
    SEARCH_KM_MAX,
    SEARCH_CONFIRM,
) = range(9)

config = Config()
search_manager = SearchManager(config.DATA_DIR)
scraper = Yad2Scraper()


# ─── /start ───────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = (
        f"👋 שלום {user.first_name}!\n\n"
        "🚗 *בוט חיפוש רכבים ביד 2*\n\n"
        "אני אחפש עבורך רכבים ביד2 ואשלח לך התראה כשיעלו מודעות חדשות!\n\n"
        "📋 *פקודות זמינות:*\n"
        "/add\\_search – הוסף חיפוש חדש\n"
        "/my\\_searches – הצג את החיפושים שלי\n"
        "/check\\_now – בדוק עכשיו\n"
        "/help – עזרה\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# ─── /help ────────────────────────────────────────────────────────────────────
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🆘 *עזרה*\n\n"
        "*/add\\_search* – הגדר חיפוש חדש עם פילטרים (יצרן, מחיר, שנה, ק\"מ)\n"
        "*/my\\_searches* – ראה ונהל את כל החיפושים שלך\n"
        "*/check\\_now* – הפעל בדיקה ידנית מיידית לכל החיפושים\n"
        "*/stop\\_all* – עצור את כל ההתראות\n\n"
        "⏱ הבוט בודק כל *{interval}* דקות אוטומטית.\n"
        "🔔 תקבל הודעה רק על מודעות *חדשות* שלא ראית קודם."
    ).format(interval=config.POLL_INTERVAL_MINUTES)
    await update.message.reply_text(text, parse_mode="Markdown")


# ─── Add Search Conversation ──────────────────────────────────────────────────
async def add_search_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_search"] = {}
    await update.message.reply_text(
        "🔍 *הוספת חיפוש חדש*\n\nשלב 1/8 – תן שם לחיפוש הזה (לדוגמה: \"פולו ידני\"):",
        parse_mode="Markdown",
    )
    return SEARCH_NAME


async def got_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_search"]["name"] = update.message.text.strip()
    await update.message.reply_text(
        "🏭 שלב 2/8 – *יצרן* (לדוגמה: `toyota`, `honda`, `mazda`)\nאו שלח /skip לדלג:",
        parse_mode="Markdown",
    )
    return SEARCH_MANUFACTURER


async def got_manufacturer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_search"]["manufacturer"] = update.message.text.strip()
    await update.message.reply_text(
        "🚘 שלב 3/8 – *דגם* (לדוגמה: `corolla`, `civic`)\nאו שלח /skip לדלג:",
        parse_mode="Markdown",
    )
    return SEARCH_MODEL


async def got_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_search"]["model"] = update.message.text.strip()
    await update.message.reply_text(
        "💰 שלב 4/8 – *מחיר מינימלי* (₪)\nאו שלח /skip לדלג:",
        parse_mode="Markdown",
    )
    return SEARCH_PRICE_MIN


async def got_price_min(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip()
    if not val.isdigit():
        await update.message.reply_text("⚠️ אנא הכנס מספר בלבד:")
        return SEARCH_PRICE_MIN
    context.user_data["new_search"]["price_min"] = int(val)
    await update.message.reply_text(
        "💰 שלב 5/8 – *מחיר מקסימלי* (₪)\nאו שלח /skip לדלג:",
        parse_mode="Markdown",
    )
    return SEARCH_PRICE_MAX


async def got_price_max(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip()
    if not val.isdigit():
        await update.message.reply_text("⚠️ אנא הכנס מספר בלבד:")
        return SEARCH_PRICE_MAX
    context.user_data["new_search"]["price_max"] = int(val)
    await update.message.reply_text(
        "📅 שלב 6/8 – *שנת ייצור מינימלית* (לדוגמה: `2018`)\nאו שלח /skip לדלג:",
        parse_mode="Markdown",
    )
    return SEARCH_YEAR_MIN


async def got_year_min(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip()
    if not val.isdigit() or not (1990 <= int(val) <= 2025):
        await update.message.reply_text("⚠️ אנא הכנס שנה תקינה (1990-2025):")
        return SEARCH_YEAR_MIN
    context.user_data["new_search"]["year_min"] = int(val)
    await update.message.reply_text(
        "📅 שלב 7/8 – *שנת ייצור מקסימלית*\nאו שלח /skip לדלג:",
        parse_mode="Markdown",
    )
    return SEARCH_YEAR_MAX


async def got_year_max(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip()
    if not val.isdigit() or not (1990 <= int(val) <= 2025):
        await update.message.reply_text("⚠️ אנא הכנס שנה תקינה (1990-2025):")
        return SEARCH_YEAR_MAX
    context.user_data["new_search"]["year_max"] = int(val)
    await update.message.reply_text(
        "🛣 שלב 8/8 – *קילומטראז' מקסימלי* (לדוגמה: `150000`)\nאו שלח /skip לדלג:",
        parse_mode="Markdown",
    )
    return SEARCH_KM_MAX


async def got_km_max(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip()
    if not val.isdigit():
        await update.message.reply_text("⚠️ אנא הכנס מספר בלבד:")
        return SEARCH_KM_MAX
    context.user_data["new_search"]["km_max"] = int(val)
    return await show_search_summary(update, context)


async def skip_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /skip – figure out which state we're in and advance."""
    # peek at current state via conversation handler
    # We just move forward by calling the "got_X" with None stored
    state_map = {
        SEARCH_MANUFACTURER: (SEARCH_MODEL, "🚘 שלב 3/8 – *דגם*\nאו שלח /skip לדלג:"),
        SEARCH_MODEL: (SEARCH_PRICE_MIN, "💰 שלב 4/8 – *מחיר מינימלי* (₪)\nאו שלח /skip לדלג:"),
        SEARCH_PRICE_MIN: (SEARCH_PRICE_MAX, "💰 שלב 5/8 – *מחיר מקסימלי* (₪)\nאו שלח /skip לדלג:"),
        SEARCH_PRICE_MAX: (SEARCH_YEAR_MIN, "📅 שלב 6/8 – *שנת ייצור מינימלית*\nאו שלח /skip לדלג:"),
        SEARCH_YEAR_MIN: (SEARCH_YEAR_MAX, "📅 שלב 7/8 – *שנת ייצור מקסימלית*\nאו שלח /skip לדלג:"),
        SEARCH_YEAR_MAX: (SEARCH_KM_MAX, "🛣 שלב 8/8 – *קילומטראז' מקסימלי*\nאו שלח /skip לדלג:"),
        SEARCH_KM_MAX: (None, None),
    }
    # We store current state in user_data so skip can know where we are
    current = context.user_data.get("_state", SEARCH_MANUFACTURER)
    nxt, msg = state_map.get(current, (None, None))
    if nxt is None:
        return await show_search_summary(update, context)
    context.user_data["_state"] = nxt
    await update.message.reply_text(msg, parse_mode="Markdown")
    return nxt


async def show_search_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = context.user_data["new_search"]
    lines = [f"✅ *סיכום החיפוש:*\n", f"📌 שם: *{s.get('name', '—')}*"]
    if s.get("manufacturer"):
        lines.append(f"🏭 יצרן: {s['manufacturer']}")
    if s.get("model"):
        lines.append(f"🚘 דגם: {s['model']}")
    if s.get("price_min") or s.get("price_max"):
        mn = f"₪{s['price_min']:,}" if s.get("price_min") else "ללא הגבלה"
        mx = f"₪{s['price_max']:,}" if s.get("price_max") else "ללא הגבלה"
        lines.append(f"💰 מחיר: {mn} – {mx}")
    if s.get("year_min") or s.get("year_max"):
        lines.append(f"📅 שנה: {s.get('year_min','—')} – {s.get('year_max','—')}")
    if s.get("km_max"):
        lines.append(f"🛣 ק\"מ מקס': {s['km_max']:,}")

    keyboard = [
        [
            InlineKeyboardButton("✅ שמור", callback_data="save_search"),
            InlineKeyboardButton("❌ בטל", callback_data="cancel_search"),
        ]
    ]
    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return SEARCH_CONFIRM


async def confirm_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "save_search":
        user_id = str(query.from_user.id)
        search = context.user_data["new_search"]
        search_manager.add_search(user_id, search)
        await query.edit_message_text(
            f"✅ החיפוש *{search['name']}* נשמר!\n\n"
            "אני אשלח לך התראה כשימצאו מודעות חדשות 🔔",
            parse_mode="Markdown",
        )
    else:
        await query.edit_message_text("❌ החיפוש בוטל.")
    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ הפעולה בוטלה.")
    return ConversationHandler.END


# ─── /my_searches ─────────────────────────────────────────────────────────────
async def my_searches(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    searches = search_manager.get_searches(user_id)
    if not searches:
        await update.message.reply_text(
            "📭 אין לך חיפושים שמורים.\nהשתמש ב-/add\\_search להוסיף!", parse_mode="Markdown"
        )
        return

    keyboard = []
    for sid, s in searches.items():
        label = f"🔍 {s['name']}"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"view_{sid}")])

    await update.message.reply_text(
        f"📋 *החיפושים שלך* ({len(searches)}):",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def view_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = str(query.from_user.id)
    sid = query.data.replace("view_", "")
    searches = search_manager.get_searches(user_id)
    s = searches.get(sid)
    if not s:
        await query.edit_message_text("❌ החיפוש לא נמצא.")
        return

    lines = [f"🔍 *{s['name']}*\n"]
    if s.get("manufacturer"):
        lines.append(f"🏭 יצרן: {s['manufacturer']}")
    if s.get("model"):
        lines.append(f"🚘 דגם: {s['model']}")
    if s.get("price_min") or s.get("price_max"):
        mn = f"₪{s['price_min']:,}" if s.get("price_min") else "ללא"
        mx = f"₪{s['price_max']:,}" if s.get("price_max") else "ללא"
        lines.append(f"💰 מחיר: {mn} – {mx}")
    if s.get("year_min") or s.get("year_max"):
        lines.append(f"📅 שנה: {s.get('year_min','—')} – {s.get('year_max','—')}")
    if s.get("km_max"):
        lines.append(f"🛣 ק\"מ מקס': {s['km_max']:,}")
    seen = len(s.get("seen_ids", []))
    lines.append(f"\n👁 מודעות שנראו: {seen}")

    keyboard = [
        [
            InlineKeyboardButton("🗑 מחק חיפוש", callback_data=f"del_{sid}"),
            InlineKeyboardButton("🔄 בדוק עכשיו", callback_data=f"chk_{sid}"),
        ],
        [InlineKeyboardButton("« חזרה", callback_data="back_to_list")],
    ]
    await query.edit_message_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def delete_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = str(query.from_user.id)
    sid = query.data.replace("del_", "")
    searches = search_manager.get_searches(user_id)
    name = searches.get(sid, {}).get("name", "")
    search_manager.delete_search(user_id, sid)
    await query.edit_message_text(f"🗑 החיפוש *{name}* נמחק.", parse_mode="Markdown")


async def check_single(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("🔄 בודק...")
    user_id = str(query.from_user.id)
    sid = query.data.replace("chk_", "")
    searches = search_manager.get_searches(user_id)
    s = searches.get(sid)
    if not s:
        await query.edit_message_text("❌ החיפוש לא נמצא.")
        return
    await query.edit_message_text(f"🔄 בודק את *{s['name']}*...", parse_mode="Markdown")
    new_listings = await scraper.fetch_new_listings(s, search_manager, user_id, sid)
    if new_listings:
        for listing in new_listings:
            await send_listing(context.bot, int(user_id), listing, s["name"])
        await context.bot.send_message(
            int(user_id), f"✅ נמצאו {len(new_listings)} מודעות חדשות!"
        )
    else:
        await context.bot.send_message(int(user_id), "😴 אין מודעות חדשות כרגע.")


async def back_to_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = str(query.from_user.id)
    searches = search_manager.get_searches(user_id)
    if not searches:
        await query.edit_message_text("📭 אין חיפושים שמורים.")
        return
    keyboard = []
    for sid, s in searches.items():
        keyboard.append([InlineKeyboardButton(f"🔍 {s['name']}", callback_data=f"view_{sid}")])
    await query.edit_message_text(
        f"📋 *החיפושים שלך* ({len(searches)}):",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ─── /check_now ──────────────────────────────────────────────────────────────
async def check_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    searches = search_manager.get_searches(user_id)
    if not searches:
        await update.message.reply_text("📭 אין לך חיפושים. השתמש ב-/add\\_search", parse_mode="Markdown")
        return
    await update.message.reply_text(f"🔄 בודק {len(searches)} חיפושים...")
    total = 0
    for sid, s in searches.items():
        new_listings = await scraper.fetch_new_listings(s, search_manager, user_id, sid)
        for listing in new_listings:
            await send_listing(context.bot, int(user_id), listing, s["name"])
            total += 1
    msg = f"✅ נמצאו {total} מודעות חדשות!" if total else "😴 אין מודעות חדשות."
    await update.message.reply_text(msg)


# ─── Polling Job ──────────────────────────────────────────────────────────────
async def poll_all_searches(context: ContextTypes.DEFAULT_TYPE):
    """Called periodically to check all searches for all users."""
    logger.info("⏱ Running scheduled poll...")
    all_users = search_manager.get_all_users()
    for user_id in all_users:
        searches = search_manager.get_searches(user_id)
        for sid, s in searches.items():
            try:
                new_listings = await scraper.fetch_new_listings(s, search_manager, user_id, sid)
                for listing in new_listings:
                    await send_listing(context.bot, int(user_id), listing, s["name"])
                    logger.info(f"Sent listing {listing['id']} to user {user_id}")
            except Exception as e:
                logger.error(f"Error polling search {sid} for user {user_id}: {e}")


# ─── Listing Notification ─────────────────────────────────────────────────────
async def send_listing(bot, chat_id: int, listing: dict, search_name: str):
    price = f"₪{listing['price']:,}" if listing.get("price") else "מחיר לא ידוע"
    year = listing.get("year", "—")
    km = f"{listing['km']:,} ק\"מ" if listing.get("km") else "—"
    city = listing.get("city", "—")
    title = listing.get("title", "רכב")

    text = (
        f"🚗 *מודעה חדשה – {search_name}*\n\n"
        f"📋 *{title}*\n"
        f"💰 מחיר: {price}\n"
        f"📅 שנה: {year}\n"
        f"🛣 ק\"מ: {km}\n"
        f"📍 עיר: {city}\n"
    )
    keyboard = [[InlineKeyboardButton("🔗 פתח ביד2", url=listing["url"])]]
    try:
        await bot.send_message(
            chat_id,
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    except Exception as e:
        logger.error(f"Failed to send listing to {chat_id}: {e}")


# ─── /stop_all ────────────────────────────────────────────────────────────────
async def stop_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    count = search_manager.delete_all_searches(user_id)
    await update.message.reply_text(f"🛑 כל {count} החיפושים נמחקו.")


# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    token = config.TELEGRAM_TOKEN
    if not token:
        logger.error("❌ TELEGRAM_TOKEN לא מוגדר ב-.env")
        sys.exit(1)

    app = Application.builder().token(token).build()

    # Conversation for adding a search
    conv = ConversationHandler(
        entry_points=[CommandHandler("add_search", add_search_start)],
        states={
            SEARCH_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_name)],
            SEARCH_MANUFACTURER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, got_manufacturer),
                CommandHandler("skip", skip_step),
            ],
            SEARCH_MODEL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, got_model),
                CommandHandler("skip", skip_step),
            ],
            SEARCH_PRICE_MIN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, got_price_min),
                CommandHandler("skip", skip_step),
            ],
            SEARCH_PRICE_MAX: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, got_price_max),
                CommandHandler("skip", skip_step),
            ],
            SEARCH_YEAR_MIN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, got_year_min),
                CommandHandler("skip", skip_step),
            ],
            SEARCH_YEAR_MAX: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, got_year_max),
                CommandHandler("skip", skip_step),
            ],
            SEARCH_KM_MAX: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, got_km_max),
                CommandHandler("skip", skip_step),
            ],
            SEARCH_CONFIRM: [CallbackQueryHandler(confirm_search, pattern="^(save|cancel)_search$")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("my_searches", my_searches))
    app.add_handler(CommandHandler("check_now", check_now))
    app.add_handler(CommandHandler("stop_all", stop_all))
    app.add_handler(conv)

    # Callback query handlers
    app.add_handler(CallbackQueryHandler(view_search, pattern="^view_"))
    app.add_handler(CallbackQueryHandler(delete_search, pattern="^del_"))
    app.add_handler(CallbackQueryHandler(check_single, pattern="^chk_"))
    app.add_handler(CallbackQueryHandler(back_to_list, pattern="^back_to_list$"))

    # Polling job
    interval = config.POLL_INTERVAL_MINUTES * 60
    app.job_queue.run_repeating(poll_all_searches, interval=interval, first=30)

    logger.info(f"🚀 Bot started! Polling every {config.POLL_INTERVAL_MINUTES} minutes.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

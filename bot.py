#!/usr/bin/env python3
"""
Yad2 Car Search Telegram Bot
"""

import asyncio
import logging
import os
import sys

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

(
    SEARCH_NAME, SEARCH_MANUFACTURER, SEARCH_MODEL,
    SEARCH_PRICE_MIN, SEARCH_PRICE_MAX, SEARCH_YEAR_MIN,
    SEARCH_YEAR_MAX, SEARCH_KM_MAX, SEARCH_CONFIRM,
) = range(9)

MANUFACTURERS = [
    "טויוטה", "הונדה", "מאזדה", "יונדאי", "קיה", "פולקסווגן",
    "פורד", "סובארו", "ניסאן", "סוזוקי", "סיאט", "סקודה",
    "רנו", "פיג'ו", "סיטרואן", "ב.מ.וו", "מרצדס", "אאודי",
    "אופל", "פיאט", "וולוו", "מיצובישי", "שברולט", "מיני",
    "ג'יפ", "לקסוס", "לנד רובר", "טסלה", "דאצ'יה", "אלפא רומיאו",
    "פורשה", "אינפיניטי", "יגואר", "קאדילק",
]

MODELS_BY_MANUFACTURER = {
    "טויוטה": ["קורולה", "קאמרי", "יאריס", "אוריס", "RAV4", "לנד קרוזר", "פריוס", "ח'יילנדר", "אברנסיס", "ורסו"],
    "הונדה": ["סיוויק", "אקורד", "ג'אז", "CR-V", "HR-V", "פיילוט"],
    "מאזדה": ["מאזדה 3", "מאזדה 6", "CX-5", "CX-3", "CX-30", "מאזדה 2"],
    "יונדאי": ["i20", "i30", "i35", "טוסון", "סונטה", "אלנטרה", "ix35", "סנטה פה", "קונה"],
    "קיה": ["ספורטז'", "ריו", "סיד", "פיקנטו", "סטוניק", "סורנטו", "ניירו"],
    "פולקסווגן": ["גולף", "פאסאט", "פולו", "טיגואן", "ג'טה", "ארטאון", "טי-רוק"],
    "פורד": ["פוקוס", "פיאסטה", "קוגה", "מונדיאו", "אקו-ספורט", "פיוז'ן"],
    "סובארו": ["אימפרזה", "פורסטר", "אאוטבק", "XV", "לגאסי", "BRZ"],
    "ניסאן": ["ג'וק", "X-Trail", "סנטרה", "קשקאי", "מיקרה", "לאף"],
    "סוזוקי": ["סוויפט", "ויטארה", "ספלאש", "סלריו", "ג'ימני"],
    "סיאט": ["איביזה", "לאון", "אטקה", "ארונה", "טרקו"],
    "סקודה": ["אוקטביה", "פאביה", "סקאלה", "קודיאק", "קאמיק", "ספרשב"],
    "רנו": ["קליאו", "מגאן", "קפצ'ור", "קולאוס", "זואי", "קנגו"],
    "פיג'ו": ["208", "308", "3008", "2008", "508", "206", "207"],
    "סיטרואן": ["C3", "C4", "C5", "C-קרוסר", "ברלינגו"],
    "ב.מ.וו": ["סדרה 1", "סדרה 2", "סדרה 3", "סדרה 5", "סדרה 7", "X1", "X3", "X5", "X6"],
    "מרצדס": ["A קלאס", "B קלאס", "C קלאס", "E קלאס", "S קלאס", "GLA", "GLC", "GLE", "CLA"],
    "אאודי": ["A1", "A3", "A4", "A5", "A6", "Q3", "Q5", "Q7", "TT"],
    "אופל": ["אסטרה", "קורסה", "אינסיגניה", "מוקה", "קרוסלנד"],
    "פיאט": ["500", "פונטו", "טיפו", "בראבו", "פנדה"],
    "וולוו": ["S60", "S90", "V40", "V60", "XC40", "XC60", "XC90"],
    "מיצובישי": ["לנסר", "ASX", "אאוטלנדר", "אקליפס קרוס", "L200"],
    "שברולט": ["קרוז", "מאליבו", "ספארק", "טרקס", "קפטיבה"],
    "מיני": ["MINI", "קלאבמן", "קאנטרימן", "קאבריולט"],
    "ג'יפ": ["רנגלר", "צ'רוקי", "גרנד צ'רוקי", "קומפאס", "ראנגלר"],
    "לקסוס": ["IS", "ES", "GS", "LS", "RX", "NX", "UX"],
    "לנד רובר": ["דיסקברי", "דיפנדר", "ריינג' רובר", "אוורק"],
    "טסלה": ["מודל 3", "מודל S", "מודל X", "מודל Y"],
    "דאצ'יה": ["סנדרו", "לוגן", "דאסטר", "לודג'י"],
    "אלפא רומיאו": ["ג'וליאטה", "ג'וליה", "סטלביו", "156", "147"],
    "פורשה": ["קאיין", "מקאן", "פאנמרה", "911", "בוקסטר"],
    "אינפיניטי": ["Q30", "Q50", "QX30", "QX50", "QX70"],
    "יגואר": ["XE", "XF", "XJ", "E-PACE", "F-PACE", "I-PACE"],
    "קאדילק": ["CTS", "ATS", "SRX", "XT5", "Escalade"],
}

config = Config()
search_manager = SearchManager(config.DATA_DIR)
scraper = Yad2Scraper()


def get_user_id(update: Update) -> str:
    """Always use telegram chat_id as user identifier."""
    return str(update.effective_chat.id)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    text = (
        f"👋 שלום {user.first_name}!\n\n"
        "🚗 *בוט חיפוש רכבים ביד 2*\n\n"
        f"🔑 ה-Chat ID שלך: `{chat_id}`\n"
        "השתמש במספר זה באתר CarConnoisseur\n\n"
        "📋 *פקודות זמינות:*\n"
        "/add\\_search – הוסף חיפוש חדש\n"
        "/my\\_searches – הצג את החיפושים שלי\n"
        "/check\\_now – בדוק עכשיו\n"
        "/my\\_id – הצג את ה-Chat ID שלך\n"
        "/help – עזרה\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def my_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        f"🔑 ה-Chat ID שלך הוא:\n\n`{chat_id}`\n\nהשתמש במספר זה באתר CarConnoisseur",
        parse_mode="Markdown"
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = (
        "🆘 *עזרה*\n\n"
        f"🔑 ה-Chat ID שלך: `{chat_id}`\n\n"
        "*/add\\_search* – הגדר חיפוש חדש\n"
        "*/my\\_searches* – ראה ונהל חיפושים\n"
        "*/check\\_now* – בדיקה ידנית\n"
        "*/my\\_id* – הצג את ה-Chat ID שלך\n"
        "*/stop\\_all* – מחק הכל\n\n"
        f"⏱ בודק כל *{config.POLL_INTERVAL_MINUTES}* דקות.\n"
        "💡 בכל שלב אפשר /skip לדלג."
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def add_search_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_search"] = {}
    context.user_data["_state"] = SEARCH_NAME
    await update.message.reply_text(
        "🔍 *הוספת חיפוש חדש*\n\nשלב 1/8 – תן שם לחיפוש:",
        parse_mode="Markdown",
    )
    return SEARCH_NAME


async def got_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_search"]["name"] = update.message.text.strip()
    context.user_data["_state"] = SEARCH_MANUFACTURER
    await _show_manufacturer_keyboard(update.message)
    return SEARCH_MANUFACTURER


async def _show_manufacturer_keyboard(msg):
    rows = []
    row = []
    for i, m in enumerate(MANUFACTURERS):
        row.append(InlineKeyboardButton(m, callback_data=f"mfr_{m}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("🚗 כל היצרנים", callback_data="mfr_all")])
    await msg.reply_text(
        "🏭 שלב 2 – *בחר יצרן:*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def got_manufacturer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    val = query.data.replace("mfr_", "")
    context.user_data["new_search"]["manufacturer"] = "" if val == "all" else val
    context.user_data["_state"] = SEARCH_MODEL
    await _show_model_keyboard(query.message, val)
    return SEARCH_MODEL


async def _show_model_keyboard(msg, manufacturer: str):
    models = MODELS_BY_MANUFACTURER.get(manufacturer, [])
    if models:
        rows = []
        row = []
        for i, m in enumerate(models):
            row.append(InlineKeyboardButton(m, callback_data=f"mdl_{m}"))
            if len(row) == 3:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        rows.append([InlineKeyboardButton("🚗 כל הדגמים", callback_data="mdl_all")])
        await msg.reply_text(
            "🚘 שלב 3 – *בחר דגם:*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(rows),
        )
    else:
        await msg.reply_text(
            "🚘 שלב 3 – *דגם*\nכתוב שם הדגם או שלח /skip לכל הדגמים:",
            parse_mode="Markdown",
        )


async def got_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        val = query.data.replace("mdl_", "")
        context.user_data["new_search"]["model"] = "" if val == "all" else val
        msg = query.message
    else:
        context.user_data["new_search"]["model"] = update.message.text.strip()
        msg = update.message
    context.user_data["_state"] = SEARCH_PRICE_MIN
    await msg.reply_text(
        "💰 שלב 4 – *מחיר מינימלי* (₪)\nשלח /skip לדלג:",
        parse_mode="Markdown",
    )
    return SEARCH_PRICE_MIN


async def got_price_min(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip()
    if not val.isdigit():
        await update.message.reply_text("⚠️ מספר בלבד (או /skip):")
        return SEARCH_PRICE_MIN
    context.user_data["new_search"]["price_min"] = int(val)
    context.user_data["_state"] = SEARCH_PRICE_MAX
    await update.message.reply_text(
        "💰 שלב 5/8 – *מחיר מקסימלי* (₪)\nשלח /skip לדלג:",
        parse_mode="Markdown",
    )
    return SEARCH_PRICE_MAX


async def got_price_max(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip()
    if not val.isdigit():
        await update.message.reply_text("⚠️ מספר בלבד (או /skip):")
        return SEARCH_PRICE_MAX
    context.user_data["new_search"]["price_max"] = int(val)
    context.user_data["_state"] = SEARCH_YEAR_MIN
    await update.message.reply_text(
        "📅 שלב 6/8 – *שנה מינימלית*\nשלח /skip לדלג:",
        parse_mode="Markdown",
    )
    return SEARCH_YEAR_MIN


async def got_year_min(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip()
    if not val.isdigit() or not (1990 <= int(val) <= 2026):
        await update.message.reply_text("⚠️ שנה תקינה (1990-2026) או /skip:")
        return SEARCH_YEAR_MIN
    context.user_data["new_search"]["year_min"] = int(val)
    context.user_data["_state"] = SEARCH_YEAR_MAX
    await update.message.reply_text(
        "📅 שלב 7/8 – *שנה מקסימלית*\nשלח /skip לדלג:",
        parse_mode="Markdown",
    )
    return SEARCH_YEAR_MAX


async def got_year_max(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip()
    if not val.isdigit() or not (1990 <= int(val) <= 2026):
        await update.message.reply_text("⚠️ שנה תקינה (1990-2026) או /skip:")
        return SEARCH_YEAR_MAX
    context.user_data["new_search"]["year_max"] = int(val)
    context.user_data["_state"] = SEARCH_KM_MAX
    await update.message.reply_text(
        "🛣 שלב 8/8 – *קילומטראז' מקסימלי*\nשלח /skip לדלג:",
        parse_mode="Markdown",
    )
    return SEARCH_KM_MAX


async def got_km_max(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip()
    if not val.isdigit():
        await update.message.reply_text("⚠️ מספר בלבד (או /skip):")
        return SEARCH_KM_MAX
    context.user_data["new_search"]["km_max"] = int(val)
    return await show_search_summary(update, context)


async def skip_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    current = context.user_data.get("_state", SEARCH_MANUFACTURER)
    next_state_map = {
        SEARCH_MANUFACTURER: (SEARCH_MODEL,    "🚘 שלב 3/8 – *דגם*\nשלח /skip לכל הדגמים:"),
        SEARCH_MODEL:        (SEARCH_PRICE_MIN, "💰 שלב 4/8 – *מחיר מינימלי* (₪)\nשלח /skip לדלג:"),
        SEARCH_PRICE_MIN:    (SEARCH_PRICE_MAX, "💰 שלב 5/8 – *מחיר מקסימלי* (₪)\nשלח /skip לדלג:"),
        SEARCH_PRICE_MAX:    (SEARCH_YEAR_MIN,  "📅 שלב 6/8 – *שנה מינימלית*\nשלח /skip לדלג:"),
        SEARCH_YEAR_MIN:     (SEARCH_YEAR_MAX,  "📅 שלב 7/8 – *שנה מקסימלית*\nשלח /skip לדלג:"),
        SEARCH_YEAR_MAX:     (SEARCH_KM_MAX,    "🛣 שלב 8/8 – *קילומטראז' מקסימלי*\nשלח /skip לדלג:"),
        SEARCH_KM_MAX:       (None, None),
    }
    nxt, msg = next_state_map.get(current, (None, None))
    if nxt is None:
        return await show_search_summary(update, context)
    context.user_data["_state"] = nxt
    await update.message.reply_text(msg, parse_mode="Markdown")
    return nxt


async def show_search_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = context.user_data["new_search"]
    lines = ["✅ *סיכום החיפוש:*\n", f"📌 שם: *{s.get('name', '—')}*"]
    lines.append(f"🏭 יצרן: {s.get('manufacturer', 'כל היצרנים') or 'כל היצרנים'}")
    lines.append(f"🚘 דגם: {s.get('model', 'כל הדגמים') or 'כל הדגמים'}")
    if s.get("price_min") or s.get("price_max"):
        mn = f"₪{s['price_min']:,}" if s.get("price_min") else "ללא"
        mx = f"₪{s['price_max']:,}" if s.get("price_max") else "ללא"
        lines.append(f"💰 מחיר: {mn} – {mx}")
    if s.get("year_min") or s.get("year_max"):
        lines.append(f"📅 שנה: {s.get('year_min','—')} – {s.get('year_max','—')}")
    if s.get("km_max"):
        lines.append(f"🛣 ק\"מ מקס': {s['km_max']:,}")
    keyboard = [[
        InlineKeyboardButton("✅ שמור", callback_data="save_search"),
        InlineKeyboardButton("❌ בטל", callback_data="cancel_search"),
    ]]
    await update.message.reply_text(
        "\n".join(lines), parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return SEARCH_CONFIRM


async def confirm_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "save_search":
        user_id = str(query.message.chat_id)
        search = context.user_data["new_search"]
        search_manager.add_search(user_id, search)
        await query.edit_message_text(
            f"✅ החיפוש *{search['name']}* נשמר!\n\n"
            f"🔑 Chat ID שלך: `{user_id}`\n"
            "השתמש במספר זה באתר CarConnoisseur 🔔",
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


async def my_searches(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_chat.id)
    searches = search_manager.get_searches(user_id)
    if not searches:
        await update.message.reply_text(
            f"📭 אין לך חיפושים שמורים.\n\n"
            f"🔑 Chat ID שלך: `{user_id}`\n"
            "הוסף חיפוש דרך האתר או /add\\_search",
            parse_mode="Markdown"
        )
        return
    keyboard = []
    for sid, s in searches.items():
        keyboard.append([InlineKeyboardButton(f"🔍 {s['name']}", callback_data=f"view_{sid}")])
    await update.message.reply_text(
        f"📋 *החיפושים שלך* ({len(searches)}):",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def view_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = str(query.message.chat_id)
    sid = query.data.replace("view_", "")
    searches = search_manager.get_searches(user_id)
    s = searches.get(sid)
    if not s:
        await query.edit_message_text("❌ החיפוש לא נמצא.")
        return
    lines = [f"🔍 *{s['name']}*\n"]
    lines.append(f"🏭 יצרן: {s.get('manufacturer', 'כל היצרנים') or 'כל היצרנים'}")
    lines.append(f"🚘 דגם: {s.get('model', 'כל הדגמים') or 'כל הדגמים'}")
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
            InlineKeyboardButton("🗑 מחק", callback_data=f"del_{sid}"),
            InlineKeyboardButton("🔄 בדוק עכשיו", callback_data=f"chk_{sid}"),
        ],
        [InlineKeyboardButton("« חזרה", callback_data="back_to_list")],
    ]
    await query.edit_message_text(
        "\n".join(lines), parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def delete_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = str(query.message.chat_id)
    sid = query.data.replace("del_", "")
    searches = search_manager.get_searches(user_id)
    name = searches.get(sid, {}).get("name", "")
    search_manager.delete_search(user_id, sid)
    await query.edit_message_text(f"🗑 החיפוש *{name}* נמחק.", parse_mode="Markdown")


async def check_single(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("🔄 בודק...")
    user_id = str(query.message.chat_id)
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
        await context.bot.send_message(int(user_id), f"✅ נמצאו {len(new_listings)} מודעות חדשות!")
    else:
        await context.bot.send_message(int(user_id), "😴 אין מודעות חדשות כרגע.")


async def back_to_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = str(query.message.chat_id)
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


async def check_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_chat.id)
    logger.info(f"check_now called by user {user_id}")
    try:
        searches = search_manager.get_searches(user_id)
        if not searches:
            await update.message.reply_text(
                f"📭 אין לך חיפושים.\n🔑 Chat ID שלך: `{user_id}`",
                parse_mode="Markdown"
            )
            return
        await update.message.reply_text(f"🔄 בודק {len(searches)} חיפושים...")
        total = 0
        for sid, s in searches.items():
            try:
                new_listings = await scraper.fetch_new_listings(s, search_manager, user_id, sid)
                for listing in new_listings:
                    await send_listing(context.bot, int(user_id), listing, s["name"])
                    total += 1
            except Exception as e:
                logger.error(f"Error fetching listings for search {sid}: {e}", exc_info=True)
                await update.message.reply_text(f"⚠️ שגיאה בחיפוש '{s.get('name', sid)}': {e}")
        msg = f"✅ נמצאו {total} מודעות חדשות!" if total else "😴 אין מודעות חדשות."
        await update.message.reply_text(msg)
    except Exception as e:
        logger.error(f"check_now error: {e}", exc_info=True)
        await update.message.reply_text(f"❌ שגיאה: {e}")


async def poll_all_searches(context: ContextTypes.DEFAULT_TYPE):
    logger.info("⏱ Running scheduled poll...")
    for user_id in search_manager.get_all_users():
        for sid, s in search_manager.get_searches(user_id).items():
            try:
                new_listings = await scraper.fetch_new_listings(s, search_manager, user_id, sid)
                for listing in new_listings:
                    await send_listing(context.bot, int(user_id), listing, s["name"])
                    logger.info(f"Sent listing {listing['id']} to {user_id}")
            except Exception as e:
                logger.error(f"Error polling {sid} for {user_id}: {e}")


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
            chat_id, text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    except Exception as e:
        logger.error(f"Failed to send to {chat_id}: {e}")


async def debug_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 בודק מה Playwright רואה ביד2...")
    try:
        info = await scraper.debug_page()
        lines = [f"*Debug Report*\n"]
        for k, v in info.items():
            if k == "html_preview":
                continue
            lines.append(f"`{k}`: {v}")
        if "html_preview" in info:
            lines.append(f"\n*HTML preview:*\n```\n{str(info['html_preview'])[:800]}\n```")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ שגיאה: {e}")


async def stop_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_chat.id)
    count = search_manager.delete_all_searches(user_id)
    await update.message.reply_text(f"🛑 כל {count} החיפושים נמחקו.")


async def logs_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_path = "logs/bot.log"
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        filtered = [l for l in lines if "httpx" not in l]
        last_lines = "".join(filtered[-60:])
        if len(last_lines) > 4000:
            last_lines = last_lines[-4000:]
        await update.message.reply_text(f"📋 *לוג אחרון:*\n```\n{last_lines}\n```", parse_mode="Markdown")
    except FileNotFoundError:
        await update.message.reply_text("❌ קובץ לוג לא נמצא.")
    except Exception as e:
        await update.message.reply_text(f"❌ שגיאה: {e}")


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = search_manager.get_all_users()
    total = sum(len(search_manager.get_searches(u)) for u in users)
    await update.message.reply_text(
        f"✅ *הבוט פעיל*\n\n"
        f"👥 משתמשים: {len(users)}\n"
        f"🔍 סה\"כ חיפושים: {total}\n"
        f"⏱ סריקה כל {config.POLL_INTERVAL_MINUTES} דקות",
        parse_mode="Markdown"
    )


def main():
    token = config.TELEGRAM_TOKEN
    if not token:
        logger.error("❌ TELEGRAM_TOKEN לא מוגדר")
        sys.exit(1)

    logger.info("🔧 Starting API thread...")
    start_api_thread(int(os.getenv("PORT", 8080)), sm=search_manager)
    logger.info("🔧 API thread started")

    app = Application.builder().token(token).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("add_search", add_search_start)],
        states={
            SEARCH_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_name)],
            SEARCH_MANUFACTURER: [CallbackQueryHandler(got_manufacturer, pattern="^mfr_"), CommandHandler("skip", skip_step)],
            SEARCH_MODEL: [CallbackQueryHandler(got_model, pattern="^mdl_"), MessageHandler(filters.TEXT & ~filters.COMMAND, got_model), CommandHandler("skip", skip_step)],
            SEARCH_PRICE_MIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_price_min), CommandHandler("skip", skip_step)],
            SEARCH_PRICE_MAX: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_price_max), CommandHandler("skip", skip_step)],
            SEARCH_YEAR_MIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_year_min), CommandHandler("skip", skip_step)],
            SEARCH_YEAR_MAX: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_year_max), CommandHandler("skip", skip_step)],
            SEARCH_KM_MAX: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_km_max), CommandHandler("skip", skip_step)],
            SEARCH_CONFIRM: [CallbackQueryHandler(confirm_search, pattern="^(save|cancel)_search$")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("my_id", my_id))
    app.add_handler(CommandHandler("my_searches", my_searches))
    app.add_handler(CommandHandler("check_now", check_now))
    app.add_handler(CommandHandler("stop_all", stop_all))
    app.add_handler(CommandHandler("debug_now", debug_now))
    app.add_handler(CommandHandler("logs", logs_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(view_search, pattern="^view_"))
    app.add_handler(CallbackQueryHandler(delete_search, pattern="^del_"))
    app.add_handler(CallbackQueryHandler(check_single, pattern="^chk_"))
    app.add_handler(CallbackQueryHandler(back_to_list, pattern="^back_to_list$"))

    interval = config.POLL_INTERVAL_MINUTES * 60
    app.job_queue.run_repeating(poll_all_searches, interval=interval, first=30)

    logger.info(f"🚀 Bot started! Polling every {config.POLL_INTERVAL_MINUTES} minutes.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

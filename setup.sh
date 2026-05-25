#!/bin/bash
# ─── Yad2 Bot – Quick Setup Script ───────────────────────────────────────────
set -e

echo "🚀 Yad2 Bot Setup"
echo "──────────────────"

# 1. Create virtual env
if [ ! -d "venv" ]; then
    echo "📦 יוצר virtual environment..."
    python3 -m venv venv
fi

# 2. Activate & install deps
echo "📥 מתקין תלויות..."
source venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q

echo ""
echo "✅ ההתקנה הושלמה!"
echo ""
echo "📋 שלבים הבאים:"
echo "  1. ערוך את קובץ .env והכנס את ה-TELEGRAM_TOKEN שלך"
echo "     (קבל מ-@BotFather בטלגרם)"
echo ""
echo "  2. הפעל את הבוט:"
echo "     source venv/bin/activate && python bot.py"
echo ""
echo "  3. להפעלה אוטומטית עם systemd:"
echo "     - ערוך yad2bot.service (שנה YOUR_LINUX_USER ו-/path/to/)"
echo "     - sudo cp yad2bot.service /etc/systemd/system/"
echo "     - sudo systemctl enable yad2bot"
echo "     - sudo systemctl start yad2bot"
echo "     - sudo systemctl status yad2bot"
echo ""
echo "🤖 בוט הטלגרם שלך מוכן!"

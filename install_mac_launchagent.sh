#!/bin/bash
# ─── Yad2 Bot – Mac auto-start installer (launchd) ───────────────────────────
#
# מריצים פעם אחת מתוך תיקיית הריפו:
#   bash install_mac_launchagent.sh
#
# מה זה עושה:
#   - בונה venv ומתקין תלויות (אם עוד לא קיים)
#   - עוצר כל הרצה ידנית קיימת של בוט.py (כדי למנוע 409 Conflict מטלגרם)
#   - יוצר LaunchAgent שמפעיל את הבוט ברקע, מרים אותו מחדש בכל קריסה,
#     ומפעיל אותו אוטומטית בכל login/הפעלה מחדש של המחשב — בלי טרמינל פתוח.
#
# אחרי ההרצה הבוט רץ כשירות רקע קבוע. אין צורך להשאיר טרמינל פתוח יותר.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LABEL="com.carconnoisseur.yad2bot"
PLIST_PATH="$HOME/Library/LaunchAgents/${LABEL}.plist"
LOG_DIR="$REPO_DIR/logs"
UID_NUM="$(id -u)"

echo "📂 תיקיית הריפו: $REPO_DIR"

if [ ! -f "$REPO_DIR/.env" ]; then
    echo "❌ לא נמצא קובץ .env בתוך $REPO_DIR"
    echo "   צור אותו קודם עם TELEGRAM_TOKEN, SUPABASE_URL, SUPABASE_SERVICE_KEY (ראה README.md)."
    exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "❌ python3 לא נמצא. התקן אותו (למשל: brew install python3) ונסה שוב."
    exit 1
fi

echo "📦 בודק venv..."
if [ ! -d "$REPO_DIR/venv" ]; then
    python3 -m venv "$REPO_DIR/venv"
fi
# shellcheck disable=SC1091
source "$REPO_DIR/venv/bin/activate"
pip install --upgrade pip -q
pip install -r "$REPO_DIR/requirements.txt" -q
deactivate

PYTHON_BIN="$REPO_DIR/venv/bin/python3"
mkdir -p "$LOG_DIR"

echo "🛑 עוצר הרצות ידניות קיימות של bot.py (אם יש, כדי למנוע כפילות מול טלגרם)..."
pkill -f "[p]ython.*bot\.py" 2>/dev/null || true
sleep 1

echo "🧹 מסיר גרסה קודמת של השירות (אם קיימת)..."
launchctl bootout "gui/${UID_NUM}" "$PLIST_PATH" 2>/dev/null || true

echo "📝 כותב $PLIST_PATH ..."
cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${PYTHON_BIN}</string>
        <string>${REPO_DIR}/bot.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${REPO_DIR}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>
    <key>ThrottleInterval</key>
    <integer>10</integer>
    <key>ProcessType</key>
    <string>Background</string>
    <key>StandardOutPath</key>
    <string>${LOG_DIR}/launchd.out.log</string>
    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/launchd.err.log</string>
</dict>
</plist>
EOF

echo "🚀 מפעיל את השירות..."
launchctl bootstrap "gui/${UID_NUM}" "$PLIST_PATH"
launchctl enable "gui/${UID_NUM}/${LABEL}"
launchctl kickstart -k "gui/${UID_NUM}/${LABEL}"

sleep 2
echo ""
echo "✅ הותקן והופעל בהצלחה!"
echo ""
echo "מעכשיו הבוט רץ ברקע תמיד — גם אחרי סגירת טרמינל, גם אחרי הפעלה מחדש של המחשב."
echo "אם הוא קורס מכל סיבה — launchd יעלה אותו מחדש אוטומטית תוך שניות."
echo ""
echo "פקודות שימושיות:"
echo "  בדיקת סטטוס:    launchctl print gui/${UID_NUM}/${LABEL} | head -20"
echo "  לוגים חיים:      tail -f ${LOG_DIR}/launchd.out.log"
echo "  לוגי שגיאות:     tail -f ${LOG_DIR}/launchd.err.log"
echo "  עצירה זמנית:     launchctl bootout gui/${UID_NUM}/${LABEL}"
echo "  הפעלה מחדש כפויה: launchctl kickstart -k gui/${UID_NUM}/${LABEL}"

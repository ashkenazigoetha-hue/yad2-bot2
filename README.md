# Yad2 Car Search Bot 🚗

בוט טלגרם מוכן לשימוש שמחפש רכבים ביד2 ושולח התראות על מודעות חדשות בזמן אמת.

## מה הבוט עושה

- מאפשר להגדיר חיפושי רכב (יצרן, דגם, מחיר, שנה, קילומטראז')
- סורק את יד2 אוטומטית כל כמה דקות
- שולח הודעת טלגרם מיד כשעולה מודעה חדשה שתואמת את החיפוש
- שומר היסטוריה כדי לא לשלוח את אותה מודעה פעמיים

---

## הפעלה

### דרישות
- Python 3.10+
- טוקן של בוט טלגרם (מ-[@BotFather](https://t.me/botfather))

### 1. שכפל את הפרויקט

```bash
git clone https://github.com/ashkenazigoetha-hue/yad2-bot2.git
cd yad2-bot2
```

### 2. התקן תלויות

```bash
pip install -r requirements.txt
```

### 3. צור קובץ `.env`

```env
TELEGRAM_TOKEN=הטוקן_שלך
POLL_INTERVAL_MINUTES=15
DATA_DIR=data
```

### 4. הפעל

```bash
python bot.py
```

תראה בטרמינל:
```
🚀 Bot started! Polling every 15 minutes.
```

---

## עדכון גרסה

אם הבוט כבר מותקן אצלך:

```bash
git remote set-url origin https://github.com/ashkenazigoetha-hue/yad2-bot2.git
git pull
python bot.py
```

---

## פקודות הבוט

| פקודה | תיאור |
|-------|--------|
| `/start` | תפריט ראשי + ה-Chat ID שלך |
| `/add_search` | הוסף חיפוש חדש |
| `/my_searches` | הצג וניהל חיפושים |
| `/check_now` | בדוק מיד אם יש מודעות חדשות |
| `/my_id` | הצג את ה-Chat ID שלך |
| `/stop_all` | מחק את כל החיפושים |

---

## פתרון בעיות

**הבוט לא שולח כלום בהרצה הראשונה** — תקין. הבוט מסמן את כל המודעות הקיימות כנראו ומהרצה הבאה שולח רק חדשות.

**מודעות ישנות חוזרות** — ודא שקובץ `data/searches.json` לא נמחק.

**הבוט לא מגיב** — בדוק שה-`TELEGRAM_TOKEN` בקובץ `.env` נכון, ובדוק שגיאות ב-`logs/bot.log`.

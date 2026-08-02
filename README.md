# CarConnoisseur Bot

Telegram bot that monitors yad2.co.il for new car listings matching saved searches. Users manage searches on the website; the bot sends Telegram alerts.

Website: https://carconnoisseur-web.vercel.app  
Supabase project: `exydxtitrmqulahfomxj`

---

## How it works

1. User creates an account on the website and sets up car searches (manufacturer, model, price range, year, km max).
2. From the signed-in dashboard, the user clicks **Connect Telegram**. The site opens the bot with a one-time token that expires after 15 minutes.
3. The bot polls yad2 every 15 minutes and sends only new matching listings.

### New-search baseline
Within 60 seconds of a search being created, the bot records all currently matching listings in `seen_ids` without sending them. From that point on, the user receives only listings first discovered in a later poll.

### Ongoing alerts
Every 15 minutes the bot checks for genuinely new listings (not previously seen). These are labeled **"מודעה חדשה!"**.

### Price change alerts
If a listing the bot already sent changes price, it sends an alert with the old and new price and a ↓/↑ arrow.

---

## Architecture

```
website (Next.js)
    ├── creates/edits/pauses searches in Supabase `searches` table
    └── creates short-lived Telegram linking tokens
          └── bot detects changes via polling (no webhooks)

bot.py
├── poll_all_searches()       runs every 15 min
│   ├── groups searches by manufacturer
│   ├── one yad2 fetch per manufacturer (avoids duplicate requests)
│   └── _process_search_with_listings() per search
│       ├── first run: silently seeds ALL matching as seen
│       └── steady state: sends new + price-changed listings
│
├── welcome_new_searches()    runs every 60s (silent baseline seeding)
│   ├── detects searches with NULL seen_ids
│   ├── detects deleted searches (stops polling within 60s)
│   └── uses the same manufacturer fetch as poll to avoid baseline gaps
│
└── _fetch_new()              used for no-manufacturer searches
    └── search-specific yad2 URL with model/price/year filters
```

### Key state in Supabase `searches` table
- `seen_ids` — array of yad2 listing tokens already sent to user (capped at 5000)
- `seen_prices` — dict of `{listing_id: price}` for price-change tracking
- `is_active` — whether the search is currently being scanned
- `last_scanned_at`, `last_match_count`, `last_notified_at` — user-facing status

Alerts include all details available from yad2: price, year, hand, km, ownership, engine, test date, city, equipment, seller notes and contact details. Each alert also has buttons to open the listing, pause its search, or manage searches on the website.

---

## Setup

### Requirements
```
python-telegram-bot==21.6
curl_cffi
httpx
python-dotenv
```

Install: `pip install -r requirements.txt`

### Environment variables (`.env`)
```
TELEGRAM_TOKEN=...
SUPABASE_URL=https://exydxtitrmqulahfomxj.supabase.co
SUPABASE_SERVICE_KEY=...
POLL_INTERVAL_MINUTES=15   # optional, default 15
API_PORT=8080               # optional, default 8080
PROXY_URL=                  # optional, e.g. http://user:pass@host:port
```

The admin interface itself is served by the website. Its `ADMIN_EMAILS` and
server-only Supabase secret must be configured in the website deployment, not
in this bot's `.env`.

### Run
```bash
python bot.py
```

Logs go to `logs/bot.log` and stdout.

---

## Telegram commands

| Command | Description |
|---|---|
| `/start` | Welcome message or consume the secure link opened by the website |
| `/my_searches` | List active searches with inline buttons |
| `/check_now` | Manually trigger a poll for all searches |
| `/status` | Show personal tracking status, active-search count and last scan |
| `/clear_history` | Reset the baseline; existing listings are silently seeded again |
| `/logs` | Admin only: show last 60 log lines (filtered) |
| `/debug_now` | Admin only: test yad2 connectivity |
| `/debug_search` | Admin only: show Supabase data + yad2 URL for first search |

---

## Deployment

The bot runs as a single process on Aral's Mac. No Docker, no cloud hosting.

### Required database migration

Before restarting this version, apply the website migrations through
`supabase/migrations/0005_admin_console.sql` in the Supabase SQL Editor. Migration
0005 adds blocking, trials and the admin audit log. The bot reads these access
rules before every manual or scheduled scan, so blocked or expired accounts are
not scanned.

### One-time setup (recommended): auto-restart via launchd

Running `python bot.py` manually in an open terminal means the bot silently
dies the moment the terminal closes, the Mac sleeps/restarts, or Aral logs
out — with no alert. Instead, install it as a background service that
launchd keeps alive and restarts automatically on crash or reboot:

```bash
cd /path/to/yad2-bot2
bash install_mac_launchagent.sh
```

Run this once. After that, the bot is always running in the background —
no terminal needs to stay open. See the script's own output for status/log/
stop commands, or `launchctl print gui/$(id -u)/com.carconnoisseur.yad2bot`.

### Updating after a code change

```bash
cd /path/to/yad2-bot2
git pull origin main
launchctl kickstart -k "gui/$(id -u)/com.carconnoisseur.yad2bot"   # if installed via launchd
# or, if still running manually: kill existing process, then `python bot.py`
```

Apply the database migration first, then pull and restart the bot.

### Conflict (409) prevention
Only one instance should run at a time. If a 409 appears, find and kill duplicate processes:
```bash
ps aux | grep bot.py
kill <PID>
```

---

## Known limitations

- yad2 km is not in the feed — the bot fetches each listing's detail page to get km (max 3 concurrent). This means km enrichment adds ~2-5s per batch of 15 listings.
- yad2 boosts old listings to the top of the feed. The `_is_recent` check (7-day window based on `createdAt`) prevents these from being re-sent as new.
- No-manufacturer searches (`_fetch_new`) are less efficient than manufacturer-grouped searches — they hit the search-specific URL with all filters in the URL.
- `seen_ids` is capped at 5000 entries per search (oldest dropped). Very high-volume searches may occasionally re-send very old listings.

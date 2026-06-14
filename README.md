# CarConnoisseur Bot

Telegram bot that monitors yad2.co.il for new car listings matching saved searches. Users manage searches on the website; the bot sends Telegram alerts.

Website: https://carconnoisseur-web.vercel.app  
Supabase project: `exydxtitrmqulahfomxj`

---

## How it works

1. User creates an account on the website and sets up car searches (manufacturer, model, price range, year, km max).
2. User sends `/start` in Telegram and provides their email to link accounts.
3. The bot polls yad2 every 15 minutes and sends new matching listings.

### Welcome batch (new search)
Within 60 seconds of a search being created, the bot sends up to 10 recent listings from the past 7 days, sorted oldest→newest. Each listing is labeled **"מודעה אחרונה"** so the user knows these aren't brand-new.

### Ongoing alerts
Every 15 minutes the bot checks for genuinely new listings (not previously seen). These are labeled **"מודעה חדשה!"**.

### Price change alerts
If a listing the bot already sent changes price, it sends an alert with the old and new price and a ↓/↑ arrow.

---

## Architecture

```
website (Next.js)
    └── creates/deletes searches in Supabase `searches` table
          └── bot detects changes via polling (no webhooks)

bot.py
├── poll_all_searches()       runs every 15 min
│   ├── groups searches by manufacturer
│   ├── one yad2 fetch per manufacturer (avoids duplicate requests)
│   └── _process_search_with_listings() per search
│       ├── first run: seeds ALL matching as seen, sends top 10
│       └── steady state: sends new + price-changed listings
│
├── welcome_new_searches()    runs every 60s
│   ├── detects searches with empty seen_ids
│   ├── detects deleted searches (stops polling within 60s)
│   └── sends welcome batch via same manufacturer fetch as poll
│
└── _fetch_new()              used for no-manufacturer searches
    └── search-specific yad2 URL with model/price/year filters
```

### Key state in Supabase `searches` table
- `seen_ids` — array of yad2 listing tokens already sent to user (capped at 5000)
- `seen_prices` — dict of `{listing_id: price}` for price-change tracking

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

### Run
```bash
python bot.py
```

Logs go to `logs/bot.log` and stdout.

---

## Telegram commands

| Command | Description |
|---|---|
| `/start` | Welcome message + link account by email |
| `/my_searches` | List active searches with inline buttons |
| `/check_now` | Manually trigger a poll for all searches |
| `/status` | Show number of linked users and searches |
| `/clear_history` | Reset seen_ids so the bot re-sends recent listings |
| `/logs` | Show last 60 log lines (filtered) |
| `/debug_now` | Test yad2 connectivity |
| `/debug_search` | Show Supabase data + yad2 URL for first search |

---

## Deployment

The bot runs as a single process on Aral's Mac. No Docker, no cloud hosting.

```bash
# Pull latest and restart
cd /path/to/yad2-bot2
git pull origin main
# kill existing process, then:
python bot.py
```

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

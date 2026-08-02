# CLAUDE.md — CarConnoisseur Bot

This file is read automatically by Claude Code. It describes the project context, critical rules, and setup state so Claude can assist without needing re-explanation.

---

## Where the bot runs

**Currently**: Aral's MacBook laptop. Previously run manually as `python bot.py` in an open terminal — this caused silent, unnoticed downtime (bot died whenever the terminal closed, the laptop slept, or it restarted; no restart/alert). As of the `install_mac_launchagent.sh` script, it should instead run as a macOS `launchd` LaunchAgent (`com.carconnoisseur.yad2bot`) — starts on login, restarts automatically on crash. Confirm with Aral that he's actually run the installer before assuming this is active.

**In progress**: Migrating to a dedicated **GMKtec G5 Mini PC** (Intel N97, 12GB RAM, 256GB SSD) so the bot runs 24/7 without depending on the laptop. The mini PC will run the bot as a `systemd` service on Ubuntu (or via WSL2 on Windows 11 Pro which comes pre-installed).

The code is already prepared for this migration — no code changes are needed for the move. Only the deployment method changes (see setup section below).

---

## Critical rules — do NOT change these behaviors

1. **First-run "burn"**: When a new search is created, the bot silently seeds ALL current yad2 listings as `seen_ids` and sends none of them. This is intentional — the user only gets alerts for listings posted AFTER their search was created. Do not reintroduce a welcome batch of old listings.

2. **Mark seen AFTER send**: Listings that will be sent to users must be marked as `seen_ids` only AFTER successful delivery. Marking before send means a failed send permanently loses that listing.

3. **One instance only**: Only one `bot.py` process should run at a time. Two instances cause 409 Conflict errors from Telegram.

4. **Supabase project**: `exydxtitrmqulahfomxj` — this is the yad2-bot Supabase instance, separate from any other Supabase projects Ido may have.

---

## Architecture summary

- `poll_all_searches()` — runs every 15 min. Groups searches by manufacturer, fetches yad2 **once per manufacturer** (not once per search). This keeps yad2 request count low at scale (100 users × 30 searches → ~50 yad2 fetches instead of 3000).
- `welcome_new_searches()` — runs every 60s. Silently seeds new searches (seen_ids is NULL) and detects deleted searches.
- `_process_search_with_listings()` — filters a pre-fetched manufacturer listing set for one specific search, sends new/price-changed listings.
- `_fetch_new()` — used only for searches with no manufacturer (can't be grouped).

---

## Admin commands (Telegram)

These commands are only available to chat IDs listed in `ADMIN_CHAT_IDS` env var:

| Command | Usage |
|---|---|
| `/admin_debug <email>` | Show profile, searches, seen_ids count for a user |
| `/admin_reset <email>` | Reset seen_ids to NULL — triggers silent baseline seeding again |
| `/my_id` | Show your own Telegram chat_id (anyone can use this) |

---

## Mini PC setup guide

When setting up the bot on the GMKtec G5 (or any Linux machine):

### Option A — Ubuntu Server (recommended)

```bash
# 1. Install Python deps
sudo apt update && sudo apt install python3 python3-pip python3-venv git -y

# 2. Clone repo
git clone https://github.com/ashkenazigoetha-hue/yad2-bot2.git
cd yad2-bot2

# 3. Create venv and install
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 4. Create .env
cp .env.example .env  # or create manually:
# TELEGRAM_TOKEN=...
# SUPABASE_URL=https://exydxtitrmqulahfomxj.supabase.co
# SUPABASE_SERVICE_KEY=...
# ADMIN_CHAT_IDS=<ido_chat_id>

# 5. Install as systemd service
sudo cp yad2bot.service /etc/systemd/system/
sudo nano /etc/systemd/system/yad2bot.service  # fill in User and WorkingDirectory
sudo systemctl daemon-reload
sudo systemctl enable yad2bot
sudo systemctl start yad2bot

# 6. Check it's running
sudo systemctl status yad2bot
journalctl -u yad2bot -f  # live logs
```

### Option B — WSL2 on Windows (if keeping Windows 11 Pro)

```bash
# In WSL2 terminal, same steps as above up to step 5.
# For auto-start on Windows boot, use Task Scheduler to run:
# wsl -d Ubuntu -- bash -c "cd /path/to/yad2-bot2 && source venv/bin/activate && python bot.py"
```

### Updating the bot (after Ido pushes a fix)

```bash
cd /path/to/yad2-bot2
git pull origin main
sudo systemctl restart yad2bot   # on Linux with systemd
# or: kill <PID> && python bot.py  # if running manually
```

---

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `TELEGRAM_TOKEN` | Yes | Bot token from @BotFather |
| `SUPABASE_URL` | Yes | `https://exydxtitrmqulahfomxj.supabase.co` |
| `SUPABASE_SERVICE_KEY` | Yes | Service role key from Supabase dashboard |
| `ADMIN_CHAT_IDS` | Recommended | Comma-separated Telegram chat IDs with admin access |
| `POLL_INTERVAL_MINUTES` | No | Default: 15 |
| `API_PORT` | No | Default: 8080 |

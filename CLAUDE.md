# CLAUDE.md — CarConnoisseur bot production map

Claude Code reads this file automatically. Treat it as the persistent source of
truth for this repository and update it whenever infrastructure changes.

## Ownership and repositories (current as of 2026-08-02)

- Production assets are being rebuilt under Erel's accounts
  (`erelash27@gmail.com`). Do not assume access to the abandoned/old owners.
- Bot repository: `https://github.com/ashkenazigoetha-hue/yad2-bot2`
- Website repository: `https://github.com/ashkenazigoetha-hue/carconnoisseur-web`
- Website administrators:
  - `ido.goetha5@gmail.com`
  - `erelash27@gmail.com`

## Where the bot runs

- The live bot currently runs on Erel's Mac and is serving users.
- It has been verified using the Playwright/Radware fix, fetching and parsing
  yad2 listings successfully.
- Do not invent the checkout path or process manager. Discover them on the live
  machine with `pwd`, `git remote -v`, process inspection and `launchctl` before
  restarting anything.
- Prefer the `com.carconnoisseur.yad2bot` LaunchAgent when installed. Confirm it
  exists before using `launchctl` commands.
- Exactly one `bot.py` process may run. Multiple instances cause Telegram 409
  conflicts and duplicate work.

## Supabase — active production database

- Active project ref: `dsindpjdlzofqkfbhchy`
- Active URL: `https://dsindpjdlzofqkfbhchy.supabase.co`
- Owner: Erel's Supabase account.
- The old project `exydxtitrmqulahfomxj` is deprecated. Never point production
  back to it.
- The bot's live `.env` has been switched to the new project and verified by a
  successful `last_scanned_at` write.
- The rebuild transferred 4 users, 8 searches and their `seen_ids`. A verified
  Kia Sportage search retained 242 seen listings and sent only 4 new listings
  plus 2 price changes after cutover.
- Database schema is migrations `0001` through `0006`. `0005` provides
  `user_access`, trials, blocking and the admin audit log. `0006` adds the
  `admin_jobs` queue and `bot_runtime_status` heartbeat. Do not deploy the job
  consumer before `0006` exists in the active project.

Never print, commit or message `SUPABASE_SERVICE_KEY`, `TELEGRAM_TOKEN`, database
passwords or connection strings. It is safe to print the project URL/ref only.

Required live `.env` shape (values stay on the machine):

```text
TELEGRAM_TOKEN=<rotated BotFather token>
SUPABASE_URL=https://dsindpjdlzofqkfbhchy.supabase.co
SUPABASE_SERVICE_KEY=<new project's server key>
ADMIN_CHAT_IDS=<approved Telegram chat IDs>
POLL_INTERVAL_MINUTES=15
```

The historical Telegram token appeared in old logs. Rotate it with BotFather,
update the live `.env`, restart once and verify. `httpx`/`httpcore` INFO logging
is disabled in the current code to prevent future URL/token logging.

## Critical behavior — do not regress

1. New searches silently seed every current yad2 listing into `seen_ids` and
   send none. Users receive only listings discovered after creation.
2. Listings are marked seen only after successful Telegram delivery.
3. Preserve `seen_ids` and `seen_prices` during every migration/cutover to avoid
   resending old listings.
4. Telegram linking uses a short-lived one-time website token; never accept a
   typed email as account proof.
5. `get_all_linked_profiles()` and `get_searches()` enforce `user_access`.
   Blocked/expired accounts must not be scanned.
6. Keep one browser session and grouped manufacturer fetching to control yad2
   request volume. The Playwright stealth path is required for Radware.

## Architecture

- `poll_all_searches()` — scheduled scan, grouped by manufacturer.
- `welcome_new_searches()` — every 60 seconds; silent baseline seeding and
  deleted-search detection.
- `_process_search_with_listings()` — filters, detects new/price changes, sends.
- `SupabaseManager` — profiles, access enforcement, searches and seen state.
- `process_admin_jobs()` — serialized five-second consumer for admin-triggered
  scans, baseline resets and Telegram service messages.
- `heartbeat()` — best-effort status update for the website command center.
- Admin access enforcement baseline: commit `635086a`.

## Safe update procedure

1. Confirm repository/branch and that the worktree is clean.
2. Confirm `.env` points to `dsindpjdlzofqkfbhchy` without printing secrets.
3. Pull `origin/main`.
4. Run `python3 -m unittest discover -s tests -v` in the project environment.
5. Restart the single known live process/LaunchAgent only once.
6. Verify logs contain: successful yad2 parse, new Supabase writes, no 401/404,
   no Telegram 409 and no secret-bearing `httpx` request URLs.
7. Verify Telegram `/status` for an active account and a blocked test account.

Do not restart before required database migrations are present. Do not claim a
cutover succeeded until both a Supabase write and a Telegram behavior check pass.

## Website/Vercel dependency

- A new Vercel project must be owned by Erel and connected to
  `ashkenazigoetha-hue/carconnoisseur-web`.
- Configure its public Supabase URL/key, server secret, Telegram username,
  support URL and:
  `ADMIN_EMAILS=ido.goetha5@gmail.com,erelash27@gmail.com`.
- The old `carconnoisseur-web.vercel.app/admin` currently returns 404; do not use
  that as proof that the new admin code is missing from GitHub.
- Once the new production Vercel URL is known, update this section and the
  website's `CLAUDE.md` immediately.

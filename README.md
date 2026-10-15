# Siege Checker

Take a photo of the Rainbow Six Siege scoreboard on your phone and see every
player's ranked stats: rank, RP, K/D, win %, matches played this season, and peak rank.
Each player also has a link to their full R6 Tracker profile.

## How it works

```
 Phone (web page)            Your computer (Python server)              Outside services
 ────────────────            ─────────────────────────────              ────────────────
 1. Take photo  ───────────▶ /api/scan  ── name_reader.py ───────────▶  Claude (reads names)
                ◀── names ──
 2. Show names  ───────────▶ /api/stats ── stats.py ─────────────────▶  Ubisoft stats servers
                ◀── stats ──
```

| File | What it does |
|---|---|
| `static/index.html` | The page you open on your phone. Takes the photo, shrinks it, shows the results. |
| `app.py` | The web server (FastAPI). Connects the phone page to the two steps below. |
| `name_reader.py` | Sends the photo to Claude and gets back `{"enemy": [...], "allies": [...]}`. |
| `stats.py` | Logs in to Ubisoft with `siegeapi` and fetches each player's ranked stats. |

**Why not get the numbers from R6 Tracker itself?** R6 Tracker has no public API
for Siege, and scraping its pages breaks its terms of service and gets blocked.
R6 Tracker reads its numbers from Ubisoft's servers anyway, so we ask Ubisoft directly.

## Setup (one time)

You need Python 3.10 or newer.

```bash
# 1. Make a virtual environment (a private folder for this project's packages)
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 2. Install the packages
pip install -r requirements.txt

# 3. Create your settings file and fill it in
cp .env.example .env             # Windows: copy .env.example .env
```

Then fill in `.env`:

- **`ANTHROPIC_API_KEY`**: create one at https://platform.claude.com. Each photo costs about one cent.
- **`UBISOFT_EMAIL` / `UBISOFT_PASSWORD`**: use a **spare Ubisoft account**, not your
  main. Ubisoft doesn't officially support this kind of access, so don't risk your main account.
  Turn off two-factor authentication on the spare account, or the login won't work.
- **`PLATFORM_FAMILY`**: `console` for PlayStation/Xbox ranked, `pc` for PC.

## Put it online (use it from anywhere on your phone)

This hosts the app for free on [Render](https://render.com), which runs it from this GitHub repo.

1. Sign up at https://render.com using **Sign in with GitHub**.
2. Click **New → Blueprint**, pick the `siegechecker` repo, and click **Connect**.
   Render reads `render.yaml` and sets everything up.
3. Render asks for four secret values. Type them in:
   - `ANTHROPIC_API_KEY`: your Claude API key
   - `UBISOFT_EMAIL` / `UBISOFT_PASSWORD`: the spare Ubisoft account
   - `APP_PASSWORD`: make up a password for the site. Your phone asks for it once and remembers it.
4. Click **Apply** and wait a few minutes for the first build.
5. Open the `https://siegechecker-xxxx.onrender.com` link Render gives you on your phone.
   Then use **Share → Add to Home Screen** so it opens like an app.

Every time you push changes to GitHub, Render rebuilds the site automatically.

**Free plan catch:** the site goes to sleep after 15 minutes with no visitors. The first
scan after that takes about a minute while it wakes up. Open the site in the
operator-select phase, before you need the stats.

## Running it on your own computer instead

```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```

1. Find your computer's local IP address (Windows: `ipconfig`, Mac: System Settings → Wi-Fi → Details).
   It looks like `192.168.1.23`.
2. On your phone, **on the same Wi-Fi**, open `http://192.168.1.23:8000`.
3. Tap **Scan the scoreboard** and take a photo of the scoreboard (hold Tab/touchpad in game).
4. If a name was misread, tap it, fix it and press Enter to search again.

Tip: add the page to your home screen (Share → Add to Home Screen) so it opens like an app.

## Good to know

- **Streamer mode.** If you have Siege's streamer mode (or a "hide names" setting) turned on,
  your scoreboard shows placeholder names, so there's nothing real to look up. Turn it off.
- **Name not found?** Try fixing look-alike characters (`l`/`I`/`1`, `O`/`0`). The app tries
  PSN names first, then Ubisoft names, then Xbox. Change the order with `LOOKUP_PLATFORMS` in `.env`.
- **Always set `APP_PASSWORD` when it's online.** Without it, anyone who finds the link can spend
  your Claude credit. Set a spending limit at https://platform.claude.com too, just in case.

# 🤖 Universal Downloader & Bypass Bot — Project Handover (`agent.md`)

This document serves as the complete technical handover and context dossier for future AI assistants and developers working on this codebase. It documents the architecture, all resolved issues, critical design decisions, and operational instructions.

---

## 📌 1. Project Overview & Architecture

- **Bot Username:** `@butcherbombit_bot`
- **Primary Roles:**
  1. **📥 Download Mode (Default):** Downloads media from YouTube (Shorts & Videos), Instagram (Reels, Posts, Carousels), X/Twitter, Pinterest, TikTok, Facebook, Reddit, SoundCloud, etc., with high-res thumbnails, audio album art, and video trimming.
  2. **🔓 Bypass Mode:** Asynchronously expands short links and bypasses ad-shorteners (`links/go` pattern) with strict SSRF protection and live progress feedback.
- **2GB Upload Engine:** Upgraded from the standard Telegram 50MB Bot API limit to **2GB (2048 MB)** using MTProto Client (`Telethon`).

### Tech Stack
| Component | Technology | Purpose |
|---|---|---|
| **Bot Framework** | `python-telegram-bot` >= 22.0 | Updates polling, command handling, inline keyboards |
| **2GB MTProto Uploader** | `telethon` == 1.45.0 | Directly uploads large files (50MB - 2GB) to Telegram MTProto |
| **Media Downloader** | `yt-dlp` + `gallery-dl` | High-quality audio/video/image extraction |
| **PO Token Provider** | `bgutil-ytdlp-pot-provider` | YouTube bot-detection / proof-of-origin token provider |
| **Media Processing** | `ffmpeg` (winget build) + `Pillow` | Video trimming, compression, album art, thumbnail generation |
| **HTTP Clients** | `aiohttp` + `httpx` | Fast async requests, redirect expansion, and form parsing |
| **HTML Parsing** | `beautifulsoup4` | Hidden input extraction for shorteners |
| **Database** | SQLite3 (`bot.db`) | User registry, download counts, persistent user mode settings |

---

## 🏗️ 2. Project File Structure

```text
├── bot.py                  # Main entry point: initializes app, health server, registers handlers
├── .env                    # Environment variables (NEVER COMMIT! Ignored by git)
├── .gitignore              # Ignores .env, downloads/, *.db, *.session*, cookies*, bot.log
├── requirements.txt        # Python package dependencies
├── agent.md                # THIS handover document for AI & developers
├── links.txt               # Input file for batch bypass testing
├── test_bypass.py          # Automated test suite (SSRF, expander, rate limiter, mode persistence)
│
├── handlers/
│   ├── commands.py         # /start, /help, /about commands
│   ├── mode.py             # /mode command & mode:download / mode:bypass callback handlers
│   ├── router.py           # Central message router: dispatches to downloader or bypass mode
│   ├── downloader.py       # Core media downloader handler, inline quality menus, trimming, etc.
│   ├── bypass_mode.py      # Bypass mode handler (1-5 links, progress updates, clean errors)
│   └── admin.py            # Admin commands: stats, broadcast, force-channel subscription
│
├── utils/
│   ├── uploader.py         # Telethon MTProto 2GB uploader (connects via API_ID & API_HASH)
│   ├── downloader.py       # yt-dlp & gallery-dl download logic, format selectors, thumbnail extraction
│   ├── helpers.py          # Progress bars, human-readable sizes, URL validation, string truncation
│   └── db.py               # SQLite helpers: user registration, mode persistence, settings
│
└── bypass_engine/
    ├── __init__.py         # Package exports
    ├── engine.py           # Multi-level resolver, Semaphore(5), rate limiter (10/min), 30s timeout
    ├── registry.py         # SiteEntry dataclass & SITES registry (Try2link, Gyanilinks, Droplink, etc.)
    ├── generic_links_go.py # 5-step async solver for AdLinkFly/MightyScript shorteners
    ├── expand.py           # Redirect follower (HEAD -> GET stream fallback, max 10 hops)
    └── ssrf.py             # Strict SSRF & private IP blocker; query string log sanitizer
```

---

## 🛠️ 3. Full History of Errors & Fixes

### A. Telegram 50MB Upload Limit Exceeded to 2GB
- **The Problem:** Telegram's official HTTP Bot API (`api.telegram.org`) rejects any bot upload exceeding 50MB with `Request Entity Too Large`.
- **The Solution:** 
  1. Integrated Telegram MTProto client using `telethon`.
  2. Implemented `utils/uploader.py` which logs into MTProto using `API_ID`, `API_HASH`, and `BOT_TOKEN`.
  3. Hybrid routing in `handlers/downloader.py`:
     - Files <= 50MB: Uploaded fast via standard Bot API (`bot.send_video`, `bot.send_audio`).
     - Files > 50MB (up to 2000MB): Automatically routed through `send_video_via_telethon` / `send_audio_via_telethon`.
     - Files > 2000MB: Rejection notice displayed (`Exceeds Telegram 2GB limit`).
     - If Telethon is unconfigured: Graceful fallback to ffmpeg video compression / splitting.
  4. **Credential Security:** `API_ID` and `API_HASH` are stored strictly in `.env`. Session files (`*.session`, `bot.session`) are strictly ignored in `.gitignore`.

### B. Multi-Mode Bot Switcher (`/mode`)
- **The Problem:** Adding a completely new feature (Link Bypasser) without disrupting the extensive, working media downloader.
- **Design Decisions:**
  1. `handlers/router.py`: Acts as a single entry point for text messages. Reads `user_modes(user_id, mode)` from SQLite. Routes to `url_handler` (Download Mode) or `bypass_mode_handler` (Bypass Mode).
  2. `handlers/mode.py`: Inline keyboard with dynamic `✅` checkmark on the active mode.
  3. **Callback Query Conflict Fix:** Existing `downloader.py:button_handler` decodes JSON callback data (`{"a": action}`). Mode callbacks use `mode:download` and `mode:bypass`. A dedicated `CallbackQueryHandler(mode_callback_handler, pattern=r"^mode:")` is registered in `bot.py` **before** `button_handler` so it intercepts mode clicks cleanly without crashing JSON parsing.

### C. Bypass Engine & Linkvertise Technical Resolution
- **AdLinkFly / Generic Shorteners:** Implemented 5-step solver in `bypass_engine/generic_links_go.py`:
  1. GET landing page (browser User-Agent, referer, session cookies).
  2. Parse hidden inputs with `BeautifulSoup`.
  3. Wait configured timer (`asyncio.sleep(site.wait_seconds)`).
  4. POST to `{api_domain}/links/go` with `X-Requested-With: XMLHttpRequest`.
  5. Parse JSON `url` response.
- **SSRF Protection (`bypass_engine/ssrf.py`):** Blocks `127.0.0.0/8`, `localhost`, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `169.254.0.0/16`, `::1`, `fc00::/7`, non-standard ports (allowed: 80, 443). Strips query parameters from logs (`host/path` only).
- **Linkvertise (`link-center.net`, `linkvertise.com`):**
  - *Investigation:* User provided `https://link-center.net/9290161/XPtxliVQflqp`. It redirects to `linkvertise.com`.
  - *Reference Repo Analysis:* `FZBypassBot` used `bypass.pm/bypass2`, but `bypass.pm` domain is expired and dead.
  - *Reverse Engineering `bypass.city`:* Decompiled frontend Next.js bundle showed `bypass.city` requires the user to solve a Cloudflare Turnstile CAPTCHA in the browser (`cloudFlareTurnstileSiteKey`, token in headers). Calling their API without human token returned `403 Forbidden`.
  - *Decision:* Configured `linkvertise` as `status="broken"` in `registry.py`. Returns clean, honest error: `"Cloudflare/captcha ki wajah se bypass nahi ho saka"` without crashing or attempting prohibited/fragile CAPTCHA evasion.

### D. YouTube Shorts & Video Download Issues
- **Root Cause:** YouTube regularly changes cipher signatures and enforces PO-Token (Proof of Origin) bot verification.
- **Fix:** Added `bgutil-ytdlp-pot-provider` plugin in `requirements.txt`. YouTube Shorts URLs are normalized (`/shorts/ID` -> `watch?v=ID`). Multiple player client fallbacks (`ios`, `android`, `web_safari`, `mweb`).

### E. Instagram Posts, Carousels & Reels
- **Reels:** 1-click fast auto-download directly triggered without extra quality confirmation buttons.
- **Carousels & Multi-item posts:** Extracted using `download_carousel_media` and sent as a single Telegram `send_media_group` album (mixing `InputMediaPhoto` and `InputMediaVideo` as needed).
- **Stories:** Verified that Instagram Stories require authenticated account session cookies. The bot cleanly reports when login cookies are required.

### F. Pinterest & X (Twitter) Photos
- **Root Cause:** `yt-dlp` often fails on static image posts with "no video formats found".
- **Fix:** Integrated `gallery-dl` fallback. `get_media_info()` accurately sets `is_photo=True`, and `_execute_photo_download()` fetches the high-resolution image and sends it via `bot.send_photo`.

### G. Sequential Batch Download
- When a user pastes multiple links in a single message, the bot detects `len(urls) > 1` and executes `_execute_batch_download()`, processing each media item sequentially with live status updates.

---

## 🔐 4. Environment Variables Configuration (`.env`)

```env
# Telegram Bot Token from @BotFather
BOT_TOKEN=your_bot_token_here

# Telegram MTProto API credentials from my.telegram.org (Required for 2GB uploads!)
API_ID=your_api_id_here
API_HASH=your_api_hash_here

# File upload limit in MB (Set to 2000 for 2GB support via Telethon)
MAX_FILE_SIZE_MB=2000

# Download storage directory
DOWNLOAD_DIR=downloads

# Full path to ffmpeg.exe
FFMPEG_PATH=C:\Users\Lenovo\AppData\Local\Microsoft\WinGet\Packages\yt-dlp.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-N-125875-g5d4d3bdc61-win64-gpl\bin\ffmpeg.exe

# Force-subscribe channel username (optional, e.g. @channelname)
FORCE_SUB_CHANNEL=@ashtavakra046
```

> [!CAUTION]
> **NEVER hardcode `API_ID`, `API_HASH`, or `BOT_TOKEN` in Python source code.**
> Always use `os.getenv()`. Ensure `.env` is never staged in git commits.

---

## 🧪 5. Testing & Verification

Run the automated bypass test suite:
```bash
python test_bypass.py
```
This runs:
1. **SSRF Unit Tests:** Verifies all private, loopback, metadata IPs, non-whitelisted ports, and dangerous schemes are blocked.
2. **Mode Persistence & Routing Tests:** Verifies SQLite `user_modes` table operations and message routing dispatch.
3. **Rate Limiting Tests:** Verifies 10 requests allowed, 11th rejected within 1 minute.
4. **Redirect Expander Tests:** Verifies multi-hop redirection chains (e.g. `httpbin.org/redirect/2`, `tinyurl.com`).
5. **Batch Links File Test:** Reads `links.txt` and prints a formatted execution status table.

---

## 📋 6. Guidelines for the Next AI Assistant

1. **Do NOT break existing Download Mode:** Any change to `downloader.py` must maintain backward compatibility for Reels, Shorts, trimming, and carousels.
2. **Keep Large File Uploads Clean:** Always route files > 50MB through `utils/uploader.py` via Telethon. Do not call `bot.send_video` with > 50MB files as `api.telegram.org` will reject it.
3. **No CAPTCHA/Cloudflare Evasion Hacks:** As established in project rules, sites with active Cloudflare Turnstile / reCAPTCHA challenges must return a clean, user-friendly message (`Cloudflare/captcha ki wajah se bypass nahi ho saka`), rather than loading heavyweight, ban-prone browser automation tools.
4. **Preserve Database Asynchrony:** Any DB query executed in message handlers must be wrapped in `asyncio.to_thread` or use the async helper functions in `utils/db.py`.

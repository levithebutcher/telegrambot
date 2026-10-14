# 🤖 Multi-Mode Telegram Downloader & Shortlink Bypass Bot (@butcherbombit_bot)

A high-performance, asynchronous Telegram bot built with **python-telegram-bot (v22+)** and **Telethon MTProto**. Features a dynamic dual-mode system:
1. 📥 **Download Mode:** High-speed media downloader supporting YouTube, Instagram Reels & Carousels, TikTok (no watermark), Twitter/X, Facebook, Reddit, Pinterest, SoundCloud, and direct URLs — with quality selection, smart 50MB compressor/splitter, and **up to 2 GB uploads via Telethon**.
2. 🔓 **Bypass Mode:** Safe shortlink bypass engine with SSRF protection, redirect unwrapping, and configurable links/go landing page resolution.

---

## ✨ Key Features

### 📥 1. Media Downloader Mode
- **Broad Platform Support:** YouTube, Instagram (Reels, Posts, Carousels), TikTok, Twitter/X, Facebook, Reddit, Pinterest (Photos/Videos), SoundCloud (MP3 + album art).
- **Quality & Audio Selection:** Choose between 360p, 720p, 1080p, or extract clean audio as MP3.
- **2 GB Telegram Uploads:** Uses Telethon MTProto client (`API_ID` & `API_HASH`) to bypass the standard 50 MB Bot API restriction.
- **Fallback Compression & Splitting:** For bots without Telethon configured, automatically offers 1-click FFmpeg compression (<50MB) or lossless multipart splitting.
- **Video Trimming:** Download exact video clips using timestamp syntax (e.g. `https://youtu.be/... 0:15-1:30`).
- **Sequential Batch Downloads:** Send multiple URLs in a single message for automatic sequential processing.
- **Carousel Extraction:** Full multi-photo/video carousel downloads via `gallery-dl` and `yt-dlp`.

### 🔓 2. Shortlink Bypass Mode
- **Mode Switcher (`/mode`):** Switch between Download Mode and Bypass Mode with state persisted across restarts in SQLite.
- **Generic Links/Go Handler:** Resolves timer-based landing pages and form tokens without running dangerous headless browser automation.
- **Redirect Unwrapper:** Expands shortened redirect chains (bit.ly, tinyurl, t.co, etc.) up to 10 hops.
- **Security & SSRF Hardening:** Non-blocking asynchronous DNS resolution blocking private/loopback IP ranges (`127.0.0.0/8`, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `169.254.0.0/16`, `::1`, `fc00::/7`).
- **Rate-Limiting & Concurrency Control:** Per-user sliding-window rate limit (10 requests/min) and global concurrency semaphore.

### 🛡️ Administration & Security
- **Strict Admin Authorization:** `/setadmin` requires pre-configured `ADMIN_ID` environment variable to prevent arbitrary admin claims.
- **Non-blocking Broadcast:** Background chunked broadcaster with cancellation and real-time delivery reports.
- **Forced Channel Subscription:** Protect your bot by requiring users to join your Telegram channel before downloading.
- **Sanitized Logging & Error Handling:** Strips sensitive tokens and URLs from logs; never leaks system paths to end users.
- **Cloud Keep-Alive:** Built-in lightweight aiohttp HTTP server for zero-downtime hosting on platforms like Render or Koyeb.

---

## 📁 Project Architecture

```
telegram bot/
├── bot.py                  # Bot entry point, JobQueue keep-alive, logging sanitization
├── setup.py                # Environment check and setup utility
├── test_bypass.py          # Automated verification test suite for SSRF and bypass engine
├── requirements.txt        # Pinned production dependencies
├── .env.example            # Environment configuration template
├── bypass_engine/          # Shortlink bypass engine package
│   ├── engine.py           # Core orchestrator, recursion control, rate limiting
│   ├── generic_links_go.py # Async links/go POST handshake handler
│   ├── expand.py           # Async HTTP redirect follower
│   ├── registry.py         # Configurable shortener site definitions
│   └── ssrf.py             # Non-blocking async DNS and private IP validator
├── handlers/               # Telegram event handlers
│   ├── admin.py            # Admin dashboard, stats, broadcast, force-sub check
│   ├── bypass_mode.py      # Bypass mode link receiver and formatted reporter
│   ├── commands.py         # /start, /help, /about
│   ├── downloader.py       # Main URL router, download callbacks, trimmer, batching
│   └── mode.py             # /mode switcher and persistence
└── utils/                  # Core operational utilities
    ├── db.py               # SQLite database layer with non-blocking async wrappers
    ├── downloader.py       # yt-dlp / gallery-dl engine, FFmpeg wrappers, LRU cache
    ├── helpers.py          # Formatting, progress bars, URL validation
    └── uploader.py         # Telethon MTProto 2GB uploader with auto-reconnection
```

---

## 🚀 Getting Started

### Prerequisites
- **Python 3.10+** (Fully tested on Python 3.14)
- **FFmpeg** (Required for video/audio merging and trimming)
  - Windows: Download from [gyan.dev/ffmpeg/builds](https://www.gyan.dev/ffmpeg/builds/) and add `bin/` to system `PATH`
  - Linux: `sudo apt install ffmpeg`
  - macOS: `brew install ffmpeg`

### Installation

1. **Clone the repository and install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure Environment Variables:**
   Copy `.env.example` to `.env` and fill in your values:
   ```bash
   cp .env.example .env
   ```

   | Variable | Required | Default | Description |
   |---|---|---|---|
   | `BOT_TOKEN` | **Yes** | — | Telegram Bot token from [@BotFather](https://t.me/BotFather) |
   | `ADMIN_ID` | Recommended | — | Telegram user ID of the owner to secure `/setadmin` |
   | `API_ID` | Optional | — | Telegram API ID from [my.telegram.org](https://my.telegram.org) (for 2GB uploads) |
   | `API_HASH` | Optional | — | Telegram API Hash from [my.telegram.org](https://my.telegram.org) (for 2GB uploads) |
   | `MAX_FILE_SIZE_MB` | Optional | `2000` or `50` | Maximum upload size threshold |
   | `DOWNLOAD_DIR` | Optional | `downloads` | Directory for temporary media downloads |
   | `FORCE_SUB_CHANNEL` | Optional | — | Channel username or ID for forced subscription (e.g. `@mychannel`) |
   | `PORT` | Optional | `8080` | Port for health check HTTP server |
   | `RENDER_EXTERNAL_URL`| Optional | — | External URL to ping periodically to prevent sleep |
   | `FFMPEG_PATH` | Optional | System PATH | Explicit path to `ffmpeg` executable |

3. **Verify the Installation:**
   Run the automated bypass & SSRF test suite:
   ```bash
   python test_bypass.py
   ```

4. **Launch the Bot:**
   ```bash
   python bot.py
   ```

---

## 📖 Bot Commands

| Command | Description |
|---|---|
| `/start` | Welcome banner, quick instructions, and channel subscription prompt |
| `/mode` | Interactive inline switcher: **📥 Download Mode** vs **🔓 Bypass Mode** |
| `/help` | Detailed guide with examples for all platforms, trimming, and modes |
| `/about` | Bot information, architecture details, and credits |
| `/trim <url> <start-end>` | Download a specific portion of a video (e.g. `0:10-1:00`) |
| `/admin` | *(Admin only)* Open admin dashboard with bot statistics |
| `/broadcast <msg>` | *(Admin only)* Send an announcement to all registered bot users |
| `/stats` | *(Admin only)* View total users, active modes, and download counts |

---

## 🔒 Security Best Practices
- **SSRF Protection:** All URL expansions and link handshakes resolve DNS asynchronously and strictly reject private, loopback, link-local, and cloud metadata (`169.254.169.254`) IP addresses.
- **Log Masking:** Bot tokens, Telegram API requests, and user query parameters containing tokens are filtered from `bot.log`.
- **Database Non-blocking Concurrency:** All SQLite database interactions are routed via `asyncio.to_thread` to maintain a non-blocking event loop.
- **Automatic Resource Cleanup:** Download sessions, temporary files, and trimmed clips are guaranteed to be cleaned up in `finally` blocks.

---

## 📜 License
Distributed under the MIT License. See `LICENSE` for more information.

# 🤖 Universal Downloader Bot

A powerful Telegram bot that downloads media from **YouTube, Instagram, TikTok, Twitter/X, Facebook, Reddit, SoundCloud**, and any direct URL — with quality selection.

---

## ✨ Features

| Platform | Video | Audio |
|---|---|---|
| YouTube | ✅ (360p / 720p / 1080p) | ✅ MP3 |
| Instagram | ✅ Reels, Posts | ✅ |
| TikTok | ✅ No watermark | ✅ |
| Twitter / X | ✅ | ✅ |
| Facebook | ✅ | ✅ |
| Reddit | ✅ | ✅ |
| SoundCloud | — | ✅ |
| Vimeo | ✅ | ✅ |
| Dailymotion | ✅ | ✅ |
| Direct URLs | ✅ | ✅ |

---

## 🚀 Quick Start

### Prerequisites
- **Python 3.10+**
- **ffmpeg** (required for merging video+audio)
  - Windows: [gyan.dev/ffmpeg/builds](https://www.gyan.dev/ffmpeg/builds/) → add to PATH
  - Linux: `sudo apt install ffmpeg`
  - Mac: `brew install ffmpeg`

### 1. Get a Bot Token
1. Open Telegram → search **@BotFather**
2. Send `/newbot` and follow the prompts
3. Copy your bot token

### 2. Install & Configure

```bash
# Clone / download the project, then:
python setup.py
```

The setup script will:
- Install all Python dependencies
- Check for ffmpeg
- Create your `.env` file and save your bot token

**Or manually:**
```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env and paste your BOT_TOKEN
```

### 3. Run the Bot

```bash
python bot.py
```

---

## 📁 Project Structure

```
telegram bot/
├── bot.py                  # Entry point
├── setup.py                # One-time setup
├── requirements.txt
├── .env                    # Your secrets (never commit this)
├── .env.example
├── handlers/
│   ├── commands.py         # /start /help /about
│   └── downloader.py       # URL handling & download callbacks
└── utils/
    ├── downloader.py       # yt-dlp core logic
    └── helpers.py          # Misc utilities
```

---

## ⚙️ Configuration (`.env`)

| Variable | Default | Description |
|---|---|---|
| `BOT_TOKEN` | — | **Required.** Your Telegram bot token |
| `MAX_FILE_SIZE_MB` | `50` | Max file size (Telegram limit = 50 MB) |
| `DOWNLOAD_DIR` | `downloads` | Where temp files are stored |

---

## 📖 Bot Commands

| Command | Description |
|---|---|
| `/start` | Welcome message |
| `/help` | How to use the bot |
| `/about` | About & version info |

**Usage:** Just paste any supported URL — the bot will show media info and let you choose Video quality or Audio (MP3).

---

## ⚠️ Notes

- Telegram bots have a **50 MB upload limit**. Large files (e.g. 4K videos) will be rejected.
- This bot is for **personal use only**. Respect platform ToS and copyright laws.
- ffmpeg must be installed and in PATH for HD video merging to work.

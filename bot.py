import logging
import os
from dotenv import load_dotenv
from telegram import __version__ as TG_VER
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler
from telegram.request import HTTPXRequest

from utils.db import init_db
from handlers.commands import start_handler, help_handler, about_handler
from handlers.mode import mode_command_handler, mode_callback_handler
from handlers.router import main_text_router
from handlers.downloader import url_handler, button_handler, error_handler
from handlers.admin import (
    admin_handler,
    setadmin_handler,
    stats_handler,
    forcesub_handler,
    broadcast_handler,
)

# Load environment variables
load_dotenv()

# Logging setup
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# ── F01 FIX: Silence httpx & telegram HTTP loggers ──────────────────────────
# httpx logs every request URL at INFO level, and those URLs contain the full
# BOT_TOKEN (e.g. /bot<token>/getUpdates). Without this, the token is written
# to bot.log hundreds of times per session.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram.ext.ExtBot").setLevel(logging.WARNING)
logging.getLogger("telegram.bot").setLevel(logging.WARNING)
# ─────────────────────────────────────────────────────────────────────────────

import threading
import asyncio
import aiohttp
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram.ext import ContextTypes


class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK - Bot is running")

    def log_message(self, format, *args):
        pass  # suppress log spam


def start_health_server():
    port = int(os.getenv("PORT", "10000"))
    try:
        server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
        logger.info(f"🌐 Health server active on port {port}")
        server.serve_forever()
    except Exception as e:
        logger.warning(f"Health server error on port {port}: {e}")


# ── F20 FIX: Self-ping as async PTB job (no daemon-thread pile-up) ──────────
async def _self_ping_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """PTB job_queue repeating job: pings RENDER_EXTERNAL_URL every 10 min."""
    url = os.getenv("RENDER_EXTERNAL_URL")
    if not url:
        return
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers={"User-Agent": "RenderSelfPing/1.0"},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                pass
        logger.info("Keep-alive ping sent to %s", url)
    except Exception as e:
        logger.warning("Keep-alive ping failed: %s", e)
# ─────────────────────────────────────────────────────────────────────────────


def main() -> None:
    token = os.getenv("BOT_TOKEN")
    if not token or token == "your_telegram_bot_token_here":
        logger.error("❌ BOT_TOKEN not set! Please create a .env file with your bot token.")
        raise SystemExit(1)

    # Start health server in daemon thread
    threading.Thread(target=start_health_server, daemon=True).start()

    # Initialize SQLite database
    init_db()

    # Create downloads directory
    download_dir = os.getenv("DOWNLOAD_DIR", "downloads")
    os.makedirs(download_dir, exist_ok=True)

    # Increase timeouts for slow connections / large uploads
    request = HTTPXRequest(
        connect_timeout=30.0,
        read_timeout=60.0,
        write_timeout=60.0,
        media_write_timeout=300.0,  # 5 minutes for video uploads
    )

    # Build application
    app = (
        Application.builder()
        .token(token)
        .request(request)
        .build()
    )

    # Register standard command handlers
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("help", help_handler))
    app.add_handler(CommandHandler("about", about_handler))
    app.add_handler(CommandHandler("mode", mode_command_handler))

    # Register admin commands
    app.add_handler(CommandHandler("admin", admin_handler))
    app.add_handler(CommandHandler("setadmin", setadmin_handler))
    app.add_handler(CommandHandler("stats", stats_handler))
    app.add_handler(CommandHandler("forcesub", forcesub_handler))
    app.add_handler(CommandHandler("broadcast", broadcast_handler))

    # Register message handler (catches URLs and trim timestamps, routed by active user mode)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, main_text_router))

    # Register mode callback query handler BEFORE general button handler (prevents JSON decode clash)
    app.add_handler(CallbackQueryHandler(mode_callback_handler, pattern=r"^mode:"))

    # Register callback query handler (inline buttons & verification)
    app.add_handler(CallbackQueryHandler(button_handler))

    # Register global error handler
    app.add_error_handler(error_handler)

    # Schedule self-ping keep-alive as async job (F20 fix)
    if os.getenv("RENDER_EXTERNAL_URL"):
        app.job_queue.run_repeating(
            callback=_self_ping_job,
            interval=600,  # 10 minutes
            first=60,      # first ping after 1 minute
        )
        logger.info("🔄 Self-ping keep-alive job scheduled via job_queue.")

    logger.info("🤖 Universal Downloader Bot is starting...")
    app.run_polling(bootstrap_retries=5)


if __name__ == "__main__":
    main()

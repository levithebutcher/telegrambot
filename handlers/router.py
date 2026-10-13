"""
Main message router: Dispatches incoming user text messages to either
Download mode (downloader.py) or Bypass mode (bypass_mode.py) based on active user mode.
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes

from utils.db import get_user_mode_async
from handlers.downloader import url_handler
from handlers.bypass_mode import bypass_mode_handler

logger = logging.getLogger(__name__)

MODES = {
    "download": url_handler,
    "bypass": bypass_mode_handler,
}


async def main_text_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Read user mode from database and route message to the appropriate handler."""
    user = update.effective_user
    if not user:
        return

    mode = await get_user_mode_async(user.id)
    handler = MODES.get(mode, url_handler)
    await handler(update, context)

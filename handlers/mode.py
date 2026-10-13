"""
Mode switcher handler: /mode command and inline keyboard callbacks.
Supports switching between 'download' and 'bypass' modes.
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from utils.db import get_user_mode_async, set_user_mode_async, add_or_update_user
from handlers.admin import check_user_subscription, get_force_sub_channel

logger = logging.getLogger(__name__)


def get_mode_keyboard(current_mode: str) -> InlineKeyboardMarkup:
    """Build inline keyboard showing active mode with checkmark."""
    download_label = "✅ 📥 Download Mode" if current_mode == "download" else "📥 Download Mode"
    bypass_label = "✅ 🔓 Bypass Mode" if current_mode == "bypass" else "🔓 Bypass Mode"

    keyboard = [
        [
            InlineKeyboardButton(download_label, callback_data="mode:download"),
            InlineKeyboardButton(bypass_label, callback_data="mode:bypass"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_mode_text(current_mode: str) -> str:
    """Return formatted status text for mode switcher."""
    mode_title = "📥 Download Mode" if current_mode == "download" else "🔓 Bypass Mode"
    return (
        "⚙️ <b>Bot Mode Switcher</b>\n\n"
        "Apna pasandida mode select karein:\n\n"
        "• <b>📥 Download Mode:</b> YouTube, Instagram, X/Twitter, Pinterest media downloader.\n"
        "• <b>🔓 Bypass Mode:</b> Shortened links aur ad-links ko fast expand aur bypass karne ke liye.\n\n"
        f"👉 <b>Current Active Mode:</b> {mode_title}"
    )


async def mode_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for /mode command."""
    user = update.effective_user
    if not user:
        return

    add_or_update_user(user.id, user.username, user.first_name)

    # Force-subscribe check
    if not await check_user_subscription(user.id, context.bot):
        channel = get_force_sub_channel()
        clean_ch = channel.lstrip("@")
        kb = [
            [InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{clean_ch}")],
            [InlineKeyboardButton("✅ Joined / Verify", callback_data="verify_sub")],
        ]
        await update.message.reply_text(
            "🔒 <b>Channel Membership Required</b>\n\n"
            "Bot use karne ke liye pehle hamara official channel join karein:\n"
            f"👉 <b>{channel}</b>\n\n"
            "Channel join karne ke baad <b>'Joined / Verify'</b> button dabayein!",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(kb),
        )
        return

    current_mode = await get_user_mode_async(user.id)
    text = get_mode_text(current_mode)
    kb = get_mode_keyboard(current_mode)

    await update.message.reply_text(text, parse_mode="HTML", reply_markup=kb)


async def mode_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for mode:* callback queries."""
    query = update.callback_query
    if not query:
        return

    user = update.effective_user
    if not user:
        await query.answer()
        return

    data = query.data or ""
    parts = data.split(":", 1)
    if len(parts) != 2:
        await query.answer()
        return

    target_mode = parts[1]
    if target_mode == "menu":
        current_mode = await get_user_mode_async(user.id)
        text = get_mode_text(current_mode)
        kb = get_mode_keyboard(current_mode)
        try:
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
        except Exception:
            pass
        return

    if target_mode not in ("download", "bypass"):
        await query.answer("Unknown mode selected.")
        return

    current_mode = await get_user_mode_async(user.id)
    if target_mode == current_mode:
        await query.answer(f"Already in {target_mode.title()} Mode! ✅", show_alert=False)
        return

    # Update mode in database
    await set_user_mode_async(user.id, target_mode)
    logger.info("User %s switched mode to: %s", user.id, target_mode)

    await query.answer(f"Switched to {target_mode.title()} Mode! 🚀", show_alert=False)

    new_text = get_mode_text(target_mode)
    new_kb = get_mode_keyboard(target_mode)

    try:
        await query.edit_message_text(new_text, parse_mode="HTML", reply_markup=new_kb)
    except Exception as e:
        logger.debug("Failed to edit mode message: %s", e)

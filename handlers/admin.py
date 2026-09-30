"""
Admin commands and management:
/admin, /stats, /broadcast, /forcesub, /setadmin
"""

import os
import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import TelegramError

from utils.db import (
    get_user_count,
    get_total_downloads,
    get_all_user_ids,
    get_setting,
    set_setting,
)

logger = logging.getLogger(__name__)

ENV_ADMIN_ID = os.getenv("ADMIN_ID")
ENV_FORCE_SUB = os.getenv("FORCE_SUB_CHANNEL", "@ashtavakra046")


def is_admin(user_id: int) -> bool:
    """Check if a given user is the bot administrator."""
    stored_admin = get_setting("admin_id")
    if stored_admin and str(user_id) == str(stored_admin):
        return True
    if ENV_ADMIN_ID and str(user_id) == str(ENV_ADMIN_ID):
        return True
    return False


def get_force_sub_channel() -> str:
    """Return the active force-subscribe channel, or 'off'."""
    stored = get_setting("force_sub_channel")
    if stored:
        return stored
    return ENV_FORCE_SUB if ENV_FORCE_SUB else "off"


async def check_user_subscription(user_id: int, bot) -> bool:
    """
    Check if user is a member of the required channel.
    Returns True if subscribed, or if force-sub is disabled or channel check failed.
    """
    channel = get_force_sub_channel()
    if not channel or channel.lower() == "off":
        return True

    # Ensure @ prefix if username
    if not channel.startswith("@") and not channel.startswith("-100"):
        channel = f"@{channel}"

    try:
        member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
        if member.status in ("creator", "administrator", "member", "restricted"):
            return True
        return False
    except Exception as e:
        # If bot is not an admin in the channel or chat not found, allow pass-through
        logger.warning("Could not check chat member in %s: %s", channel, e)
        return True


# ── Commands ─────────────────────────────────────────────────────────────────

async def admin_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin dashboard command."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        # If no admin is configured anywhere yet, guide them to claim it
        if not get_setting("admin_id") and not ENV_ADMIN_ID:
            await update.message.reply_text(
                "👑 <b>No Admin configured yet!</b>\n\n"
                "Run <code>/setadmin</code> to set yourself as the bot admin.",
                parse_mode="HTML",
            )
        else:
            await update.message.reply_text("⛔ <i>Access denied. This command is for admins only.</i>", parse_mode="HTML")
        return

    text = (
        "👑 <b>Admin Control Panel</b>\n\n"
        "<b>Available Commands:</b>\n"
        "• <code>/stats</code> — View bot user & download statistics\n"
        "• <code>/broadcast &lt;message&gt;</code> — Send announcement to all users\n"
        "• <code>/forcesub &lt;@channel&gt;</code> — Change force subscribe channel\n"
        "• <code>/forcesub off</code> — Disable force subscribe\n"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def setadmin_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Allow claiming admin if none set."""
    user_id = update.effective_user.id
    current_admin = get_setting("admin_id") or ENV_ADMIN_ID
    if current_admin:
        await update.message.reply_text("⛔ Admin is already set.", parse_mode="HTML")
        return

    set_setting("admin_id", str(user_id))
    await update.message.reply_text(
        f"✅ <b>You are now the Bot Admin!</b> (ID: <code>{user_id}</code>)\n\n"
        "Use <code>/admin</code> to view commands.",
        parse_mode="HTML",
    )


async def stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show detailed bot usage statistics."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("⛔ <i>Access denied.</i>", parse_mode="HTML")
        return

    total_users = get_user_count()
    total_downloads = get_total_downloads()
    channel = get_force_sub_channel()

    text = (
        "📊 <b>Bot Live Statistics</b>\n\n"
        f"👥 <b>Total Users:</b> {total_users:,}\n"
        f"📥 <b>Total Downloads:</b> {total_downloads:,}\n"
        f"📢 <b>Force-Sub Channel:</b> <code>{channel}</code>\n\n"
        "⚡ <b>Enabled Features:</b>\n"
        "• 🚀 Auto Fast-Download (Reels/Shorts)\n"
        "• 🎵 MP3 Album Art & ID3 Tags\n"
        "• ✂️ Video Clip Trimmer\n"
        "• 🔒 Channel Force-Subscribe"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def forcesub_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Configure force-subscribe channel."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("⛔ <i>Access denied.</i>", parse_mode="HTML")
        return

    if not context.args:
        curr = get_force_sub_channel()
        await update.message.reply_text(
            f"📢 Current Force-Sub Channel: <code>{curr}</code>\n\n"
            "To change: <code>/forcesub @yourchannel</code>\n"
            "To disable: <code>/forcesub off</code>",
            parse_mode="HTML",
        )
        return

    new_channel = context.args[0].strip()
    if new_channel.lower() in ("off", "disable", "none", "false"):
        set_setting("force_sub_channel", "off")
        await update.message.reply_text("✅ <b>Force-Subscribe disabled.</b>", parse_mode="HTML")
    else:
        if not new_channel.startswith("@") and not new_channel.startswith("-100"):
            new_channel = f"@{new_channel}"
        set_setting("force_sub_channel", new_channel)
        await update.message.reply_text(
            f"✅ <b>Force-Subscribe updated to:</b> <code>{new_channel}</code>\n\n"
            f"<i>Note: Make sure this bot is added as an Administrator in {new_channel} to check members!</i>",
            parse_mode="HTML",
        )


async def broadcast_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send broadcast message to all registered users."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("⛔ <i>Access denied.</i>", parse_mode="HTML")
        return

    reply_to = update.message.reply_to_message
    broadcast_text = " ".join(context.args).strip() if context.args else ""

    if not reply_to and not broadcast_text:
        await update.message.reply_text(
            "⚠️ <b>Usage:</b>\n"
            "1. <code>/broadcast Your message here</code>\n"
            "OR\n"
            "2. Reply to any message/media with <code>/broadcast</code>",
            parse_mode="HTML",
        )
        return

    users = get_all_user_ids()
    total = len(users)
    if total == 0:
        await update.message.reply_text("⚠️ No users found in database.", parse_mode="HTML")
        return

    status_msg = await update.message.reply_text(f"🚀 Starting broadcast to {total} users...")

    sent_count = 0
    fail_count = 0

    for idx, target_id in enumerate(users):
        try:
            if reply_to:
                await reply_to.copy(chat_id=target_id)
            else:
                await context.bot.send_message(
                    chat_id=target_id,
                    text=broadcast_text,
                    parse_mode="HTML",
                )
            sent_count += 1
        except Exception:
            fail_count += 1

        # Periodic status update every 20 users
        if (idx + 1) % 20 == 0:
            try:
                await status_msg.edit_text(f"🚀 Broadcasting... {idx + 1}/{total}\n✅ Sent: {sent_count} | ❌ Failed: {fail_count}")
            except Exception:
                pass
        await asyncio.sleep(0.05)  # Telegram rate limit safety

    await status_msg.edit_text(
        f"✅ <b>Broadcast Completed!</b>\n\n"
        f"👥 Total Target: {total}\n"
        f"✅ Successfully Sent: {sent_count}\n"
        f"❌ Failed: {fail_count}",
        parse_mode="HTML",
    )

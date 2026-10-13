"""
Command handlers: /start, /help, /about
"""
import html
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from utils.db import add_or_update_user
from handlers.admin import check_user_subscription, get_force_sub_channel


START_TEXT = (
    "👋 <b>Welcome to Multi-Mode Bot!</b>\n\n"
    "Main media download bhi kar sakta hoon aur short/ad-links ko bypass bhi kar sakta hoon!\n\n"
    "<b>✨ Key Modes:</b>\n"
    "📥 <b>Download Mode (Default):</b> YouTube, Instagram, X/Twitter, Pinterest & Reels/Shorts\n"
    "🔓 <b>Bypass Mode:</b> Shortened URLs aur ad-links ko direct link me convert karein\n\n"
    "<b>⚡ Quick Features:</b>\n"
    "• Fast 1-click download for Reels & Shorts\n"
    "• High-Quality MP3 with album art\n"
    "• Video trimming (e.g. <code>00:10 - 00:30</code>)\n"
    "• Mode switch karne ke liye /mode command use karein!\n\n"
    "Type /help for complete guide."
)

HELP_TEXT = (
    "📖 <b>Help Guide & Modes</b>\n\n"
    "<b>1. Multi-Mode Switcher (/mode):</b>\n"
    "• <b>📥 Download Mode:</b> Media download karne ke liye\n"
    "• <b>🔓 Bypass Mode:</b> Short links / ad-links ko unshorten aur bypass karne ke liye (max 5 links ek sath)\n\n"
    "<b>2. Normal Download:</b>\n"
    "• Send any YouTube/Instagram/TikTok link\n"
    "• Choose quality (360p / 720p / 1080p) or MP3\n\n"
    "<b>3. Fast Reels/Shorts Download:</b>\n"
    "• Send an Instagram Reel, YouTube Short, or TikTok link\n"
    "• Bot automatically downloads it in best quality instantly!\n\n"
    "<b>4. Video Clip Trimmer:</b>\n"
    "• Method A: Send link with time: <code>https://youtu.be/... 00:10-00:30</code>\n"
    "• Method B: Send link, click <b>✂️ Trim Clip</b>, then reply with time range!\n\n"
    "<b>5. MP3 Audio with Cover Art:</b>\n"
    "• Select <b>🎵 MP3 Audio</b> for high quality audio with track thumbnail!\n\n"
    "<b>Commands:</b>\n"
    "/start — Welcome message\n"
    "/mode — Switch between Download & Bypass mode\n"
    "/help — This help guide\n"
    "/about — About this bot"
)

ABOUT_TEXT = (
    "ℹ️ <b>About Universal Downloader Bot</b>\n\n"
    "<b>Bot:</b> @butcherbombit_bot\n"
    "<b>Version:</b> 2.5.0\n"
    "<b>Features:</b> Fast Reels, MP3 Album Art, Video Trimmer, Channel Gate\n\n"
    "<b>Libraries used:</b>\n"
    "• <code>python-telegram-bot</code> — Telegram API\n"
    "• <code>yt-dlp</code> — Media engine\n"
    "• <code>ffmpeg</code> — Audio/Video processor\n\n"
    "<i>Note: This bot is for personal use only. Please respect copyright laws.</i>"
)


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
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

    keyboard = [
        [
            InlineKeyboardButton("⚙️ Mode Switcher", callback_data="mode:menu"),
            InlineKeyboardButton("📖 Help", callback_data="help"),
            InlineKeyboardButton("ℹ️ About", callback_data="about"),
        ],
    ]
    await update.message.reply_text(
        START_TEXT,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT, parse_mode="HTML")


async def about_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(ABOUT_TEXT, parse_mode="HTML")

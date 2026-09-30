"""
Main download handler — processes URLs sent by users,
handles fast-downloads for Reels/Shorts, video trimming,
MP3 album art, force-sub verification, and stats tracking.
"""

import asyncio
import logging
import os
import json
import html
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, InputMediaVideo
from telegram.ext import ContextTypes
from telegram.constants import ChatAction
from telegram.error import TelegramError

from utils.downloader import (
    get_media_info,
    download_video,
    download_audio,
    extract_urls,
    file_size_mb,
    cleanup_session,
    is_reel_or_short,
    parse_time_range,
    trim_media,
    get_session_thumbnail,
    get_video_metadata_and_thumb,
    download_carousel_media,
    download_photo,
    resolve_short_url,
    compress_video_to_size,
    split_video_by_size,
    MAX_FILE_SIZE_MB,
)
from utils.helpers import is_valid_url, truncate, human_size, progress_bar
from utils.db import add_or_update_user, increment_download_count
from handlers.admin import check_user_subscription, get_force_sub_channel

logger = logging.getLogger(__name__)


# ── Callback data helpers ────────────────────────────────────────────────────

def _encode_cb(action: str, extra: str = "") -> str:
    return json.dumps({"a": action, "e": extra}, separators=(",", ":"))


def _decode_cb(data: str) -> dict:
    try:
        return json.loads(data)
    except Exception:
        return {}


def _h(text: str) -> str:
    """Escape text for safe use inside HTML parse_mode messages."""
    return html.escape(str(text))


# ── Live progress updater ────────────────────────────────────────────────────

async def _progress_updater(bot, chat_id: int, msg_id: int, progress_state: dict, label: str):
    """Background task: edits the message every ~2 s with download progress."""
    last_text = ""
    while True:
        await asyncio.sleep(2)

        status = progress_state.get("status", "")
        if status in ("done", "error", ""):
            break

        percent = progress_state.get("percent", 0)
        downloaded = progress_state.get("downloaded", 0)
        total = progress_state.get("total", 0)
        speed = progress_state.get("speed", 0)
        eta = progress_state.get("eta", 0)

        bar = progress_bar(int(percent), width=12)

        if status == "merging":
            text = (
                f"⬇️ <b>{label}</b>\n\n"
                f"{bar}  100%\n\n"
                f"🔄 Merging audio + video…"
            )
        else:
            speed_str = human_size(speed) + "/s" if speed else "…"
            eta_str = f"{int(eta)}s" if eta else "…"
            dl_str = human_size(downloaded)
            total_str = human_size(total) if total else "?"

            text = (
                f"⬇️ <b>{label}</b>\n\n"
                f"{bar}  {percent:.0f}%\n\n"
                f"📦 {dl_str} / {total_str}\n"
                f"🚀 {speed_str}   ⏱ ETA {eta_str}"
            )

        if text != last_text:
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=msg_id,
                    text=text,
                    parse_mode="HTML",
                )
                last_text = text
            except TelegramError:
                pass


# ── Global error handler ─────────────────────────────────────────────────────

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log all errors and notify user in Telegram."""
    logger.error("Exception while handling update:", exc_info=context.error)

    err_text = (
        "⚠️ <b>An error occurred while processing your request.</b>\n\n"
        f"<code>{_h(str(context.error))}</code>\n\n"
        "Please try again or send a different link."
    )

    try:
        if isinstance(update, Update):
            if update.callback_query:
                await update.callback_query.message.reply_text(err_text, parse_mode="HTML")
            elif update.message:
                await update.message.reply_text(err_text, parse_mode="HTML")
    except Exception:
        pass


# ── Message / URL handler ────────────────────────────────────────────────────

async def url_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat_id = update.effective_chat.id
    text = update.message.text.strip()

    # Track user in database
    add_or_update_user(user.id, user.username, user.first_name)

    # 1. Force-subscribe check
    if not await check_user_subscription(user.id, context.bot):
        channel = get_force_sub_channel()
        clean_ch = channel.lstrip("@")
        kb = [
            [InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{clean_ch}")],
            [InlineKeyboardButton("✅ Joined / Verify", callback_data=_encode_cb("verify_sub"))],
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

    # 2. Check if user is responding with a Trim Time Range
    waiting_trim_url = context.user_data.get("waiting_trim_url")
    time_range = parse_time_range(text)
    if waiting_trim_url and time_range:
        url = context.user_data.pop("waiting_trim_url")
        start_t, end_t = time_range
        await _execute_trim_download(update, context, url, start_t, end_t)
        return

    # 3. Check for valid URL
    if not is_valid_url(text):
        await update.message.reply_text(
            "⚠️ Please send a valid URL.\n\nType /help for supported platforms or instructions."
        )
        return

    urls = extract_urls(text)
    url = resolve_short_url(urls[0])

    # Check if user sent inline trim time with the URL (e.g. "https://... 00:10-00:30")
    if time_range:
        start_t, end_t = time_range
        await _execute_trim_download(update, context, url, start_t, end_t)
        return

    # 4. Fetch Info & Display Quality Options for all media
    context.user_data["pending_url"] = url
    context.user_data["pending_info"] = None

    thinking_msg = await update.message.reply_text("🔍 Fetching media info, please wait...")
    await context.bot.send_chat_action(chat_id, ChatAction.TYPING)

    try:
        info = await get_media_info(url)
    except Exception as e:
        logger.error("get_media_info failed: %s", e)
        await thinking_msg.edit_text(
            f"❌ <b>Failed to fetch info.</b>\n\n<code>{_h(str(e))}</code>",
            parse_mode="HTML",
        )
        return

    if not info:
        await thinking_msg.edit_text(
            "❌ <b>Could not fetch media info.</b>\n\n"
            "Possible reasons:\n"
            "• The URL is private or geo-restricted\n"
            "• The platform is not supported\n"
            "• The link has expired\n\n"
            "Try a different link or check /help.",
            parse_mode="HTML",
        )
        return

    # ── Instagram Carousel / Multi-item Albums ──
    if info.get("is_carousel"):
        await _execute_carousel_download(update, context, url, info, thinking_msg)
        return

    # ── Single Photo (Pinterest Image, Instagram Photo, etc.) ──
    if info.get("is_photo"):
        await _execute_photo_download(update, context, url, info, thinking_msg)
        return

    context.user_data["pending_info"] = info

    emoji   = info["emoji"]
    platform = _h(info["platform"].capitalize())
    title   = _h(truncate(info["title"], 60))
    uploader = _h(truncate(info["uploader"], 40))
    duration = _h(info["duration"])

    info_text = (
        f"{emoji} <b>{platform}</b>\n\n"
        f"📌 <b>Title:</b> {title}\n"
        f"👤 <b>By:</b> {uploader}\n"
        f"⏱ <b>Duration:</b> {duration}\n\n"
        f"Choose what to download:"
    )

    buttons = []
    quality_row = []

    for h_val in info["video_qualities"]:
        cb = _encode_cb("video", str(h_val))
        quality_row.append(InlineKeyboardButton(f"🎬 {h_val}p", callback_data=cb))
        if len(quality_row) == 3:
            buttons.append(quality_row)
            quality_row = []

    if not info["video_qualities"]:
        buttons.append([InlineKeyboardButton("🎬 Download Video", callback_data=_encode_cb("video", "best"))])
    elif quality_row:
        buttons.append(quality_row)

    # Audio & Trimming options
    action_row = []
    if info.get("has_audio") or info["platform"] in ("soundcloud", "youtube", "twitter", "instagram", "tiktok"):
        action_row.append(InlineKeyboardButton("🎵 MP3 Audio", callback_data=_encode_cb("audio", "")))

    action_row.append(InlineKeyboardButton("✂️ Trim Clip", callback_data=_encode_cb("trim", "")))
    buttons.append(action_row)

    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data=_encode_cb("cancel", ""))])

    try:
        await thinking_msg.edit_text(
            info_text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
    except TelegramError:
        pass


async def _send_video_message(
    bot,
    chat_id: int,
    file_path: str,
    caption: str,
) -> None:
    """
    Sends video to Telegram with exact width, height, duration and optimized thumbnail
    so the Telegram player renders crisp preview and correct aspect ratio (16:9, 9:16 Shorts/Reels, 1:1).
    """
    loop = asyncio.get_event_loop()
    meta = await loop.run_in_executor(None, get_video_metadata_and_thumb, file_path)
    thumb_path = meta.get("thumbnail_path")
    thumb_file = None
    if thumb_path and os.path.isfile(thumb_path):
        try:
            thumb_file = open(thumb_path, "rb")
        except Exception as e:
            logger.warning("Could not open thumbnail %s: %s", thumb_path, e)
            thumb_file = None

    try:
        with open(file_path, "rb") as f:
            await bot.send_video(
                chat_id=chat_id,
                video=f,
                caption=caption,
                width=meta.get("width"),
                height=meta.get("height"),
                duration=meta.get("duration"),
                thumbnail=thumb_file,
                supports_streaming=True,
                read_timeout=120,
                write_timeout=120,
            )
    finally:
        if thumb_file:
            try:
                thumb_file.close()
            except Exception:
                pass


# ── 🖼️ Single Photo Download (Pinterest, Instagram Photo, etc.) ────────────

async def _execute_photo_download(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    url: str,
    info: dict,
    msg,
) -> None:
    """Downloads a photo and sends it to Telegram with original HD quality."""
    chat_id = update.effective_chat.id
    platform = info.get("platform", "Photo").capitalize()
    emoji = info.get("emoji", "📌")
    await msg.edit_text(
        f"{emoji} <b>Downloading {platform} image in full HD...</b>\n\n⏳ Please wait...",
        parse_mode="HTML",
    )
    await context.bot.send_chat_action(chat_id, ChatAction.UPLOAD_PHOTO)

    photo_url = info.get("photo_url")
    loop = asyncio.get_event_loop()
    file_path = await loop.run_in_executor(None, download_photo, photo_url)

    if not file_path or not os.path.isfile(file_path):
        await msg.edit_text(
            "❌ <b>Could not download image.</b> Media might be private or unavailable.",
            parse_mode="HTML",
        )
        return

    size = file_size_mb(file_path)
    title = truncate(info.get("title", f"{platform} Image"), 60)
    uploader = truncate(info.get("uploader", "Pinterest"), 40)
    caption = (
        f"{emoji} {platform}\n"
        f"📌 {title}\n"
        f"📦 {size:.2f} MB\n\n"
        f"🤖 @butcherbombit_bot"
    )

    try:
        with open(file_path, "rb") as f:
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=f,
                caption=caption,
                read_timeout=120,
                write_timeout=120,
            )
        increment_download_count(update.effective_user.id)
        try:
            await msg.delete()
        except TelegramError:
            pass
    except Exception as e:
        logger.error("Failed to send photo: %s", e)
        await context.bot.send_message(
            chat_id,
            f"❌ <b>Failed to send image:</b>\n<code>{_h(str(e))}</code>",
            parse_mode="HTML",
        )
    finally:
        cleanup_session(file_path)


# ── 📸 Instagram Carousel & Multi-Item Album Download ───────────────────────

async def _execute_carousel_download(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    url: str,
    info: dict,
    msg,
) -> None:
    """Downloads all slides/items from an Instagram Carousel or Stories collection and sends as an album."""
    chat_id = update.effective_chat.id
    count = info.get("carousel_count", 0)
    count_text = f" ({count} items)" if count > 0 else ""
    await msg.edit_text(
        f"📸 <b>Instagram Carousel detected{count_text}!</b>\n\n"
        "⏳ Downloading all photos and videos...",
        parse_mode="HTML",
    )
    await context.bot.send_chat_action(chat_id, ChatAction.UPLOAD_PHOTO)

    loop = asyncio.get_event_loop()
    items, raw_info = await loop.run_in_executor(None, download_carousel_media, url)

    if not items:
        await msg.edit_text(
            "❌ <b>Could not download carousel items.</b>\n"
            "Media might be private, deleted, or require login.",
            parse_mode="HTML",
        )
        return

    await msg.edit_text(
        f"📤 <b>Uploading {len(items)} items to Telegram as Media Album...</b>",
        parse_mode="HTML",
    )
    await context.bot.send_chat_action(chat_id, ChatAction.UPLOAD_PHOTO)

    title = truncate(info.get("title", "Instagram Post"), 60)
    uploader = truncate(info.get("uploader", "Instagram User"), 40)
    caption = (
        f"📸 Instagram ({len(items)} items)\n"
        f"📌 {title}\n"
        f"👤 {uploader}\n\n"
        f"🤖 @butcherbombit_bot"
    )

    try:
        if len(items) == 1:
            it = items[0]
            if it["type"] == "photo":
                with open(it["path"], "rb") as f:
                    await context.bot.send_photo(chat_id, photo=f, caption=caption)
            else:
                await _send_video_message(context.bot, chat_id, it["path"], caption)
        else:
            # Telegram allows maximum 10 media items per send_media_group
            batches = [items[i:i + 10] for i in range(0, len(items), 10)]
            for b_idx, batch in enumerate(batches):
                media_group = []
                opened_files = []
                for idx, it in enumerate(batch):
                    is_first = (b_idx == 0 and idx == 0)
                    item_caption = caption if is_first else None
                    if it["type"] == "photo":
                        f = open(it["path"], "rb")
                        opened_files.append(f)
                        media_group.append(InputMediaPhoto(media=f, caption=item_caption))
                    else:
                        f = open(it["path"], "rb")
                        opened_files.append(f)
                        thumb_f = None
                        if it.get("thumbnail_path") and os.path.isfile(it["thumbnail_path"]):
                            thumb_f = open(it["thumbnail_path"], "rb")
                            opened_files.append(thumb_f)
                        media_group.append(
                            InputMediaVideo(
                                media=f,
                                caption=item_caption,
                                width=it.get("width"),
                                height=it.get("height"),
                                duration=it.get("duration"),
                                thumbnail=thumb_f,
                                supports_streaming=True,
                            )
                        )
                try:
                    await context.bot.send_media_group(
                        chat_id=chat_id,
                        media=media_group,
                        read_timeout=180,
                        write_timeout=180,
                    )
                finally:
                    for f in opened_files:
                        try:
                            f.close()
                        except Exception:
                            pass

        increment_download_count(update.effective_user.id)
        try:
            await msg.delete()
        except TelegramError:
            pass
    except Exception as e:
        logger.error("Failed to send carousel media group: %s", e)
        await context.bot.send_message(
            chat_id,
            f"❌ <b>Failed to send album:</b>\n<code>{_h(str(e))}</code>",
            parse_mode="HTML",
        )
    finally:
        if items and "path" in items[0]:
            cleanup_session(items[0]["path"])


# ── ⚡ Fast Reel / Short Download ───────────────────────────────────────────

async def _execute_fast_reel_download(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str) -> None:
    """Instant 1-click download for Instagram Reels, YouTube Shorts, and TikTok."""
    chat_id = update.effective_chat.id
    msg = await update.message.reply_text("⚡ <b>Fast-Download started for Reel/Short...</b>\n\n⏳ Please wait...", parse_mode="HTML")
    await context.bot.send_chat_action(chat_id, ChatAction.UPLOAD_VIDEO)

    progress_state: dict = {"status": "starting", "percent": 0}
    progress_task = asyncio.create_task(
        _progress_updater(context.bot, chat_id, msg.message_id, progress_state, "Fast Reel/Short Download")
    )

    try:
        file_path = await download_video(url, height=None, progress_state=progress_state)
    except Exception as e:
        progress_state["status"] = "error"
        await msg.edit_text(f"❌ <b>Download error:</b>\n<code>{_h(str(e))}</code>", parse_mode="HTML")
        return
    finally:
        progress_state["status"] = "done"
        progress_task.cancel()

    if not file_path or not os.path.exists(file_path):
        await msg.edit_text("❌ <b>Download failed.</b> Media might be private or unavailable.", parse_mode="HTML")
        return

    size = file_size_mb(file_path)
    if size > MAX_FILE_SIZE_MB:
        await msg.edit_text(f"⚠️ File is too large ({size:.1f} MB). Max allowed is {MAX_FILE_SIZE_MB} MB.", parse_mode="HTML")
        cleanup_session(file_path)
        return

    # Fetch basic info for clean caption
    try:
        info = await get_media_info(url)
    except Exception:
        info = None

    platform_name = (info.get("platform", "Video") if info else "Video").capitalize()
    video_title = truncate(info.get("title", "Short / Reel"), 60) if info else "Short / Reel"
    emoji = info.get("emoji", "🎬") if info else "🎬"

    caption = (
        f"{emoji} {platform_name}\n"
        f"📌 {video_title}\n"
        f"📦 {size:.1f} MB\n\n"
        f"🤖 @butcherbombit_bot"
    )

    await context.bot.send_chat_action(chat_id, ChatAction.UPLOAD_VIDEO)
    try:
        await _send_video_message(context.bot, chat_id, file_path, caption)
        increment_download_count(update.effective_user.id)
        # Delete progress message cleanly
        try:
            await msg.delete()
        except TelegramError:
            pass
    except Exception as e:
        logger.error("send_video failed: %s", e)
        await context.bot.send_message(chat_id, f"❌ Failed to send video: {_h(str(e))}", parse_mode="HTML")
    finally:
        cleanup_session(file_path)


# ── ✂️ Trim Download Execution ───────────────────────────────────────────────

async def _execute_trim_download(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    url: str,
    start_t: str,
    end_t: str,
) -> None:
    """Download video and trim with ffmpeg to requested interval."""
    chat_id = update.effective_chat.id
    status_msg = await update.message.reply_text(
        f"✂️ <b>Cutting clip:</b> <code>{start_t}</code> to <code>{end_t}</code>\n\n⬇️ Downloading media...",
        parse_mode="HTML",
    )
    await context.bot.send_chat_action(chat_id, ChatAction.UPLOAD_VIDEO)

    progress_state: dict = {"status": "starting", "percent": 0}
    progress_task = asyncio.create_task(
        _progress_updater(context.bot, chat_id, status_msg.message_id, progress_state, f"Trimming ({start_t} - {end_t})")
    )

    try:
        file_path = await download_video(url, height=None, progress_state=progress_state)
    except Exception as e:
        progress_state["status"] = "error"
        await status_msg.edit_text(f"❌ <b>Download error:</b>\n<code>{_h(str(e))}</code>", parse_mode="HTML")
        return
    finally:
        progress_state["status"] = "done"
        progress_task.cancel()

    if not file_path or not os.path.exists(file_path):
        await status_msg.edit_text("❌ <b>Download failed.</b> Try again later.", parse_mode="HTML")
        return

    # Execute ffmpeg trim
    try:
        await status_msg.edit_text("✂️ <b>Trimming video clip...</b>", parse_mode="HTML")
    except Exception:
        pass

    trimmed_path = trim_media(file_path, start_t, end_t)
    target_path = trimmed_path if trimmed_path and os.path.isfile(trimmed_path) else file_path

    size = file_size_mb(target_path)
    if size > MAX_FILE_SIZE_MB:
        await status_msg.edit_text(f"⚠️ Trimmed file too large ({size:.1f} MB).", parse_mode="HTML")
        cleanup_session(file_path)
        return

    try:
        info = await get_media_info(url)
    except Exception:
        info = None

    platform_name = (info.get("platform", "Video") if info else "Video").capitalize()
    video_title = truncate(info.get("title", "Video Clip"), 50) if info else "Video Clip"

    caption = (
        f"🎬 {platform_name} (✂️ {start_t} - {end_t})\n"
        f"📌 {video_title}\n"
        f"📦 {size:.1f} MB\n\n"
        f"🤖 @butcherbombit_bot"
    )

    await context.bot.send_chat_action(chat_id, ChatAction.UPLOAD_VIDEO)
    try:
        await _send_video_message(context.bot, chat_id, target_path, caption)
        increment_download_count(update.effective_user.id)
        try:
            await status_msg.delete()
        except TelegramError:
            pass
    except Exception as e:
        await context.bot.send_message(chat_id, f"❌ Failed to send trimmed video: {_h(str(e))}", parse_mode="HTML")
    finally:
        cleanup_session(file_path)


# ── Callback / button handler ────────────────────────────────────────────────

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    cb     = _decode_cb(query.data)
    action = cb.get("a", "")
    extra  = cb.get("e", "")

    # Static page buttons
    if action == "help":
        from handlers.commands import HELP_TEXT
        await query.edit_message_text(HELP_TEXT, parse_mode="HTML")
        return
    if action == "about":
        from handlers.commands import ABOUT_TEXT
        await query.edit_message_text(ABOUT_TEXT, parse_mode="HTML")
        return
    if action == "cancel":
        await query.edit_message_text("✅ Download cancelled.")
        return

    # Verify channel membership callback
    if action == "verify_sub":
        user_id = query.from_user.id
        if await check_user_subscription(user_id, context.bot):
            await query.answer("✅ Verification successful!", show_alert=True)
            await query.edit_message_text(
                "✅ <b>Channel Verification Successful!</b>\n\n"
                "Ab aap koi bhi video ya audio link bhej kar download kar sakte hain. 🚀",
                parse_mode="HTML",
            )
        else:
            await query.answer("❌ Aapne abhi tak channel join nahi kiya! Pehle join karein.", show_alert=True)
        return

    # ── LARGE VIDEO: COMPRESS OPTION ─────────────────────────────────────────
    if action == "large_compress":
        file_path = context.user_data.get("large_file_path")
        if not file_path or not os.path.exists(file_path):
            await query.edit_message_text("⚠️ File expired. Please send the link again.")
            return

        chat_id = update.effective_chat.id
        await query.edit_message_text(
            "🗜️ <b>Compressing video to fit under 50 MB...</b>\n\n"
            "⏳ Please wait, this takes about 1-2 minutes...",
            parse_mode="HTML",
        )
        await context.bot.send_chat_action(chat_id, ChatAction.UPLOAD_VIDEO)

        loop = asyncio.get_event_loop()
        compressed_path = await loop.run_in_executor(None, compress_video_to_size, file_path, 46.0)

        target = compressed_path if compressed_path and os.path.isfile(compressed_path) else file_path
        comp_size = file_size_mb(target)

        media_info = context.user_data.get("pending_info") or {}
        m_title = truncate(media_info.get("title", ""), 60)
        m_emoji = media_info.get("emoji", "🎬")
        m_platform = media_info.get("platform", "").capitalize()

        caption = (
            f"{m_emoji} {m_platform} (🗜️ Compressed)\n"
            f"📌 {m_title}\n"
            f"📦 {comp_size:.1f} MB\n\n"
            f"🤖 @butcherbombit_bot"
        )

        try:
            await query.edit_message_text("📤 <b>Uploading compressed video...</b>", parse_mode="HTML")
        except Exception:
            pass

        try:
            await _send_video_message(context.bot, chat_id, target, caption)
            increment_download_count(query.from_user.id)
            try:
                await query.delete_message()
            except Exception:
                pass
        except Exception as e:
            logger.error("Failed to send compressed video: %s", e)
            await context.bot.send_message(chat_id, f"❌ Failed to send video: {_h(str(e))}", parse_mode="HTML")
        finally:
            cleanup_session(file_path)
            context.user_data.pop("large_file_path", None)
        return

    # ── LARGE VIDEO: SPLIT INTO PARTS OPTION ─────────────────────────────────
    if action == "large_split":
        file_path = context.user_data.get("large_file_path")
        if not file_path or not os.path.exists(file_path):
            await query.edit_message_text("⚠️ File expired. Please send the link again.")
            return

        chat_id = update.effective_chat.id
        await query.edit_message_text(
            "✂️ <b>Splitting video into high-quality parts...</b>\n\n"
            "⏳ Please wait...",
            parse_mode="HTML",
        )
        await context.bot.send_chat_action(chat_id, ChatAction.UPLOAD_VIDEO)

        loop = asyncio.get_event_loop()
        parts = await loop.run_in_executor(None, split_video_by_size, file_path, 46.0)

        if not parts:
            await query.edit_message_text("❌ Failed to split video.")
            cleanup_session(file_path)
            return

        total_parts = len(parts)
        media_info = context.user_data.get("pending_info") or {}
        m_title = truncate(media_info.get("title", ""), 50)
        m_emoji = media_info.get("emoji", "🎬")
        m_platform = media_info.get("platform", "").capitalize()

        for idx, part_path in enumerate(parts):
            part_num = idx + 1
            part_size = file_size_mb(part_path)
            caption = (
                f"{m_emoji} {m_platform} (Part {part_num}/{total_parts})\n"
                f"📌 {m_title}\n"
                f"📦 {part_size:.1f} MB\n\n"
                f"🤖 @butcherbombit_bot"
            )
            try:
                await query.edit_message_text(f"📤 <b>Uploading Part {part_num}/{total_parts}...</b>", parse_mode="HTML")
            except Exception:
                pass

            try:
                await _send_video_message(context.bot, chat_id, part_path, caption)
            except Exception as e:
                logger.error("Failed to send part %s: %s", part_num, e)

        increment_download_count(query.from_user.id)
        try:
            await query.delete_message()
        except Exception:
            pass
        cleanup_session(file_path)
        context.user_data.pop("large_file_path", None)
        return

    # ── LARGE VIDEO: CANCEL OPTION ──────────────────────────────────────────
    if action == "large_cancel":
        file_path = context.user_data.pop("large_file_path", None)
        if file_path:
            cleanup_session(file_path)
        await query.edit_message_text("✅ Download cancelled.")
        return

    url = context.user_data.get("pending_url")
    if not url:
        await query.edit_message_text("⚠️ Session expired. Please send the URL again.")
        return

    chat_id = update.effective_chat.id

    # ── TRIM BUTTON CLICKED ──────────────────────────────────────────────────
    if action == "trim":
        context.user_data["waiting_trim_url"] = url
        await query.edit_message_text(
            "✂️ <b>Send Video Cut Timestamps</b>\n\n"
            "Reply with start and end time.\n"
            "<b>Format:</b> <code>00:15 - 00:45</code> or <code>1:20 - 2:00</code>\n\n"
            "Send your message now:",
            parse_mode="HTML",
        )
        return

    # ── VIDEO DOWNLOAD ───────────────────────────────────────────────────────
    if action == "video":
        height = None if extra in ("", "best") else (int(extra) if extra.isdigit() else None)
        label = f"Downloading video ({height}p)" if height else "Downloading video (best quality)"
        await query.edit_message_text(f"⬇️ <b>{label}</b>\n\n⏳ Starting download...", parse_mode="HTML")
        await context.bot.send_chat_action(chat_id, ChatAction.UPLOAD_VIDEO)

        progress_state: dict = {"status": "starting", "percent": 0}
        progress_task = asyncio.create_task(
            _progress_updater(context.bot, chat_id, query.message.message_id, progress_state, label)
        )

        try:
            file_path = await download_video(url, height=height, progress_state=progress_state)
        except Exception as e:
            progress_state["status"] = "error"
            await context.bot.send_message(
                chat_id,
                f"❌ <b>Download error:</b>\n<code>{_h(str(e))}</code>",
                parse_mode="HTML",
            )
            return
        finally:
            progress_state["status"] = "done"
            progress_task.cancel()

        if not file_path or not os.path.exists(file_path):
            await context.bot.send_message(
                chat_id,
                "❌ <b>Download failed.</b>\nThe media might be unavailable, private, or geo-restricted.\n\nTry a lower quality or a different link.",
                parse_mode="HTML",
            )
            return

        size = file_size_mb(file_path)
        if size > MAX_FILE_SIZE_MB:
            context.user_data["large_file_path"] = file_path
            context.user_data["large_file_size"] = size
            kb = [
                [InlineKeyboardButton("🗜️ Compress Video (Single File < 50MB)", callback_data=_encode_cb("large_compress"))],
                [InlineKeyboardButton("✂️ Split into Parts (High Quality)", callback_data=_encode_cb("large_split"))],
                [InlineKeyboardButton("❌ Cancel", callback_data=_encode_cb("large_cancel"))],
            ]
            await query.edit_message_text(
                f"⚠️ <b>Video size is {size:.1f} MB (Exceeds Telegram 50 MB limit)</b>\n\n"
                "Aap is video ko kaise receive karna chahte hain?\n\n"
                "• <b>🗜️ Compress:</b> Video compress hoke <b>1 hi single file</b> mein aayegi.\n"
                "• <b>✂️ Split:</b> Original high quality rahegi aur <b>Part 1, Part 2</b> mein aayegi.\n\n"
                "Neeche se apna option chunein:",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(kb),
            )
            return

        media_info = context.user_data.get("pending_info") or {}
        m_title = truncate(media_info.get("title", ""), 60)
        m_emoji = media_info.get("emoji", "🎬")
        m_platform = media_info.get("platform", "").capitalize()

        caption = (
            f"{m_emoji} {m_platform}\n"
            f"📌 {m_title}\n"
            f"📦 {size:.1f} MB\n\n"
            f"🤖 @butcherbombit_bot"
        )

        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=query.message.message_id,
                text="📤 <b>Uploading to Telegram...</b>",
                parse_mode="HTML",
            )
        except TelegramError:
            pass

        await context.bot.send_chat_action(chat_id, ChatAction.UPLOAD_VIDEO)
        try:
            await _send_video_message(context.bot, chat_id, file_path, caption)
            increment_download_count(query.from_user.id)
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=query.message.message_id)
            except TelegramError:
                pass
        except Exception as e:
            logger.error("send_video failed: %s", e)
            await context.bot.send_message(
                chat_id,
                f"❌ <b>Failed to send video:</b>\n<code>{_h(str(e))}</code>",
                parse_mode="HTML",
            )
        finally:
            cleanup_session(file_path)

    # ── AUDIO DOWNLOAD WITH ALBUM ART & NATIVE METADATA ─────────────────────
    elif action == "audio":
        label = "Downloading audio (MP3)"
        await query.edit_message_text(f"⬇️ <b>{label}</b>\n\n⏳ Starting download...", parse_mode="HTML")
        await context.bot.send_chat_action(chat_id, ChatAction.UPLOAD_VOICE)

        progress_state: dict = {"status": "starting", "percent": 0}
        progress_task = asyncio.create_task(
            _progress_updater(context.bot, chat_id, query.message.message_id, progress_state, label)
        )

        try:
            file_path = await download_audio(url, progress_state=progress_state)
        except Exception as e:
            progress_state["status"] = "error"
            await context.bot.send_message(
                chat_id,
                f"❌ <b>Audio download error:</b>\n<code>{_h(str(e))}</code>",
                parse_mode="HTML",
            )
            return
        finally:
            progress_state["status"] = "done"
            progress_task.cancel()

        if not file_path or not os.path.exists(file_path):
            await context.bot.send_message(
                chat_id,
                "❌ <b>Audio download failed.</b>\nTry a different link.",
                parse_mode="HTML",
            )
            return

        size = file_size_mb(file_path)
        if size > MAX_FILE_SIZE_MB:
            await context.bot.send_message(
                chat_id,
                f"⚠️ Audio file too large (<b>{size:.1f} MB</b>). Max allowed: <b>{MAX_FILE_SIZE_MB} MB</b>.",
                parse_mode="HTML",
            )
            cleanup_session(file_path)
            return

        media_info = context.user_data.get("pending_info") or {}
        m_title = truncate(media_info.get("title", "Audio Track"), 60)
        m_uploader = truncate(media_info.get("uploader", "Unknown Artist"), 40)
        m_emoji = media_info.get("emoji", "🎵")
        m_platform = media_info.get("platform", "").capitalize()

        caption = (
            f"{m_emoji} {m_platform}\n"
            f"📌 {m_title}\n"
            f"📦 {size:.1f} MB\n\n"
            f"🤖 @butcherbombit_bot"
        )

        # Check for album art thumbnail
        thumb_path = get_session_thumbnail(file_path)

        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=query.message.message_id,
                text="📤 <b>Uploading audio...</b>",
                parse_mode="HTML",
            )
        except TelegramError:
            pass

        await context.bot.send_chat_action(chat_id, ChatAction.UPLOAD_VOICE)
        try:
            with open(file_path, "rb") as f:
                thumb_file = open(thumb_path, "rb") if thumb_path and os.path.isfile(thumb_path) else None
                try:
                    await context.bot.send_audio(
                        chat_id,
                        audio=f,
                        caption=caption,
                        title=m_title,
                        performer=m_uploader,
                        thumbnail=thumb_file,
                    )
                finally:
                    if thumb_file:
                        thumb_file.close()

            increment_download_count(query.from_user.id)
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=query.message.message_id)
            except TelegramError:
                pass
        except Exception as e:
            logger.error("send_audio failed: %s", e)
            await context.bot.send_message(
                chat_id,
                f"❌ <b>Failed to send audio:</b>\n<code>{_h(str(e))}</code>",
                parse_mode="HTML",
            )
        finally:
            cleanup_session(file_path)

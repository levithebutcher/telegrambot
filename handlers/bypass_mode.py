"""
Bypass Mode Handler: Processes short links and ad-links when user is in Bypass Mode.
Handles 1 to 5 links per message, live progress feedback, and clean error messages.
"""

import html
import logging
from typing import List
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from utils.downloader import extract_urls
from utils.db import add_or_update_user
from handlers.admin import check_user_subscription, get_force_sub_channel
from bypass_engine import bypass, sanitize_url

logger = logging.getLogger(__name__)

MAX_LINKS_PER_MESSAGE = 5


def _clean_error_message(err: str) -> str:
    """Format raw error string into user-friendly explanation."""
    err_lower = (err or "").lower()
    if "cloudflare" in err_lower or "captcha" in err_lower:
        return "Cloudflare/captcha ki wajah se bypass nahi ho saka"
    if "timer" in err_lower or "handshake" in err_lower or "inputs" in err_lower:
        return "Timer/handshake fail hua (site badal gayi ho sakti hai)"
    if "rate limit" in err_lower:
        return "Rate limit exceed ho gaya hai (max 10 link per minute)"
    if "ssrf" in err_lower or "blocked" in err_lower:
        return "Security restriction: Yeh URL allow nahi hai"
    if "timeout" in err_lower:
        return "Link open hone me zyada waqt laga (timeout)"
    if "site supported" in err_lower:
        return "Site supported nahi hai"
    return err or "Bypass nahi ho saka"


async def bypass_mode_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles text messages containing links in Bypass Mode."""
    user = update.effective_user
    if not user or not update.message or not update.message.text:
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

    raw_text = update.message.text.strip()
    urls = extract_urls(raw_text)

    if not urls:
        await update.message.reply_text(
            "🔓 <b>Bypass Mode Active</b>\n\n"
            "Koi short link ya ad-link bhejein jise aap bypass/expand karna chahte hain (ek message me max 5 links).\n\n"
            "💡 <i>Download Mode me wapas jaane ke liye /mode use karein.</i>",
            parse_mode="HTML",
        )
        return

    selected_urls = urls[:MAX_LINKS_PER_MESSAGE]
    total_count = len(selected_urls)

    status_msg = await update.message.reply_text(
        f"⏳ <b>Bypass shuru ho raha hai...</b> (0/{total_count})",
        parse_mode="HTML",
    )

    results_text_blocks = []

    for index, link in enumerate(selected_urls, start=1):
        try:
            # Update progress
            await status_msg.edit_text(
                f"⏳ <b>Bypassing link {index}/{total_count}...</b>\n<code>{html.escape(sanitize_url(link))}</code>",
                parse_mode="HTML",
            )
        except Exception:
            pass

        try:
            res = await bypass(link, user_id=user.id)
            if res.success:
                block = (
                    f"✅ <b>Link #{index}:</b>\n"
                    f"• <b>Original:</b> <code>{html.escape(res.original_url)}</code>\n"
                    f"• <b>Direct URL:</b> {res.final_url}\n"
                    f"• <b>Hops:</b> {res.hops} | <b>Method:</b> <code>{html.escape(res.method)}</code>\n"
                )
            else:
                clean_err = _clean_error_message(res.error or "")
                block = (
                    f"❌ <b>Link #{index}:</b>\n"
                    f"• <b>Original:</b> <code>{html.escape(res.original_url)}</code>\n"
                    f"• <b>Reason:</b> {html.escape(clean_err)}\n"
                )
            results_text_blocks.append(block)

        except Exception as e:
            logger.exception("Unexpected exception in bypass_mode_handler for %s: %s", sanitize_url(link), e)
            block = (
                f"❌ <b>Link #{index}:</b>\n"
                f"• <b>Original:</b> <code>{html.escape(sanitize_url(link))}</code>\n"
                f"• <b>Reason:</b> Bypass karte waqt anjaan error aaya\n"
            )
            results_text_blocks.append(block)

    footer = "\n💡 <i>Mode switch karne ke liye /mode command use karein.</i>"
    final_output = "\n".join(results_text_blocks) + footer

    try:
        await status_msg.edit_text(final_output, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        logger.error("Failed to send final bypass message: %s", e)
        # Fallback without HTML formatting if parsing error
        try:
            await status_msg.edit_text(final_output, disable_web_page_preview=True)
        except Exception:
            pass

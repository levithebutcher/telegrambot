"""
Telethon MTProto Uploader for large files up to 2GB (2048 MB).
Bypasses the standard Telegram Bot HTTP API 50MB limit using MTProto API_ID & API_HASH.
Credentials are read strictly from environment variables (.env) to prevent credential leakage.
"""

import os
import logging
import asyncio
from typing import Optional, Callable
from telethon import TelegramClient
from telethon.tl.types import DocumentAttributeVideo, DocumentAttributeAudio

logger = logging.getLogger(__name__)

API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

_telethon_client: Optional[TelegramClient] = None
_client_lock = asyncio.Lock()


def is_telethon_configured() -> bool:
    """Return True if API_ID, API_HASH, and BOT_TOKEN are all provided."""
    api_id = os.getenv("API_ID")
    api_hash = os.getenv("API_HASH")
    bot_token = os.getenv("BOT_TOKEN")
    return bool(api_id and api_hash and bot_token)


async def get_telethon_client() -> Optional[TelegramClient]:
    """
    Get or initialize the shared Telethon TelegramClient session.
    Uses bot_token for authentication, enabling bot uploads up to 2GB.
    F16 FIX: Reconnects automatically if the MTProto session dropped.
    """
    global _telethon_client

    if not is_telethon_configured():
        return None

    # Fast path: already connected
    if _telethon_client is not None and _telethon_client.is_connected():
        return _telethon_client

    async with _client_lock:
        # Re-check under lock
        if _telethon_client is not None and _telethon_client.is_connected():
            return _telethon_client

        # F16 FIX: If client exists but disconnected, try reconnecting first
        if _telethon_client is not None and not _telethon_client.is_connected():
            try:
                await _telethon_client.connect()
                if _telethon_client.is_connected():
                    logger.info("Telethon MTProto client reconnected successfully.")
                    return _telethon_client
            except Exception as e:
                logger.warning("Telethon reconnect failed (%s). Re-initializing client.", e)
                _telethon_client = None

        try:
            api_id = int(os.getenv("API_ID"))
            api_hash = os.getenv("API_HASH")
            bot_token = os.getenv("BOT_TOKEN")

            session_name = "bot_uploader"
            client = TelegramClient(session_name, api_id, api_hash)
            await client.start(bot_token=bot_token)
            _telethon_client = client
            logger.info("🚀 Telethon MTProto client initialized for up to 2GB uploads.")
            return _telethon_client
        except Exception as e:
            logger.error("Failed to initialize Telethon MTProto client: %s", e)
            return None



async def send_video_via_telethon(
    chat_id: int,
    file_path: str,
    caption: str,
    meta: Optional[dict] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> bool:
    """Send video via Telethon MTProto client (supports up to 2GB)."""
    client = await get_telethon_client()
    if not client:
        raise RuntimeError("Telethon MTProto client is not configured or unavailable.")

    attributes = []
    thumb_path = None

    if meta:
        duration = int(meta.get("duration") or 0)
        width = int(meta.get("width") or 0)
        height = int(meta.get("height") or 0)
        attributes.append(
            DocumentAttributeVideo(
                duration=duration,
                w=width,
                h=height,
                supports_streaming=True,
            )
        )
        t_path = meta.get("thumbnail_path")
        if t_path and os.path.isfile(t_path):
            thumb_path = t_path

    logger.info("Uploading large video (%s) to %s via Telethon MTProto...", file_path, chat_id)
    await client.send_file(
        entity=chat_id,
        file=file_path,
        caption=caption,
        thumb=thumb_path,
        attributes=attributes,
        supports_streaming=True,
        progress_callback=progress_callback,
    )
    logger.info("Successfully uploaded large video via Telethon MTProto to %s", chat_id)
    return True


async def send_audio_via_telethon(
    chat_id: int,
    file_path: str,
    caption: str,
    title: Optional[str] = None,
    performer: Optional[str] = None,
    thumb_path: Optional[str] = None,
    duration: int = 0,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> bool:
    """Send audio via Telethon MTProto client (supports up to 2GB)."""
    client = await get_telethon_client()
    if not client:
        raise RuntimeError("Telethon MTProto client is not configured or unavailable.")

    attributes = [
        DocumentAttributeAudio(
            duration=duration,
            title=title or "Audio Track",
            performer=performer or "Unknown Artist",
        )
    ]

    t_file = thumb_path if (thumb_path and os.path.isfile(thumb_path)) else None

    logger.info("Uploading large audio (%s) to %s via Telethon MTProto...", file_path, chat_id)
    await client.send_file(
        entity=chat_id,
        file=file_path,
        caption=caption,
        thumb=t_file,
        attributes=attributes,
        progress_callback=progress_callback,
    )
    logger.info("Successfully uploaded large audio via Telethon MTProto to %s", chat_id)
    return True

"""
Core download logic using yt-dlp.
Handles all platform downloads: YouTube, Instagram, TikTok, Twitter/X,
Facebook, Reddit, SoundCloud, and direct URLs.
Includes album art embedding, video trimming, and reel/short detection.
"""

import os
import asyncio
import logging
import re
import uuid
import subprocess
from pathlib import Path
from typing import Optional, Tuple

import yt_dlp
from PIL import Image

logger = logging.getLogger(__name__)

DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "downloads")
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "50"))
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
FFMPEG_PATH = os.getenv(
    "FFMPEG_PATH",
    r"C:\Users\Lenovo\AppData\Local\Microsoft\WinGet\Packages\yt-dlp.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-N-125875-g5d4d3bdc61-win64-gpl\bin\ffmpeg.exe",
)


# ── Platform detection ──────────────────────────────────────────────────────

PLATFORM_PATTERNS = {
    "youtube":     re.compile(r"(youtube\.com|youtu\.be)", re.I),
    "instagram":   re.compile(r"instagram\.com", re.I),
    "twitter":     re.compile(r"(twitter\.com|x\.com)", re.I),
    "tiktok":      re.compile(r"tiktok\.com", re.I),
    "facebook":    re.compile(r"(facebook\.com|fb\.watch)", re.I),
    "reddit":      re.compile(r"reddit\.com", re.I),
    "soundcloud":  re.compile(r"soundcloud\.com", re.I),
    "pinterest":   re.compile(r"(pinterest\.[a-z.]+|pin\.it)", re.I),
    "vimeo":       re.compile(r"vimeo\.com", re.I),
    "dailymotion": re.compile(r"dailymotion\.com", re.I),
    "twitch":      re.compile(r"twitch\.tv", re.I),
    "spotify":     re.compile(r"open\.spotify\.com", re.I),
}

PLATFORM_EMOJIS = {
    "youtube":     "🎬",
    "instagram":   "📸",
    "twitter":     "🐦",
    "tiktok":      "🎵",
    "facebook":    "📘",
    "reddit":      "🟠",
    "soundcloud":  "🎧",
    "pinterest":   "📌",
    "vimeo":       "🎞️",
    "dailymotion": "📺",
    "twitch":      "🟣",
    "spotify":     "🟢",
    "unknown":     "🌐",
}

URL_REGEX = re.compile(
    r"https?://[^\s/$.?#].[^\s]*",
    re.I,
)


def resolve_short_url(url: str) -> str:
    """Follow redirects for short URLs like pin.it, bit.ly, etc."""
    u = url.lower()
    if "pin.it" in u or "t.co" in u or "bit.ly" in u:
        try:
            import urllib.request
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                return resp.geturl()
        except Exception as e:
            logger.warning("Could not resolve short url %s: %s", url, e)
    return url


def _download_direct_file(url: str, output_path: str) -> bool:
    """Download a direct CDN media file using urllib with browser headers."""
    try:
        import urllib.request
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "*/*",
        }
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=40) as resp:
            with open(output_path, "wb") as f:
                while chunk := resp.read(65536):
                    f.write(chunk)
        return os.path.isfile(output_path) and os.path.getsize(output_path) > 100
    except Exception as e:
        logger.warning("Direct download failed for %s: %s", url[:60], e)
        return False


def extract_pinterest_pin_fallback(url: str) -> Optional[dict]:
    """Fallback scraper for Pinterest image pins when yt-dlp doesn't extract formats."""
    try:
        import urllib.request
        resolved = resolve_short_url(url)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        req = urllib.request.Request(resolved, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        # Find og:image
        m_img = re.search(r'<meta\s+property=["\']og:image["\']\s+content=["\']([^"\']+)["\']', html)
        if not m_img:
            m_img = re.search(r'<meta\s+content=["\']([^"\']+)["\']\s+property=["\']og:image["\']', html)
        if not m_img:
            return None

        img_url = m_img.group(1)
        orig_img_url = re.sub(r"/(?:736x|564x|474x|236x)/", "/originals/", img_url)

        m_title = re.search(r'<meta\s+property=["\']og:title["\']\s+content=["\']([^"\']+)["\']', html)
        title = m_title.group(1) if m_title else "Pinterest Image"

        return {
            "title": title,
            "uploader": "Pinterest",
            "url": resolved,
            "is_photo": True,
            "photo_url": orig_img_url,
            "platform": "pinterest",
            "emoji": "📌",
            "formats": [],
            "thumbnails": [{"url": orig_img_url}],
        }
    except Exception as e:
        logger.warning("Pinterest fallback extraction error for %s: %s", url, e)
        return None


def get_best_photo_url(info: dict) -> Optional[str]:
    """Finds highest-resolution direct image URL from info dict (supporting Pinterest, Instagram, etc.)."""
    if info.get("photo_url"):
        return info["photo_url"]

    thumbs = info.get("thumbnails") or []
    # 1. Look for Pinterest /originals/ URL
    for t in thumbs:
        u = t.get("url", "")
        if "/originals/" in u:
            return u

    # 2. Find largest resolution thumbnail
    if thumbs:
        best_t = max(thumbs, key=lambda t: (t.get("width") or 0) * (t.get("height") or 0))
        u = best_t.get("url")
        if u:
            if "pinimg.com" in u:
                u = re.sub(r"/(?:736x|564x|474x|236x)/", "/originals/", u)
            return u

    # 3. Fallback to info.get("thumbnail") or info.get("url")
    u = info.get("thumbnail") or info.get("url")
    if u:
        if "pinimg.com" in u:
            u = re.sub(r"/(?:736x|564x|474x|236x)/", "/originals/", u)
        return u

    return None


def download_photo(photo_url: str) -> Optional[str]:
    """Downloads a photo to a session directory and ensures it is a clean JPEG."""
    out_dir = _make_session_dir()
    file_id = uuid.uuid4().hex[:8]
    target_path = os.path.join(out_dir, f"photo_{file_id}.jpg")

    success = _download_direct_file(photo_url, target_path)
    if not success and "/originals/" in photo_url:
        # Fallback to 736x if originals is not found
        fallback_url = photo_url.replace("/originals/", "/736x/")
        success = _download_direct_file(fallback_url, target_path)

    if success and os.path.isfile(target_path):
        try:
            with Image.open(target_path) as im:
                if im.format not in ("JPEG", "JPG"):
                    im.convert("RGB").save(target_path, "JPEG", quality=95)
        except Exception:
            pass
        return target_path
    return None


def detect_platform(url: str) -> str:
    for name, pattern in PLATFORM_PATTERNS.items():
        if pattern.search(url):
            return name
    return "unknown"


def extract_urls(text: str) -> list[str]:
    return URL_REGEX.findall(text)


def is_reel_or_short(url: str) -> bool:
    """Detect if URL is an Instagram Reel, YouTube Short, TikTok, or Twitter/X clip."""
    u = url.lower()
    return (
        "youtube.com/shorts/" in u
        or "youtu.be/shorts/" in u
        or "instagram.com/reel/" in u
        or "instagram.com/reels/" in u
        or "tiktok.com" in u
        or "x.com" in u
        or "twitter.com" in u
    )


# ── Time range parsing & Trimming ──────────────────────────────────────────

def parse_time_range(text: str) -> Optional[Tuple[str, str]]:
    """
    Parses timestamps like '00:10-00:40', '1:20 2:30', '10s - 30s', '00:15 to 01:00'.
    Returns (start_time, end_time) or None.
    """
    pattern = re.compile(
        r"(\d{1,2}(?::\d{1,2})*(?:\.\d+)?s?)\s*(?:-|to|\s)\s*(\d{1,2}(?::\d{1,2})*(?:\.\d+)?s?)",
        re.I,
    )
    m = pattern.search(text)
    if m:
        s = m.group(1).rstrip("s").strip()
        e = m.group(2).rstrip("s").strip()
        return s, e
    return None


def trim_media(input_path: str, start_time: str, end_time: str) -> Optional[str]:
    """
    Trims audio/video using ffmpeg -ss and -to.
    Returns trimmed file path or None on failure.
    """
    if not os.path.isfile(input_path):
        return None

    p = Path(input_path)
    out_path = str(p.parent / f"cut_{p.name}")
    ffmpeg_exe = FFMPEG_PATH if os.path.isfile(FFMPEG_PATH) else "ffmpeg"

    # Fast stream copy first (instant & lossless)
    cmd = [
        ffmpeg_exe,
        "-y",
        "-ss", str(start_time).strip(),
        "-to", str(end_time).strip(),
        "-i", input_path,
        "-c", "copy",
        out_path,
    ]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60)
        if res.returncode == 0 and os.path.isfile(out_path) and os.path.getsize(out_path) > 1024:
            return out_path

        # Fallback: re-encode if stream copy fails on keyframes
        cmd_reencode = [
            ffmpeg_exe,
            "-y",
            "-ss", str(start_time).strip(),
            "-to", str(end_time).strip(),
            "-i", input_path,
            out_path,
        ]
        res2 = subprocess.run(cmd_reencode, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=90)
        if res2.returncode == 0 and os.path.isfile(out_path) and os.path.getsize(out_path) > 1024:
            return out_path
    except Exception as e:
        logger.error("trim_media error: %s", e)
    return None


def get_session_thumbnail(file_path: str) -> Optional[str]:
    """
    Finds any thumbnail generated in the session directory.
    Converts .webp to .jpg if needed for Telegram compatibility.
    """
    try:
        folder = Path(file_path).parent
        for ext in ("*.jpg", "*.jpeg", "*.png"):
            matches = list(folder.glob(ext))
            if matches:
                return str(matches[0])

        # If .webp exists, convert to .jpg
        webp_files = list(folder.glob("*.webp"))
        if webp_files:
            webp_path = webp_files[0]
            jpg_path = webp_path.with_suffix(".jpg")
            with Image.open(webp_path) as im:
                im.convert("RGB").save(jpg_path, "JPEG")
            return str(jpg_path)
    except Exception as e:
        logger.warning("get_session_thumbnail warning: %s", e)
    return None


def get_video_metadata_and_thumb(file_path: str) -> dict:
    """
    Extracts width, height, duration and generates an optimized JPEG thumbnail (max 320x320, < 200KB)
    for Telegram's send_video.
    Returns:
        {
            "width": Optional[int],
            "height": Optional[int],
            "duration": Optional[int],
            "thumbnail_path": Optional[str],
        }
    """
    meta = {
        "width": None,
        "height": None,
        "duration": None,
        "thumbnail_path": None,
    }
    if not file_path or not os.path.isfile(file_path):
        return meta

    ffmpeg_exe = FFMPEG_PATH if os.path.isfile(FFMPEG_PATH) else "ffmpeg"
    duration_sec = 0.0

    # 1. Probe video with ffmpeg to get duration and dimensions
    try:
        cmd = [ffmpeg_exe, "-i", file_path]
        res = subprocess.run(cmd, stderr=subprocess.PIPE, text=True, timeout=15)
        stderr = res.stderr

        m_dur = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", stderr)
        if m_dur:
            h, mn, s = m_dur.groups()
            duration_sec = int(h) * 3600 + int(mn) * 60 + float(s)
            meta["duration"] = int(round(duration_sec))

        m_wh = re.search(r"Stream #.*Video:.*,\s*(\d{2,5})x(\d{2,5})", stderr)
        if m_wh:
            meta["width"] = int(m_wh.group(1))
            meta["height"] = int(m_wh.group(2))
    except Exception as e:
        logger.warning("Error probing video %s: %s", file_path, e)

    # 2. Generate thumbnail frame
    try:
        p = Path(file_path)
        folder = p.parent
        raw_thumb = str(folder / f"raw_thumb_{p.stem}.jpg")
        final_thumb = str(folder / f"thumb_{p.stem}.jpg")

        seek_time = 1.0
        if 0 < duration_sec < 2.0:
            seek_time = max(0.1, duration_sec / 2.0)

        thumb_cmd = [
            ffmpeg_exe,
            "-y",
            "-ss", str(round(seek_time, 2)),
            "-i", file_path,
            "-vframes", "1",
            "-q:v", "2",
            raw_thumb,
        ]
        subprocess.run(thumb_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)

        if not os.path.isfile(raw_thumb) or os.path.getsize(raw_thumb) < 100:
            thumb_cmd[2] = "0"
            subprocess.run(thumb_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)

        source_thumb = None
        if os.path.isfile(raw_thumb) and os.path.getsize(raw_thumb) > 100:
            source_thumb = raw_thumb
        else:
            existing = get_session_thumbnail(file_path)
            if existing and os.path.isfile(existing):
                source_thumb = existing

        if source_thumb and os.path.isfile(source_thumb):
            with Image.open(source_thumb) as img:
                actual_w, actual_h = img.size
                if meta["width"] and meta["height"]:
                    if (meta["width"] > meta["height"] and actual_w < actual_h) or (
                        meta["width"] < meta["height"] and actual_w > actual_h
                    ):
                        meta["width"], meta["height"] = meta["height"], meta["width"]
                else:
                    meta["width"], meta["height"] = actual_w, actual_h

                img_copy = img.copy()
                img_copy.thumbnail((320, 320), Image.Resampling.LANCZOS)
                img_copy.convert("RGB").save(final_thumb, "JPEG", quality=85, optimize=True)

            if os.path.isfile(final_thumb) and os.path.getsize(final_thumb) > 100:
                meta["thumbnail_path"] = final_thumb

        if os.path.isfile(raw_thumb):
            try:
                os.remove(raw_thumb)
            except OSError:
                pass
    except Exception as e:
        logger.warning("Error generating thumbnail for %s: %s", file_path, e)

    return meta


# ── yt-dlp helpers ──────────────────────────────────────────────────────────

def _make_session_dir() -> str:
    """Create a unique temp folder for this download session."""
    session_id = uuid.uuid4().hex[:8]
    path = os.path.join(DOWNLOAD_DIR, session_id)
    os.makedirs(path, exist_ok=True)
    return path


def get_cookie_file_path() -> Optional[str]:
    """
    Checks if cookies are provided via:
    1. A physical file named 'cookies.txt'
    2. An environment variable 'YOUTUBE_COOKIES' (raw text or base64)
    Returns path to the cookie file or None.
    """
    if os.path.isfile("cookies.txt") and os.path.getsize("cookies.txt") > 10:
        return "cookies.txt"

    env_cookies = os.getenv("YOUTUBE_COOKIES", "").strip()
    if env_cookies:
        cookie_path = os.path.join(DOWNLOAD_DIR, "session_cookies.txt")
        try:
            import base64
            try:
                decoded = base64.b64decode(env_cookies).decode("utf-8")
                if "youtube.com" in decoded or "# Netscape" in decoded:
                    env_cookies = decoded
            except Exception:
                pass
            with open(cookie_path, "w", encoding="utf-8") as f:
                f.write(env_cookies)
            return cookie_path
        except Exception as e:
            logger.warning("Could not write YOUTUBE_COOKIES: %s", e)

    return None


def _base_ydl_opts(out_dir: str) -> dict:
    opts = {
        "outtmpl": os.path.join(out_dir, "%(title).60s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": 30,
        "retries": 5,
        "concurrent_fragment_downloads": 4,
        "fragment_retries": 3,
        "fragment_timeout": 15,
        "extractor_args": {
            "youtube": {
                "player_client": ["android"],
            }
        },
    }

    ffmpeg_dir = str(Path(FFMPEG_PATH).parent)
    if os.path.isfile(FFMPEG_PATH):
        opts["ffmpeg_location"] = ffmpeg_dir
    return opts


def _get_info(url: str) -> Optional[dict]:
    """Fetch video metadata without downloading, trying android client first without cookies."""
    url = resolve_short_url(url)
    cookie_path = get_cookie_file_path()

    # Step 1: Try Android client for YouTube (works without cookies, bypasses cloud blocks)
    if "youtube.com" in url or "youtu.be" in url:
        android_opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "noplaylist": True,
            "socket_timeout": 30,
            "extractor_args": {
                "youtube": {
                    "player_client": ["android"],
                }
            },
        }
        try:
            with yt_dlp.YoutubeDL(android_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info and (info.get("formats") or info.get("title")):
                    return info
        except Exception as e:
            logger.warning("Android client extraction failed for %s: %s", url, e)

    is_ig = "instagram.com" in url.lower()

    # Step 2: Try with cookies (if provided) on web/mweb
    if cookie_path:
        cookie_opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "noplaylist": not is_ig,
            "socket_timeout": 30,
            "cookiefile": cookie_path,
        }
        try:
            with yt_dlp.YoutubeDL(cookie_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info and (info.get("formats") or info.get("title") or info.get("entries") or info.get("thumbnails")):
                    return info
        except Exception as e:
            logger.warning("Cookie extraction failed for %s: %s", url, e)

    # Step 3: Default extraction (for Instagram, Twitter/X, TikTok, Reddit, Pinterest, etc.)
    default_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": not is_ig,
        "socket_timeout": 30,
    }
    try:
        with yt_dlp.YoutubeDL(default_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info:
                return info
    except Exception as e:
        logger.warning("Default info extraction failed for %s: %s", url, e)

    # Step 4: Fallback scraper for Pinterest image pins
    if "pinterest." in url.lower() or "pin.it" in url.lower():
        fallback_info = extract_pinterest_pin_fallback(url)
        if fallback_info:
            return fallback_info

    return None


def _download_file(url: str, ydl_opts: dict, progress_state: Optional[dict] = None) -> Optional[str]:
    """Run yt-dlp download and return the downloaded file path."""
    downloaded_files: list[str] = []

    class PathCollector(yt_dlp.postprocessor.common.PostProcessor):
        def run(self, info):
            path = info.get("filepath") or info.get("_filename")
            if path:
                downloaded_files.append(path)
            return [], info

    def _progress_hook(d: dict) -> None:
        if progress_state is None:
            return
        status = d.get("status", "")
        progress_state["status"] = status

        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes", 0)
            percent = (downloaded / total * 100) if total else 0
            speed = d.get("speed") or 0
            eta = d.get("eta") or 0

            progress_state["percent"] = round(percent, 1)
            progress_state["downloaded"] = downloaded
            progress_state["total"] = total
            progress_state["speed"] = speed
            progress_state["eta"] = eta

        elif status == "finished":
            progress_state["percent"] = 100
            progress_state["status"] = "merging"

    ydl_opts["progress_hooks"] = [_progress_hook]

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.add_post_processor(PathCollector(), when="post_process")
            info = ydl.extract_info(url, download=True)

        if downloaded_files:
            return downloaded_files[-1]

        out_dir = ydl_opts.get("outtmpl", "")
        if out_dir:
            folder = str(Path(out_dir).parent)
            files = sorted(
                Path(folder).iterdir(),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            media_files = [str(f) for f in files if f.suffix.lower() in ('.mp4', '.mp3', '.m4a', '.webm', '.mkv')]
            if media_files:
                return media_files[0]
            if files:
                return str(files[0])
    except Exception as e:
        logger.error("Download failed for %s: %s", url, e)
        if progress_state is not None:
            progress_state["status"] = "error"
            progress_state["error"] = str(e)
    return None


# ── Public API ──────────────────────────────────────────────────────────────

async def get_media_info(url: str) -> Optional[dict]:
    """Return cleaned metadata dict for display."""
    loop = asyncio.get_event_loop()
    info = await loop.run_in_executor(None, _get_info, url)
    if not info:
        return None

    platform = detect_platform(url)
    emoji = PLATFORM_EMOJIS.get(platform, "🌐")
    duration = info.get("duration")
    duration_str = (
        f"{int(duration // 60)}:{int(duration % 60):02d}" if duration else "N/A"
    )

    formats = info.get("formats") or []
    video_qualities = []
    seen_heights = set()
    for f in formats:
        h = f.get("height")
        vcodec = f.get("vcodec", "none")
        if h and vcodec != "none" and h not in seen_heights:
            seen_heights.add(h)
            video_qualities.append(h)
    video_qualities = sorted(video_qualities, reverse=True)

    has_audio = any(
        f.get("acodec", "none") != "none" and f.get("vcodec", "none") == "none"
        for f in formats
    )

    entries = [e for e in info.get("entries", []) if e] if info.get("entries") else []
    is_carousel = len(entries) > 1
    carousel_count = len(entries) if is_carousel else 0

    photo_url = get_best_photo_url(info)
    is_photo = (len(video_qualities) == 0 and photo_url is not None) or bool(info.get("is_photo"))

    title = info.get("title") or "Unknown Title"
    if is_carousel:
        duration_str = f"{carousel_count} Items"
        title = f"Instagram Album ({carousel_count} items)"
    elif is_photo:
        duration_str = "Photo"

    return {
        "title": title[:80],
        "uploader": info.get("uploader") or info.get("channel") or "Unknown",
        "duration": duration_str,
        "platform": platform,
        "emoji": emoji,
        "video_qualities": video_qualities[:5],
        "has_audio": has_audio or platform == "soundcloud",
        "thumbnail": info.get("thumbnail"),
        "url": url,
        "is_carousel": is_carousel,
        "carousel_count": carousel_count,
        "is_photo": is_photo,
        "photo_url": photo_url,
    }


def download_carousel_media(url: str) -> Tuple[list[dict], dict]:
    """
    Downloads all slides/items from an Instagram carousel or multi-item story.
    Returns (items, post_info)
    """
    out_dir = _make_session_dir()
    cookie_path = get_cookie_file_path()

    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": False,
        "socket_timeout": 30,
    }
    if cookie_path:
        opts["cookiefile"] = cookie_path

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        logger.error("Failed to extract carousel info for %s: %s", url, e)
        return [], {}

    if not info:
        return [], {}

    entries = [e for e in info.get("entries", []) if e] if info.get("entries") else [info]
    items: list[dict] = []

    for idx, entry in enumerate(entries):
        slide_num = idx + 1
        formats = entry.get("formats") or []
        video_formats = [
            f for f in formats
            if f.get("vcodec") != "none" or (f.get("ext") == "mp4" and f.get("acodec") != "none")
        ]

        if video_formats:
            target_path = os.path.join(out_dir, f"slide_{slide_num:02d}.mp4")
            best_fmt = max(
                video_formats,
                key=lambda f: (f.get("height") or 0) * (f.get("width") or 0) or (f.get("tbr") or 0),
            )
            video_url = best_fmt.get("url")

            downloaded = False
            if video_url:
                downloaded = _download_direct_file(video_url, target_path)

            if not downloaded:
                entry_opts = _base_ydl_opts(out_dir)
                entry_opts["outtmpl"] = target_path
                entry_opts["format"] = "bestvideo+bestaudio/best"
                try:
                    with yt_dlp.YoutubeDL(entry_opts) as ydl_single:
                        ydl_single.download([entry.get("webpage_url") or entry.get("url") or url])
                    if os.path.isfile(target_path) and os.path.getsize(target_path) > 100:
                        downloaded = True
                except Exception as e:
                    logger.warning("Fallback download failed for slide %d: %s", slide_num, e)

            if os.path.isfile(target_path) and os.path.getsize(target_path) > 100:
                meta = get_video_metadata_and_thumb(target_path)
                items.append({
                    "type": "video",
                    "path": target_path,
                    "width": meta.get("width") or best_fmt.get("width"),
                    "height": meta.get("height") or best_fmt.get("height"),
                    "duration": meta.get("duration") or int(entry.get("duration") or 0),
                    "thumbnail_path": meta.get("thumbnail_path"),
                })
        else:
            target_path = os.path.join(out_dir, f"slide_{slide_num:02d}.jpg")
            thumbs = entry.get("thumbnails") or []
            if thumbs:
                best_img = max(thumbs, key=lambda t: (t.get("width") or 0) * (t.get("height") or 0))
                img_url = best_img.get("url")
            else:
                img_url = entry.get("url")

            if img_url and _download_direct_file(img_url, target_path):
                try:
                    with Image.open(target_path) as im:
                        if im.format not in ("JPEG", "JPG"):
                            im.convert("RGB").save(target_path, "JPEG", quality=95)
                except Exception:
                    pass
                items.append({
                    "type": "photo",
                    "path": target_path,
                })

    return items, info


async def download_video(
    url: str,
    height: Optional[int] = None,
    progress_state: Optional[dict] = None,
) -> Optional[str]:
    """Download best video (optionally at specific height). Returns file path."""
    out_dir = _make_session_dir()
    opts = _base_ydl_opts(out_dir)

    if height:
        fmt = (
            f"bestvideo[height={height}][ext=mp4]+bestaudio[ext=m4a]/"
            f"bestvideo[height<={height}]+bestaudio/best[height<={height}]/best"
        )
    else:
        fmt = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best"

    opts["format"] = fmt
    opts["merge_output_format"] = "mp4"

    platform = detect_platform(url)
    if platform == "tiktok":
        opts["format"] = "download_addr-0/bestvideo+bestaudio/best"

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _download_file, url, opts, progress_state)


async def download_audio(
    url: str,
    progress_state: Optional[dict] = None,
) -> Optional[str]:
    """Download best audio as MP3 with ID3 tags & Album Art."""
    out_dir = _make_session_dir()
    opts = _base_ydl_opts(out_dir)
    opts.update(
        {
            "format": "bestaudio/best",
            "writethumbnail": True,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                },
                {"key": "FFmpegMetadata", "add_metadata": True},
                {"key": "EmbedThumbnail", "already_have_thumbnail": False},
            ],
        }
    )
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _download_file, url, opts, progress_state)


def file_size_mb(path: str) -> float:
    try:
        return os.path.getsize(path) / (1024 * 1024)
    except OSError:
        return 0.0


def cleanup_session(path: str) -> None:
    """Remove the session download folder."""
    try:
        folder = str(Path(path).parent)
        for f in Path(folder).iterdir():
            f.unlink(missing_ok=True)
        Path(folder).rmdir()
    except Exception as e:
        logger.warning("Cleanup failed: %s", e)


def get_media_duration(file_path: str) -> float:
    """Get duration of a media file in seconds using ffprobe or ffmpeg."""
    ffmpeg_exe = FFMPEG_PATH if os.path.isfile(FFMPEG_PATH) else "ffmpeg"
    try:
        cmd = [ffmpeg_exe, "-i", file_path]
        res = subprocess.run(cmd, stderr=subprocess.PIPE, text=True, timeout=15)
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", res.stderr)
        if m:
            h, mn, s = m.groups()
            return int(h) * 3600 + int(mn) * 60 + float(s)
    except Exception as e:
        logger.warning("Could not determine duration for %s: %s", file_path, e)
    return 0.0


def compress_video_to_size(input_path: str, target_size_mb: float = 46.0) -> Optional[str]:
    """
    Compress video to target_size_mb so it fits under Telegram's 50MB limit.
    Returns compressed file path or None on failure.
    """
    if not os.path.isfile(input_path):
        return None

    duration = get_media_duration(input_path)
    if duration <= 0:
        duration = 600.0  # fallback assumption 10 min

    # Calculate target video bitrate in kbps
    audio_bitrate_k = 96
    total_target_bits = target_size_mb * 8 * 1024 * 1024
    total_bitrate_k = (total_target_bits / duration) / 1000
    video_bitrate_k = max(int(total_bitrate_k - audio_bitrate_k), 100)

    p = Path(input_path)
    out_path = str(p.parent / f"compressed_{p.stem}.mp4")
    ffmpeg_exe = FFMPEG_PATH if os.path.isfile(FFMPEG_PATH) else "ffmpeg"

    cmd = [
        ffmpeg_exe,
        "-y",
        "-i", input_path,
        "-c:v", "libx264",
        "-b:v", f"{video_bitrate_k}k",
        "-maxrate", f"{int(video_bitrate_k * 1.3)}k",
        "-bufsize", f"{video_bitrate_k * 2}k",
        "-preset", "faster",
        "-c:a", "aac",
        "-b:a", f"{audio_bitrate_k}k",
        out_path,
    ]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=300)
        if res.returncode == 0 and os.path.isfile(out_path) and os.path.getsize(out_path) > 1024:
            return out_path
        logger.error("Compress failed: %s", res.stderr)
    except Exception as e:
        logger.error("compress_video_to_size error: %s", e)
    return None


def split_video_by_size(input_path: str, max_chunk_mb: float = 46.0) -> list[str]:
    """
    Split a large video into multiple parts so each part is under max_chunk_mb.
    Returns list of file paths for the parts.
    """
    import math

    if not os.path.isfile(input_path):
        return []

    total_size = file_size_mb(input_path)
    duration = get_media_duration(input_path)
    if total_size <= max_chunk_mb or duration <= 0:
        return [input_path]

    num_parts = math.ceil(total_size / max_chunk_mb)
    part_duration = duration / num_parts

    p = Path(input_path)
    ffmpeg_exe = FFMPEG_PATH if os.path.isfile(FFMPEG_PATH) else "ffmpeg"
    parts: list[str] = []

    for i in range(num_parts):
        start_t = i * part_duration
        out_part = str(p.parent / f"part_{i + 1}_{p.stem}.mp4")

        cmd = [
            ffmpeg_exe,
            "-y",
            "-ss", str(round(start_t, 2)),
            "-t", str(round(part_duration, 2)),
            "-i", input_path,
            "-c", "copy",
            out_part,
        ]
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120)
            if res.returncode == 0 and os.path.isfile(out_part) and os.path.getsize(out_part) > 1024:
                parts.append(out_part)
            else:
                cmd_reencode = [
                    ffmpeg_exe,
                    "-y",
                    "-ss", str(round(start_t, 2)),
                    "-t", str(round(part_duration, 2)),
                    "-i", input_path,
                    "-preset", "faster",
                    out_part,
                ]
                res2 = subprocess.run(cmd_reencode, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=240)
                if res2.returncode == 0 and os.path.isfile(out_part):
                    parts.append(out_part)
        except Exception as e:
            logger.error("Error creating part %s: %s", i + 1, e)

    return parts

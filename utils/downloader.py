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
    "pinterest":   re.compile(r"pinterest\.(com|co\.uk|ca|de|fr)", re.I),
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


# ── yt-dlp helpers ──────────────────────────────────────────────────────────

def _make_session_dir() -> str:
    """Create a unique temp folder for this download session."""
    session_id = uuid.uuid4().hex[:8]
    path = os.path.join(DOWNLOAD_DIR, session_id)
    os.makedirs(path, exist_ok=True)
    return path


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
                "player_client": ["android", "web"],
            }
        },
    }
    ffmpeg_dir = str(Path(FFMPEG_PATH).parent)
    if os.path.isfile(FFMPEG_PATH):
        opts["ffmpeg_location"] = ffmpeg_dir
    return opts


def _get_info(url: str) -> Optional[dict]:
    """Fetch video metadata without downloading, trying android client first."""
    client_candidates = [
        ["android"],
        ["android", "web"],
        None,  # default
    ]

    for clients in client_candidates:
        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "noplaylist": True,
            "socket_timeout": 30,
        }
        if clients and ("youtube.com" in url or "youtu.be" in url):
            opts["extractor_args"] = {
                "youtube": {
                    "player_client": clients,
                }
            }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info:
                    return info
        except Exception as e:
            logger.warning("Info extraction failed with clients %s for %s: %s", clients, url, e)

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

    return {
        "title": info.get("title", "Unknown Title")[:80],
        "uploader": info.get("uploader") or info.get("channel") or "Unknown",
        "duration": duration_str,
        "platform": platform,
        "emoji": emoji,
        "video_qualities": video_qualities[:5],
        "has_audio": has_audio or platform == "soundcloud",
        "thumbnail": info.get("thumbnail"),
        "url": url,
    }


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

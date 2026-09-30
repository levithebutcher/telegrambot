"""
Miscellaneous helper functions.
"""

import re


def is_valid_url(text: str) -> bool:
    """Check if a string contains a valid HTTP/HTTPS URL."""
    pattern = re.compile(r"https?://[^\s/$.?#].[^\s]*", re.I)
    return bool(pattern.search(text))


def human_size(num_bytes: float) -> str:
    """Convert bytes to human-readable string."""
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} TB"


def truncate(text: str, max_len: int = 50) -> str:
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


def progress_bar(percent: int, width: int = 10) -> str:
    filled = int(width * percent / 100)
    return "█" * filled + "░" * (width - filled)

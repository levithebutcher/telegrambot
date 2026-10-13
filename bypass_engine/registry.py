"""
Registry of supported sites for Bypass Engine.
Supports JSON configuration loading for dynamic site definitions.
"""

import os
import re
import json
import logging
from dataclasses import dataclass, asdict
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class SiteEntry:
    name: str
    host_regex: str
    api_domain: Optional[str] = None
    referer: Optional[str] = None
    wait_seconds: int = 5
    status: str = "working"  # "working", "broken", "unknown"
    last_checked: Optional[str] = None

    def matches(self, url: str) -> bool:
        """Check if URL matches the host_regex of this site entry."""
        try:
            return bool(re.search(self.host_regex, url, re.IGNORECASE))
        except re.error:
            return False


DEFAULT_SITES: List[SiteEntry] = [
    SiteEntry(
        name="try2link",
        host_regex=r"(try2link\.com|try2fly\.net)",
        api_domain="https://try2link.com",
        referer="https://youtube.com/",
        wait_seconds=6,
        status="working",
    ),
    SiteEntry(
        name="gyanilinks",
        host_regex=r"(gyanilinks\.com|gyanilinks\.in)",
        api_domain="https://gyanilinks.com",
        referer="https://gyanilinks.com/",
        wait_seconds=5,
        status="working",
    ),
    SiteEntry(
        name="droplink",
        host_regex=r"(droplink\.co|droplink\.in)",
        api_domain="https://droplink.co",
        referer="https://droplink.co/",
        wait_seconds=5,
        status="working",
    ),
    SiteEntry(
        name="adlinkfly_generic",
        host_regex=r"(clk\.wiki|ouo\.today|shrinkme\.io|shrinkearn\.com)",
        api_domain=None,  # Dynamic: uses landing host
        referer=None,
        wait_seconds=6,
        status="working",
    ),
    SiteEntry(
        name="linkvertise",
        host_regex=r"(linkvertise\.(com|download)|link-center\.net|link-to\.net|up-to-down\.net|direct-link\.net|file-link\.net)",
        api_domain="https://linkvertise.com",
        referer="https://linkvertise.com/",
        wait_seconds=5,
        status="broken",  # Protected by Cloudflare Turnstile / anti-bot challenge
    ),
]

SITES: List[SiteEntry] = list(DEFAULT_SITES)

# Optional external JSON configuration path
CONFIG_DIR = os.path.dirname(os.path.dirname(__file__))
EXTERNAL_CONFIG_PATH = os.path.join(CONFIG_DIR, "bypass_sites.json")


def load_sites_from_json(path: str = EXTERNAL_CONFIG_PATH) -> None:
    """Load or update site definitions from an external JSON file if present."""
    global SITES
    if not os.path.isfile(path):
        return

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            new_sites = []
            for item in data:
                if isinstance(item, dict) and "name" in item and "host_regex" in item:
                    new_sites.append(SiteEntry(**item))
            if new_sites:
                SITES = new_sites
                logger.info("Loaded %d sites from %s", len(SITES), path)
    except Exception as e:
        logger.error("Failed to load external bypass sites from %s: %s", path, e)


def find_site(url: str) -> Optional[SiteEntry]:
    """Find matching SiteEntry for the given URL."""
    for site in SITES:
        if site.matches(url):
            return site
    return None


# Load custom config if available on import
load_sites_from_json()

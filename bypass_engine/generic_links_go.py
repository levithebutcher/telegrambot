"""
Generic links/go bypass solver for URL shorteners using the AdLinkFly / MightyScripts pattern.

Attribution:
    Concept and flow adapted from FZBypassBot (MIT License) - FZBypass/bypass/ddl.py
    (functions transcript(), try2link(), gyanilinks()).
    Re-implemented cleanly using async aiohttp with BeautifulSoup4 and SSRF checks.
"""

import asyncio
import logging
from typing import Optional, Tuple
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup
import aiohttp

from .registry import SiteEntry
from .ssrf import is_safe_url_async, sanitize_url

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def _detect_captcha_or_cf(html: str) -> bool:
    """Check if page contains Cloudflare or CAPTCHA challenges."""
    html_lower = html.lower()
    cf_markers = [
        "just a moment...",
        "cf-browser-verification",
        "cf-turnstile",
        "challenges.cloudflare.com",
        "g-recaptcha",
        "h-captcha",
        "recaptcha/api.js",
        "hcaptcha.com",
    ]
    return any(marker in html_lower for marker in cf_markers)


async def bypass_generic_links_go(
    url: str,
    site: Optional[SiteEntry] = None,
    timeout_seconds: float = 30.0,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Solve a generic links/go shortener:
    1. GET landing URL with cookies kept in session.
    2. Parse hidden <input> pairs using BeautifulSoup.
    3. Wait wait_seconds (asyncio.sleep).
    4. POST to {api_domain}/links/go with X-Requested-With: XMLHttpRequest.
    5. Parse JSON response and return url.

    Returns:
        (final_url, None) on success
        (None, error_message) on failure
    """
    safe, reason = await is_safe_url_async(url)
    if not safe:
        return None, reason

    parsed_landing = urlparse(url)
    base_domain = f"{parsed_landing.scheme}://{parsed_landing.netloc}"

    api_base = site.api_domain if (site and site.api_domain) else base_domain
    post_url = urljoin(api_base, "/links/go")

    safe_post, post_reason = await is_safe_url_async(post_url)
    if not safe_post:
        return None, post_reason

    referer = site.referer if (site and site.referer) else url
    wait_time = site.wait_seconds if site else 5

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": referer,
    }

    timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    try:
        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            # Step 1: GET landing URL
            logger.info("Bypass landing GET: %s", sanitize_url(url))
            async with session.get(url, allow_redirects=True) as resp:
                if resp.status >= 400:
                    return None, f"Landing page error (HTTP {resp.status})"
                html = await resp.text(errors="replace")
                final_landing_url = str(resp.url)

            # Check for Cloudflare / Captcha
            if _detect_captcha_or_cf(html):
                return None, "Cloudflare/captcha ki wajah se bypass nahi ho saka"

            # Step 2: Parse hidden <input> tags
            soup = BeautifulSoup(html, "html.parser")
            inputs = soup.find_all("input")
            data = {}
            for inp in inputs:
                name = inp.get("name")
                value = inp.get("value", "")
                if name:
                    data[name] = value

            if not data:
                return None, "Form ya inputs nahi mile (site badal gayi ho sakti hai)"

            # Step 3: Wait wait_time seconds
            logger.info("Waiting %s seconds for bypass token generation...", wait_time)
            await asyncio.sleep(wait_time)

            # Step 4: POST to /links/go
            post_headers = {
                "User-Agent": USER_AGENT,
                "X-Requested-With": "XMLHttpRequest",
                "Referer": final_landing_url,
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Accept": "application/json, text/javascript, */*; q=0.01",
            }

            logger.info("Bypass POST to: %s", sanitize_url(post_url))
            async with session.post(post_url, data=data, headers=post_headers) as post_resp:
                if post_resp.status == 200:
                    try:
                        res_json = await post_resp.json(content_type=None)
                        if isinstance(res_json, dict) and "url" in res_json and res_json["url"]:
                            return res_json["url"], None
                        if isinstance(res_json, dict) and "message" in res_json:
                            return None, f"Bypass API error: {res_json['message']}"
                    except Exception:
                        pass
                    # If not json or missing url
                    text = await post_resp.text(errors="replace")
                    if _detect_captcha_or_cf(text):
                        return None, "Cloudflare/captcha ki wajah se bypass nahi ho saka"
                    return None, "Timer/handshake fail hua (site badal gayi ho sakti hai)"
                elif post_resp.status in (403, 503):
                    return None, "Cloudflare/captcha ki wajah se bypass nahi ho saka"
                else:
                    return None, f"Timer/handshake fail hua (HTTP {post_resp.status})"

    except asyncio.TimeoutError:
        return None, "Request timed out (30s)"
    except aiohttp.ClientError as e:
        logger.exception("aiohttp client error in generic_links_go: %s", e)
        return None, "Network connection error"
    except Exception as e:
        logger.exception("Unexpected error in generic_links_go: %s", e)
        return None, "Bypass process me anjaan error aaya"

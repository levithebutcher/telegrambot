"""
HTTP redirect chain expander for generic shorteners (bit.ly, tinyurl, t.co, etc.).
Uses httpx with HEAD first, falling back to streaming GET, validating SSRF on each hop.
"""

import logging
from typing import Optional, Tuple
from urllib.parse import urljoin
import httpx

from .ssrf import is_safe_url_async, sanitize_url

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

REDIRECT_STATUSES = {301, 302, 303, 307, 308}


async def expand_redirects(
    url: str,
    max_hops: int = 10,
    timeout_seconds: float = 15.0,
) -> Tuple[str, int, Optional[str]]:
    """
    Follow redirect chains step-by-step up to max_hops.
    Validates SSRF safety on every hop before making the request.

    Returns:
        (final_url, hops, error)
    """
    current_url = url
    hops = 0
    visited = {current_url}

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
    }

    try:
        async with httpx.AsyncClient(
            headers=headers,
            timeout=timeout_seconds,
            verify=True,
            follow_redirects=False,
        ) as client:
            while hops < max_hops:
                # SSRF check before requesting
                safe, reason = await is_safe_url_async(current_url)
                if not safe:
                    return current_url, hops, reason

                logger.info("Expand hop %d: %s", hops, sanitize_url(current_url))

                # Try HEAD first
                try:
                    resp = await client.head(current_url)
                except httpx.RequestError:
                    resp = None

                # Fallback to GET (streamed) if HEAD rejected or errored
                if resp is None or resp.status_code in (405, 501):
                    try:
                        async with client.stream("GET", current_url) as stream_resp:
                            resp = stream_resp
                    except httpx.RequestError as e:
                        logger.warning("GET error expanding %s: %s", sanitize_url(current_url), e)
                        break

                if resp is None:
                    break

                # If redirect status
                if resp.status_code in REDIRECT_STATUSES:
                    location = resp.headers.get("Location")
                    if not location:
                        break

                    next_url = urljoin(current_url, location)

                    # Validate SSRF on next hop
                    safe_next, next_reason = await is_safe_url_async(next_url)
                    if not safe_next:
                        return current_url, hops, next_reason


                    if next_url in visited:
                        logger.warning("Redirect loop detected at %s", sanitize_url(next_url))
                        break

                    visited.add(next_url)
                    current_url = next_url
                    hops += 1
                else:
                    # Final destination reached
                    break

        return current_url, hops, None

    except httpx.TimeoutException:
        return current_url, hops, "Redirect expansion timed out"
    except Exception as e:
        logger.exception("Unexpected error expanding %s: %s", sanitize_url(current_url), e)
        return current_url, hops, "Redirect follow error"

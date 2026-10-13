"""
Bypass Engine coordinator.
Implements multi-level nested shortener resolution, SSRF protection,
concurrency limits (Semaphore(5)), per-user rate limiting (10/min), and 30s timeout.
"""

import time
import asyncio
import logging
from dataclasses import dataclass
from typing import Optional, Dict, List, Tuple
from collections import defaultdict

from .registry import find_site
from .generic_links_go import bypass_generic_links_go
from .expand import expand_redirects
from .ssrf import is_safe_url, sanitize_url

logger = logging.getLogger(__name__)

# Global semaphore: max 5 concurrent bypass tasks
GLOBAL_SEMAPHORE = asyncio.Semaphore(5)

# Per-user rate limiting: max 10 requests per 60 seconds
USER_RATE_LIMIT = 10
RATE_WINDOW_SECONDS = 60.0
_user_request_history: Dict[int, List[float]] = defaultdict(list)


@dataclass
class BypassResult:
    original_url: str
    final_url: str
    hops: int = 0
    method: str = "expand"
    success: bool = True
    error: Optional[str] = None


def check_rate_limit(user_id: int) -> Tuple[bool, Optional[str]]:
    """Check if user has exceeded the 10/min rate limit."""
    now = time.time()
    cutoff = now - RATE_WINDOW_SECONDS
    history = _user_request_history[user_id]
    
    # Filter out requests older than window
    _user_request_history[user_id] = [t for t in history if t > cutoff]
    
    if len(_user_request_history[user_id]) >= USER_RATE_LIMIT:
        return False, "Rate limit exceed ho gaya hai (max 10 link per minute). Kuch der baad try karein."
    
    _user_request_history[user_id].append(now)
    return True, None


async def _resolve_single_url(url: str, total_timeout: float = 30.0) -> BypassResult:
    """Internal resolver handling nested shorteners up to 3 levels."""
    safe, reason = is_safe_url(url)
    if not safe:
        return BypassResult(
            original_url=url,
            final_url=url,
            hops=0,
            method="ssrf_blocked",
            success=False,
            error=reason,
        )

    current_url = url
    total_hops = 0
    methods_used = []
    visited = {current_url}
    max_levels = 3

    for level in range(max_levels):
        logger.info(
            "Bypass level %d: resolving %s",
            level + 1,
            sanitize_url(current_url),
        )

        site = find_site(current_url)
        if site:
            if site.status in ("broken", "unsupported"):
                return BypassResult(
                    original_url=url,
                    final_url=current_url,
                    hops=total_hops,
                    method=f"registry:{site.name}",
                    success=False,
                    error="Cloudflare/captcha ki wajah se bypass nahi ho saka",
                )

            # Registry-based solver
            resolved_url, err = await bypass_generic_links_go(
                current_url, site=site, timeout_seconds=15.0
            )
            if err:
                # If specific error like captcha or handshake failure
                return BypassResult(
                    original_url=url,
                    final_url=current_url,
                    hops=total_hops,
                    method=f"registry:{site.name}",
                    success=False,
                    error=err,
                )
            if resolved_url:
                total_hops += 1
                methods_used.append(f"registry:{site.name}")
                if resolved_url in visited:
                    logger.warning("Bypass loop detected at %s", sanitize_url(resolved_url))
                    current_url = resolved_url
                    break
                visited.add(resolved_url)
                current_url = resolved_url
                continue

        # If not in registry or after registry step, expand redirect chains
        expanded_url, hops, expand_err = await expand_redirects(
            current_url, max_hops=10, timeout_seconds=15.0
        )
        total_hops += hops

        if expand_err:
            return BypassResult(
                original_url=url,
                final_url=current_url,
                hops=total_hops,
                method="expand",
                success=False,
                error=expand_err,
            )

        if expanded_url != current_url:
            methods_used.append("redirect_expand")
            if expanded_url in visited:
                logger.warning("Expand loop detected at %s", sanitize_url(expanded_url))
                current_url = expanded_url
                break
            visited.add(expanded_url)
            current_url = expanded_url

            # If expanded URL matches a known site in registry, loop back to solve it
            if find_site(current_url):
                continue
            else:
                break
        else:
            # No changes from expand and not in registry
            if level == 0 and not methods_used:
                # Was not a shortener or already final
                pass
            break

    final_method = " + ".join(methods_used) if methods_used else "direct/expand"
    is_success = current_url != url or total_hops > 0 or len(methods_used) > 0

    return BypassResult(
        original_url=url,
        final_url=current_url,
        hops=total_hops,
        method=final_method,
        success=True,
        error=None,
    )


async def bypass(url: str, user_id: Optional[int] = None, timeout: float = 30.0) -> BypassResult:
    """
    Main entry point for bypassing a link.
    Enforces per-user rate limit, global semaphore, and total timeout.
    """
    if user_id is not None:
        allowed, err_msg = check_rate_limit(user_id)
        if not allowed:
            return BypassResult(
                original_url=url,
                final_url=url,
                hops=0,
                method="rate_limit",
                success=False,
                error=err_msg,
            )

    async with GLOBAL_SEMAPHORE:
        try:
            return await asyncio.wait_for(_resolve_single_url(url, total_timeout=timeout), timeout=timeout)
        except asyncio.TimeoutError:
            return BypassResult(
                original_url=url,
                final_url=url,
                hops=0,
                method="timeout",
                success=False,
                error="Bypass timeout ho gaya (30 seconds limit)",
            )
        except Exception as e:
            logger.exception("Bypass engine unexpected error for %s: %s", sanitize_url(url), e)
            return BypassResult(
                original_url=url,
                final_url=url,
                hops=0,
                method="error",
                success=False,
                error="Bypass karte waqt koi takneeki error aaya",
            )

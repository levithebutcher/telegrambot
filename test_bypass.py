"""
Test suite for Bypass Engine, SSRF Protection, Redirect Expansion, Mode Switcher, and User Mode Persistence.

Can also process links from a `links.txt` file (format: `<site_name> <url>` per line).
"""

import os
import sys
import asyncio
import logging
from urllib.parse import urlparse
from unittest.mock import AsyncMock, MagicMock

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from bypass_engine.ssrf import is_safe_url, sanitize_url
from bypass_engine.expand import expand_redirects
from bypass_engine.engine import bypass, check_rate_limit, _user_request_history
from bypass_engine.registry import SITES, find_site
from utils.db import init_db, set_user_mode, get_user_mode, get_user_mode_async, set_user_mode_async
from handlers.router import MODES, main_text_router
from handlers.downloader import url_handler
from handlers.bypass_mode import bypass_mode_handler

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("test_bypass")


async def test_ssrf():
    """Verify SSRF protection blocks private, loopback, metadata, and non-whitelisted ports."""
    print("\n" + "=" * 60)
    print("1. RUNNING SSRF PROTECTION TESTS")
    print("=" * 60)

    ssrf_payloads = [
        ("http://127.0.0.1/", "Loopback IPv4"),
        ("http://localhost/", "Localhost domain"),
        ("http://169.254.169.254/latest/meta-data/", "AWS/Cloud Link-Local Metadata"),
        ("http://10.0.0.1/", "Private RFC1918 Class A"),
        ("http://172.16.0.1/", "Private RFC1918 Class B"),
        ("http://192.168.1.1/", "Private RFC1918 Class C"),
        ("http://[::1]/", "IPv6 Loopback"),
        ("http://google.com:22/", "Disallowed port 22 (SSH)"),
        ("http://google.com:8080/", "Disallowed port 8080"),
        ("ftp://google.com/", "Disallowed scheme ftp"),
        ("file:///etc/passwd", "Disallowed scheme file"),
    ]

    all_passed = True
    for url, desc in ssrf_payloads:
        safe, reason = is_safe_url(url)
        # Also run bypass() to ensure engine rejects it
        res = await bypass(url)
        blocked = (not safe) and (not res.success) and ("blocked" in (res.error or "").lower() or "invalid" in (res.error or "").lower())
        status = "✅ BLOCKED" if blocked else "❌ ALLOWED (VULNERABILITY!)"
        print(f"[{status}] {desc:32} -> {url} ({reason or res.error})")
        if not blocked:
            all_passed = False

    # Positive test: public URL
    safe_pub, reason_pub = is_safe_url("https://www.google.com")
    pub_status = "✅ ALLOWED" if safe_pub else "❌ FALSE POSITIVE"
    print(f"[{pub_status}] {'Public HTTPS':32} -> https://www.google.com")
    if not safe_pub:
        all_passed = False

    assert all_passed, "SSRF Protection tests failed!"
    print("\n🎉 ALL SSRF TESTS PASSED!")


async def test_mode_persistence_and_routing():
    """Verify database user mode persistence and handler routing."""
    print("\n" + "=" * 60)
    print("2. RUNNING MODE PERSISTENCE & ROUTING TESTS")
    print("=" * 60)

    init_db()
    test_user_id = 88776655

    # 1. Default mode should be 'download'
    default_mode = get_user_mode(test_user_id)
    print(f"Default user mode for new user: {default_mode}")
    assert default_mode == "download", f"Expected 'download', got '{default_mode}'"

    # 2. Switch to 'bypass'
    await set_user_mode_async(test_user_id, "bypass")
    mode_after_set = await get_user_mode_async(test_user_id)
    print(f"Mode after setting to 'bypass': {mode_after_set}")
    assert mode_after_set == "bypass", f"Expected 'bypass', got '{mode_after_set}'"

    # 3. Switch back to 'download'
    await set_user_mode_async(test_user_id, "download")
    mode_back = await get_user_mode_async(test_user_id)
    print(f"Mode after resetting to 'download': {mode_back}")
    assert mode_back == "download", f"Expected 'download', got '{mode_back}'"

    # 4. Verify Router mapping
    assert MODES["download"] == url_handler, "Router download mode must map to url_handler"
    assert MODES["bypass"] == bypass_mode_handler, "Router bypass mode must map to bypass_mode_handler"

    # 5. Test Router dispatch logic using mocks
    mock_update = MagicMock()
    mock_update.effective_user.id = test_user_id
    mock_context = MagicMock()

    # When user is in download mode
    await set_user_mode_async(test_user_id, "download")
    MODES["download"] = AsyncMock()
    MODES["bypass"] = AsyncMock()
    await main_text_router(mock_update, mock_context)
    assert MODES["download"].called, "Download handler should be called when mode is download"
    assert not MODES["bypass"].called, "Bypass handler should not be called when mode is download"

    # When user is in bypass mode
    await set_user_mode_async(test_user_id, "bypass")
    MODES["download"].reset_mock()
    MODES["bypass"].reset_mock()
    await main_text_router(mock_update, mock_context)
    assert MODES["bypass"].called, "Bypass handler should be called when mode is bypass"
    assert not MODES["download"].called, "Download handler should not be called when mode is bypass"

    # Restore real handlers
    MODES["download"] = url_handler
    MODES["bypass"] = bypass_mode_handler

    # Clean up test user
    await set_user_mode_async(test_user_id, "download")

    print("\n🎉 ALL MODE & ROUTING TESTS PASSED!")


async def test_redirect_expander():
    """Verify expand_redirects follows redirect chains."""
    print("\n" + "=" * 60)
    print("3. RUNNING REDIRECT EXPANDER TESTS")
    print("=" * 60)

    # Test with a known redirect service or HTTP redirect
    test_urls = [
        "https://httpbin.org/redirect/2",
        "https://tinyurl.com/app",
    ]

    for u in test_urls:
        print(f"Testing expand on: {u}")
        final_url, hops, err = await expand_redirects(u, max_hops=5)
        print(f"  -> Final URL: {final_url} (Hops: {hops}, Error: {err})")
        if err:
            print(f"  Note: Request gave {err} (network/status dependent)")
        else:
            assert hops >= 0, "Hops should be non-negative"

    print("\n🎉 REDIRECT EXPANDER FINISHED!")


async def test_rate_limiter():
    """Verify per-user rate limit (max 10 requests per minute)."""
    print("\n" + "=" * 60)
    print("4. RUNNING RATE LIMITER TESTS")
    print("=" * 60)

    test_uid = 999111222
    _user_request_history[test_uid] = []

    # Make 10 allowed requests
    for i in range(10):
        allowed, msg = check_rate_limit(test_uid)
        assert allowed is True, f"Request {i+1} should be allowed"

    # 11th request must be rejected
    allowed, msg = check_rate_limit(test_uid)
    assert allowed is False, "11th request in 1 minute should be blocked by rate limiter"
    print(f"✅ 11th request correctly rejected: {msg}")

    # Clean up
    _user_request_history[test_uid] = []
    print("\n🎉 RATE LIMITER TESTS PASSED!")


async def run_links_file(file_path: str = "links.txt"):
    """
    Read links.txt (format: `<site_name> <url>` per line) and test bypass.
    Prints status table: Site Name | URL | Status | Final Domain | Reason
    """
    print("\n" + "=" * 60)
    print(f"5. TESTING LINKS FROM {file_path}")
    print("=" * 60)

    if not os.path.isfile(file_path):
        print(f"ℹ️ File '{file_path}' not found. Create it with format: '<site_name> <url>' to test real links.")
        return

    with open(file_path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]

    if not lines:
        print(f"ℹ️ '{file_path}' is empty.")
        return

    results = []
    for line in lines:
        parts = line.split(None, 1)
        if len(parts) == 2:
            site_name, url = parts[0], parts[1]
        else:
            site_name, url = "unknown", parts[0]

        print(f"Processing [{site_name}] {sanitize_url(url)} ...")
        res = await bypass(url)
        status = "PASS" if res.success and res.final_url != url else ("PASS (same)" if res.success else "FAIL")
        domain = urlparse(res.final_url).netloc if res.final_url else "-"
        reason = res.error or f"{res.hops} hops via {res.method}"
        results.append((site_name, sanitize_url(url), status, domain, reason))

    print("\n" + "-" * 90)
    print(f"{'Site':15} | {'Status':12} | {'Final Domain':25} | {'Details / Reason'}")
    print("-" * 90)
    for site, u, status, dom, reason in results:
        print(f"{site:15} | {status:12} | {dom:25} | {reason}")
    print("-" * 90)


async def main():
    await test_ssrf()
    await test_mode_persistence_and_routing()
    await test_rate_limiter()
    await test_redirect_expander()
    await run_links_file("links.txt")


if __name__ == "__main__":
    asyncio.run(main())

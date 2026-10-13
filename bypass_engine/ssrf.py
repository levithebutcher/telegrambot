"""
SSRF Protection and URL Sanitization for Bypass Engine.
Blocks local, private, multicast, loopback IPs and non-standard ports.
Strips sensitive query parameters from logs.
"""

import ipaddress
import socket
import logging
from typing import Tuple
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

ALLOWED_PORTS = {80, 443}
ALLOWED_SCHEMES = {"http", "https"}


def sanitize_url(url: str) -> str:
    """Return URL with query parameters and fragment stripped for safe logging."""
    try:
        parts = urlsplit(url)
        return f"{parts.scheme}://{parts.netloc}{parts.path}"
    except Exception:
        return "<invalid-url>"


def is_safe_url(url: str) -> Tuple[bool, str]:
    """
    Validate that a URL is safe against SSRF attacks.
    Checks scheme, port, and resolves hostname to verify it's a public IP.
    """
    try:
        parsed = urlsplit(url)
    except Exception as e:
        return False, f"Malformed URL: {e}"

    if not parsed.scheme or parsed.scheme.lower() not in ALLOWED_SCHEMES:
        return False, f"Invalid scheme '{parsed.scheme}'. Only http and https allowed."

    port = parsed.port
    if port is not None and port not in ALLOWED_PORTS:
        return False, f"Invalid port '{port}'. Only ports 80 and 443 allowed."

    hostname = parsed.hostname
    if not hostname:
        return False, "Missing hostname in URL."

    hostname_lower = hostname.strip().lower()
    if hostname_lower == "localhost" or hostname_lower.endswith(".local") or hostname_lower.endswith(".internal"):
        return False, f"Blocked host '{hostname}' by SSRF protection."

    # Try resolving hostname to IPs
    try:
        addr_info = socket.getaddrinfo(hostname, None)
    except socket.gaierror as e:
        return False, f"DNS resolution failed for {hostname}: {e}"
    except Exception as e:
        return False, f"Hostname resolution error: {e}"

    if not addr_info:
        return False, f"Could not resolve host {hostname}."

    for family, _, _, _, sockaddr in addr_info:
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return False, f"Invalid IP address resolved: {ip_str}"

        # Block loopback, private, link-local, multicast, reserved, unspecified
        if (
            ip.is_loopback
            or ip.is_private
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False, f"Blocked target IP {ip_str} by SSRF protection."

    return True, ""

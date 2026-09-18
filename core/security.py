from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


def _is_private_ip(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


BLOCKED_HOSTS = {"localhost", "metadata.google.internal", "metadata"}


def is_safe_url(url: str) -> bool:
    """Reject URLs that could reach internal services (basic SSRF guard)."""
    try:
        p = urlparse(url)
    except Exception:
        return False
    if p.scheme not in ("http", "https"):
        return False
    host = (p.hostname or "").lower().strip("[]")
    if not host:
        return False
    if host in BLOCKED_HOSTS:
        return False
    if _is_private_ip(host):
        return False
    # Resolve textual hostname (single lookup, cheap)
    try:
        infos = socket.getaddrinfo(host, None)
        for info in infos:
            addr = info[4][0]
            if _is_private_ip(addr):
                return False
    except socket.gaierror:
        return True  # let yt-dlp handle unresolvable
    return True

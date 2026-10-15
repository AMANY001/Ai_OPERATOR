"""Constrained Playwright research adapter; it does not submit forms or purchase items."""
from __future__ import annotations
import ipaddress
import socket
from functools import lru_cache
from urllib.parse import urlparse


@lru_cache(maxsize=512)
def _host_resolves_publicly(host: str, port: int, scheme: str) -> bool:
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)}
    except OSError as exc:
        raise ValueError(f"Could not resolve public host: {host}") from exc
    if not addresses:
        raise ValueError("Hostname did not resolve to an address.")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise ValueError("Private, loopback, link-local, and non-public IP addresses are blocked.")
    return True


def validate_public_http_url(url: str) -> str:
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Only complete http:// or https:// URLs are allowed.")
    if parsed.username or parsed.password:
        raise ValueError("URLs containing embedded credentials are not allowed.")
    host = parsed.hostname.lower().rstrip(".")
    if host in {"localhost", "localhost.localdomain"} or host.endswith((".localhost", ".local", ".internal")):
        raise ValueError("Local and internal hostnames are blocked.")
    _host_resolves_publicly(host, parsed.port or (443 if parsed.scheme == "https" else 80), parsed.scheme)
    return url


def _install_route_guard(page) -> None:
    """Apply the same public-host restriction to subresources and redirects."""
    def guard(route):
        request_url = route.request.url
        scheme = urlparse(request_url).scheme.lower()
        if scheme in {"data", "blob", "about"}:
            route.continue_()
            return
        try:
            validate_public_http_url(request_url)
            route.continue_()
        except Exception:
            route.abort()
    page.route("**/*", guard)


def browser_open_impl(url: str, timeout_ms: int = 20000) -> dict:
    safe_url = validate_public_http_url(url)
    timeout_ms = max(3000, min(int(timeout_ms), 60000))
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _install_route_guard(page)
        try:
            response = page.goto(safe_url, wait_until="domcontentloaded", timeout=timeout_ms)
            title = page.title()
            final_url = page.url
            status = response.status if response else None
            return {"requested_url": safe_url, "final_url": final_url, "title": title,
                    "http_status": status, "verification_status": "page_loaded" if response and response.ok else "page_response_unconfirmed"}
        finally:
            browser.close()


def browser_extract_impl(url: str, max_chars: int = 12000, timeout_ms: int = 20000) -> dict:
    safe_url = validate_public_http_url(url)
    max_chars = max(500, min(int(max_chars), 20000))
    timeout_ms = max(3000, min(int(timeout_ms), 60000))
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _install_route_guard(page)
        try:
            response = page.goto(safe_url, wait_until="domcontentloaded", timeout=timeout_ms)
            title = page.title()
            text = page.locator("body").inner_text(timeout=5000)
            return {"url": page.url, "title": title, "http_status": response.status if response else None,
                    "text": text[:max_chars], "truncated": len(text) > max_chars,
                    "verification_status": "page_text_extracted" if response and response.ok else "page_response_unconfirmed"}
        finally:
            browser.close()

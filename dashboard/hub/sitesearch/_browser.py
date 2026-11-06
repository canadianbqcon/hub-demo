"""Headless system-Chrome page loader (Playwright sync API)."""

from urllib.parse import urlparse


def load(url: str, wait_for: str | None = None, capture_hosts: tuple = ()) -> tuple[str, list[str]]:
    """Return (page html, request URLs whose host matches capture_hosts)."""
    from playwright.sync_api import TimeoutError as PlaywrightTimeout, sync_playwright

    seen: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        try:
            page = browser.new_page()
            if capture_hosts:
                page.on("request", lambda r: seen.append(r.url)
                        if any(h in (urlparse(r.url).hostname or "") for h in capture_hosts) else None)
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            if wait_for:
                page.wait_for_selector(wait_for, timeout=15000)
            else:
                try:  # best effort: pages with live trackers (Amazon) never go idle; the caller parses what loaded
                    page.wait_for_load_state("networkidle", timeout=15000)
                except PlaywrightTimeout:
                    pass
            return page.content(), seen
        finally:
            browser.close()

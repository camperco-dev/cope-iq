"""
Headless Chromium browser automation for qPublic (qpublic.schneidercorp.com).

Cloudflare's CDN blocks plain HTTP clients on this domain. This module uses
Playwright (real Chromium) to navigate the site.

Discovery flow (two page loads):

  1. Homepage — all county options are pre-loaded in the initial HTML as
     div.dropdown-option elements inside state-group divs.  We parse the
     county's numeric AppID directly from the DOM (data-appid attribute)
     without any clicking.

  2. Application page — GET Application.aspx?AppID={appid}. The page embeds a
     JSON config object that explicitly names each page type.  We extract the
     "Property Search" URL (PageTypeID=2, PageID=N) from it.  Fallback: the
     nav link with text "Search" and PageTypeID=2.

Requires:
    pip install playwright
    playwright install chromium
"""

from __future__ import annotations

import json
import re

_QPUBLIC_HOME = "https://qpublic.schneidercorp.com"

# Full state names as they appear in the qPublic state-group data-state attribute.
_STATE_NAMES: dict[str, str] = {
    "AL": "Alabama",        "AK": "Alaska",         "AZ": "Arizona",
    "AR": "Arkansas",       "CA": "California",     "CO": "Colorado",
    "CT": "Connecticut",    "DE": "Delaware",        "FL": "Florida",
    "GA": "Georgia",        "HI": "Hawaii",          "ID": "Idaho",
    "IL": "Illinois",       "IN": "Indiana",         "IA": "Iowa",
    "KS": "Kansas",         "KY": "Kentucky",        "LA": "Louisiana",
    "ME": "Maine",          "MD": "Maryland",        "MA": "Massachusetts",
    "MI": "Michigan",       "MN": "Minnesota",       "MS": "Mississippi",
    "MO": "Missouri",       "MT": "Montana",         "NE": "Nebraska",
    "NV": "Nevada",         "NH": "New Hampshire",   "NJ": "New Jersey",
    "NM": "New Mexico",     "NY": "New York",        "NC": "North Carolina",
    "ND": "North Dakota",   "OH": "Ohio",            "OK": "Oklahoma",
    "OR": "Oregon",         "PA": "Pennsylvania",    "RI": "Rhode Island",
    "SC": "South Carolina", "SD": "South Dakota",    "TN": "Tennessee",
    "TX": "Texas",          "UT": "Utah",            "VT": "Vermont",
    "VA": "Virginia",       "WA": "Washington",      "WV": "West Virginia",
    "WI": "Wisconsin",      "WY": "Wyoming",
}


async def get_property_search_url(state: str, county: str) -> str | None:
    """
    Return the Property Search page URL for the given county on qPublic.

    The URL contains county-specific numeric parameters (AppID, LayerID, PageID)
    needed to reach the address search form.  Returns None if the county is not
    listed on qPublic or if any step fails.

    Args:
        state:  Two-letter state abbreviation (e.g. "CO").
        county: County name without "County" suffix (e.g. "Pitkin").
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("[qpublic_browser] playwright not installed — run: pip install playwright && playwright install chromium")
        return None

    state_full = _STATE_NAMES.get(state.upper())
    if not state_full:
        print(f"[qpublic_browser] unknown state abbreviation: {state!r}")
        return None

    print(f"[qpublic_browser] looking for {county.title()} County, {state_full}")

    ctx_opts = {
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "viewport": {"width": 1280, "height": 800},
    }

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            # ── Step 1: homepage — extract county AppID from pre-loaded DOM ──
            # All county options are present in the initial HTML as
            # div.dropdown-option elements inside div.state-group[data-state].
            # Each has a data-appid attribute with the numeric AppID.
            print(f"[qpublic_browser] GET {_QPUBLIC_HOME}")
            ctx1 = await browser.new_context(**ctx_opts)
            page1 = await ctx1.new_page()
            await page1.goto(_QPUBLIC_HOME, wait_until="networkidle", timeout=30_000)
            await page1.wait_for_timeout(1_000)

            state_group = page1.locator(f".state-group[data-state='{state_full}']")
            if await state_group.count() == 0:
                print(f"[qpublic_browser] state {state_full!r} not found on qPublic")
                return None

            options = await state_group.locator(".dropdown-option").all()
            app_id = await _match_county(options, county)
            await ctx1.close()

            if not app_id:
                available = [(await opt.text_content() or "").strip() for opt in options]
                print(f"[qpublic_browser] county {county!r} not found in {state_full}. "
                      f"Available: {available}")
                return None

            print(f"[qpublic_browser] matched county - AppID={app_id}")

            # ── Step 2: app page — extract Property Search URL ───────────────
            # IMPORTANT: use a fresh browser context here. The homepage SPA sets
            # cookies that cause the app page to do client-side rendering (32 KB,
            # no nav links) instead of server-side rendering (136 KB, full links).
            # A separate context has no prior cookies and gets the full SSR page.
            app_url = f"{_QPUBLIC_HOME}/Application.aspx?AppID={app_id}"
            print(f"[qpublic_browser] GET {app_url}")
            ctx2 = await browser.new_context(**ctx_opts)
            page2 = await ctx2.new_page()
            # domcontentloaded because the GIS map fires continuous network requests
            # and networkidle never triggers.
            await page2.goto(app_url, wait_until="domcontentloaded", timeout=30_000)
            try:
                await page2.wait_for_selector("a[href*='PageTypeID']", timeout=10_000)
            except Exception:
                pass  # proceed; extraction will log what it finds

            search_url = await _extract_property_search_url(page2)
            await ctx2.close()

            if search_url:
                print(f"[qpublic_browser] Property Search URL: {search_url}")
            else:
                print(f"[qpublic_browser] could not find Property Search link on app page")

            return search_url

        finally:
            await browser.close()


async def _match_county(options: list, county: str) -> str | None:
    """
    Find the data-appid for the option whose text best matches the county name.

    Matching rules (in priority order):
      1. Exact match on the county name word (case-insensitive).
      2. Option text starts with the county name.
      3. County name appears anywhere in the option text.
    """
    county_lower = county.lower().strip()
    candidates = []

    for opt in options:
        text = (await opt.text_content() or "").strip().lower()
        app_id = await opt.get_attribute("data-appid")
        if not app_id:
            continue
        # Score: 3 = word match, 2 = starts-with, 1 = contains
        if re.search(rf'\b{re.escape(county_lower)}\b', text):
            candidates.append((3, app_id))
        elif text.startswith(county_lower):
            candidates.append((2, app_id))
        elif county_lower in text:
            candidates.append((1, app_id))

    if not candidates:
        return None
    candidates.sort(key=lambda x: -x[0])
    return candidates[0][1]


async def _extract_property_search_url(page) -> str | None:
    """
    Extract the Property Search URL from the qPublic app page.

    Strategy 1 — embedded JSON config: the page inlines a JSON object containing
    an Apps array where each entry has Name/Url. "Property Search" is the entry
    we want.

    Strategy 2 — nav link with text "Search" and PageTypeID=2 (not "Advanced
    Search" or "Sales").
    """
    html = await page.content()

    # Strategy 1: parse embedded JSON for "Property Search"
    # The JSON contains entries like: {"Name":"Property Search","Url":"Application.aspx?..."}
    match = re.search(r'"Name"\s*:\s*"Property Search"\s*,\s*"[^"]+"\s*:\s*"[^"]*"\s*,\s*"Url"\s*:\s*"([^"]+)"', html)
    if not match:
        # Also try with Url before the Text field
        match = re.search(r'"Name"\s*:\s*"Property Search"[^}]*?"Url"\s*:\s*"([^"]+)"', html)
    if match:
        url = match.group(1).replace(r"\u0026", "&")
        return url if url.startswith("http") else f"{_QPUBLIC_HOME}/{url.lstrip('/')}"

    # Strategy 2: nav link — text exactly "Search" with PageTypeID=2
    links = await page.locator("a[href*='PageTypeID=2']").all()
    for lnk in links:
        text = (await lnk.text_content() or "").strip()
        href = await lnk.get_attribute("href") or ""
        # Accept "Search" but not "Advanced Search", "Sales Search", "Sales List" etc.
        if text.lower() == "search" and "PageTypeID=2" in href:
            return href if href.startswith("http") else f"{_QPUBLIC_HOME}{href}"

    # Strategy 3: first PageTypeID=2 link that isn't labelled Advanced/Sales
    for lnk in links:
        text = (await lnk.text_content() or "").strip().lower()
        href = await lnk.get_attribute("href") or ""
        if not any(skip in text for skip in ("advanced", "sales")):
            return href if href.startswith("http") else f"{_QPUBLIC_HOME}{href}"

    return None

"""
Headless Chromium browser automation for qPublic (qpublic.schneidercorp.com).

Cloudflare's CDN blocks plain HTTP clients on this domain. This module uses
Playwright (real Chromium) to navigate the site.

Discovery flow (two page loads, get_property_search_url):

  1. Homepage — all county options are pre-loaded in the initial HTML as
     div.dropdown-option elements inside state-group divs.  We parse the
     county's numeric AppID directly from the DOM (data-appid attribute)
     without any clicking.

  2. Application page — GET Application.aspx?AppID={appid}. The page embeds a
     JSON config object that explicitly names each page type.  We extract the
     "Property Search" URL (PageTypeID=2, PageID=N) from it.  Fallback: the
     nav link with text "Search" and PageTypeID=2.

Scraping flow (scrape_property_search):

  1. GET the county's property search form (search_page_url from platform_config).
  2. Fill the street address into #SearchControl1's text input and submit.
  3. If the POST redirects to a detail page (KeyValue= in URL), capture it.
     Otherwise parse the results table for the first parcel link and follow it.
  4. Return (pid, matched_address, html, parcel_url).

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

    _STEALTH_SCRIPT = "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"

    async with async_playwright() as pw:
        # Use headless=False to avoid Cloudflare bot fingerprinting (same as scraping flow).
        browser = await pw.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            # ── Step 1: homepage — extract county AppID from pre-loaded DOM ──
            # All county options are present in the initial HTML as
            # div.dropdown-option elements inside div.state-group[data-state].
            # Each has a data-appid attribute with the numeric AppID.
            print(f"[qpublic_browser] GET {_QPUBLIC_HOME}")
            ctx1 = await browser.new_context(**ctx_opts)
            await ctx1.add_init_script(_STEALTH_SCRIPT)
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
            await ctx2.add_init_script(_STEALTH_SCRIPT)
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


# ── Property scraping ─────────────────────────────────────────────────────────

async def scrape_property_search(
    search_page_url: str,
    query: str,
) -> tuple[str | None, str | None, str | None, str | None]:
    """
    Submit a property address search on a qPublic site using a Playwright browser.

    Bypasses Cloudflare's CDN block that rejects plain httpx clients.

    Args:
        search_page_url: The county's Property Search form URL (PageTypeID=2).
        query:           Street address to search (street portion only, e.g. "100 E Main St").

    Returns:
        (pid, matched_address, html, parcel_url) on success.
        Raises ValueError if the address is not found.
        Raises other exceptions on hard failures (timeout, navigation error).
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise RuntimeError("playwright not installed — run: pip install playwright && playwright install chromium")

    print(f"[qpublic_browser] scraping {query!r} via {search_page_url}")

    async with async_playwright() as pw:
        # Cloudflare's bot detection blocks headless Chromium's form POSTs via
        # interactive Turnstile. Running non-headless bypasses this fingerprinting.
        # On Linux servers, set the DISPLAY environment variable or start Xvfb first:
        #   export DISPLAY=:99 && Xvfb :99 -screen 0 1280x800x24 &
        browser = await pw.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            ctx = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
            )
            await ctx.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            )
            page = await ctx.new_page()

            # ── Step 1: load the search form ─────────────────────────────────
            await page.goto(search_page_url, wait_until="domcontentloaded", timeout=30_000)
            # Wait for the address search input (class is stable across deployments).
            try:
                await page.wait_for_selector("input.tt-upm-address-search", timeout=10_000)
            except Exception:
                pass

            # ── Dismiss Terms and Conditions modal (appears on first visit) ──
            try:
                modal = page.locator("div.modal.in, div[role='dialog'].in")
                if await modal.count() > 0:
                    for accept_sel in [
                        "button:has-text('Accept')",
                        "button:has-text('Agree')",
                        "button:has-text('OK')",
                        ".modal.in .btn-primary",
                        ".modal.in button",
                    ]:
                        btn = page.locator(accept_sel).first
                        if await btn.count() > 0:
                            await btn.click()
                            print(f"[qpublic_browser] dismissed T&C modal ({accept_sel})")
                            await page.wait_for_timeout(800)
                            break
            except Exception as e:
                print(f"[qpublic_browser] modal dismiss attempt: {e}")

            # ── Step 2: fill address and submit ──────────────────────────────
            # qPublic uses Bootstrap + Twitter Typeahead.  The address input has
            # class "tt-upm-address-search" and the submit button is an <a> tag
            # with searchintent="Address" — not a standard input[type=submit].
            for input_sel in [
                "input.tt-upm-address-search",
                "input[name*='txtAddress']",
                "input[type='text'][name*='ddress']",
            ]:
                inp = page.locator(input_sel).first
                if await inp.count() > 0:
                    await inp.click()
                    await inp.type(query, delay=50)
                    print(f"[qpublic_browser] filled address input ({input_sel})")
                    break

            await page.wait_for_timeout(500)

            submitted = False
            for btn_sel in [
                "a[searchintent='Address']",
                "a.tt-upm-address-search-btn",
                "a[id*='btnSearch'][id*='ctl03']",
                "input[type='submit']",
                "button[type='submit']",
            ]:
                btn = page.locator(btn_sel).first
                if await btn.count() > 0:
                    await btn.click()
                    submitted = True
                    print(f"[qpublic_browser] clicked submit ({btn_sel})")
                    break
            if not submitted:
                await page.keyboard.press("Enter")
                print("[qpublic_browser] submitted via Enter key")

            # Wait for the POST response to load (URL changes to PageTypeID=3 for
            # results or PageTypeID=4 for a single-result redirect).
            try:
                await page.wait_for_url(
                    lambda u: "PageTypeID=3" in u or "PageTypeID=4" in u or "KeyValue=" in u,
                    timeout=20_000,
                )
            except Exception:
                # Fallback: just wait a few seconds
                await page.wait_for_timeout(4_000)

            # ── Step 3: handle results or redirect ───────────────────────────
            result_url = str(page.url)
            print(f"[qpublic_browser] post-submit URL: {result_url}")

            # Single-result redirect lands directly on the detail page.
            if _is_detail_url(result_url):
                html = await page.content()
                pid = _parse_pid(result_url)
                print(f"[qpublic_browser] single-result redirect: pid={pid!r}")
                return pid, query, html, result_url

            # Results table (PageTypeID=3) — find and follow the first parcel link.
            # Each row has: [checkbox, icon-link, parcel-ID-link, alt-ID, owner, address, city, map]
            detail_sel = (
                "a[href*='KeyValue='], "
                "a[href*='PageType=Detail'], "
                "a[href*='PageTypeID=4']"
            )
            all_links = await page.locator(detail_sel).all()
            if not all_links:
                raise ValueError(f"Address not found in qPublic database: {query!r}")

            # Use the first result link (icon or parcel-ID link) to navigate.
            first_link = all_links[0]
            href = await first_link.get_attribute("href") or ""
            detail_url = href if href.startswith("http") else _QPUBLIC_HOME + href

            # Try to extract the matched address from the "Property Address" column
            # of the same table row (col index 5 in the standard qPublic layout).
            matched_address = query
            try:
                row = page.locator(f"tr:has(a[href='{href}'])").first
                if await row.count() > 0:
                    cells = await row.locator("td").all()
                    if len(cells) >= 6:
                        addr_text = (await cells[5].text_content() or "").strip()
                        if addr_text:
                            matched_address = addr_text
            except Exception:
                pass  # fallback to query

            print(f"[qpublic_browser] following result link: matched_address={matched_address!r}")

            # ── Step 4: GET the property detail page ─────────────────────────
            await page.goto(detail_url, wait_until="domcontentloaded", timeout=20_000)
            await page.wait_for_timeout(1_000)
            parcel_url = str(page.url)
            html = await page.content()
            pid = _parse_pid(parcel_url) or _parse_pid(detail_url)
            print(f"[qpublic_browser] detail page: pid={pid!r}  url={parcel_url}")
            return pid, matched_address, html, parcel_url

        finally:
            await browser.close()


def _is_detail_url(url: str) -> bool:
    """Return True if the URL looks like a property detail page."""
    return (
        "KeyValue=" in url
        or "PageType=Detail" in url
        or "PageTypeID=4" in url
    )


def _parse_pid(url: str) -> str | None:
    """Extract the KeyValue (parcel ID) from a qPublic URL."""
    m = re.search(r"KeyValue=([^&]+)", url)
    return m.group(1) if m else None

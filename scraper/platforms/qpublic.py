import re

import httpx
from lxml import html as lxhtml

from .base import PropertyPlatform

# UI asset filenames to skip when hunting for a property photo fallback.
_UI_ASSET_RE = re.compile(r'spacer|icon|button|logo|arrow', re.I)

# Common photo path patterns found on qPublic sites.
_PHOTO_PATH_RE = re.compile(r'/photos/|/images/|/parcel/', re.I)

# Photo file extensions used for fallback matching.
_PHOTO_EXT_RE = re.compile(r'\.(jpg|jpeg|png)($|\?)', re.I)


class QPublicPlatform(PropertyPlatform):
    """
    Scraper for Schneider Corp / qPublic assessor sites (qpublic.schneidercorp.com).

    The platform is an ASP.NET WebForms application that requires a GET → POST
    flow to obtain __VIEWSTATE tokens before submitting a search, followed by
    parsing a results page and fetching the property detail card.

    Required platform_config keys:
        app_id (str):    The App= parameter from the site URL.
                         E.g. "SCGovtBryanGA".

    Optional platform_config keys:
        layer_id (str):         Defaults to "Parcels".
        search_page_url (str):  Full URL to the county's address search form page.
                                Find it by visiting qpublic.schneidercorp.com, selecting
                                the county, and copying the "Property Search" link URL.
                                Example: https://qpublic.schneidercorp.com/Application.aspx
                                         ?AppID=1223&LayerID=37300&PageTypeID=2&PageID=14257
                                When provided, bypasses URL construction entirely and GETs
                                this URL directly for the search form. Strongly recommended —
                                the auto-constructed URL may land on the wrong page type.
    """

    # Base URL shared by all Schneider deployments.
    _HOST = "https://qpublic.schneidercorp.com"

    async def fetch(
        self,
        base_url: str,
        address: str,
        street: str | None,
        platform_config: dict,
        client: httpx.AsyncClient,
    ) -> tuple[str, str, str, str]:
        """
        Fetch a qPublic property card via a four-step flow:

        1. GET the search form to capture ASP.NET hidden tokens.
        2. POST the search form with the street address.
        3. Parse the results page for the first parcel detail link.
        4. GET the property detail page.

        Args:
            base_url:        Root URL of the municipality's qPublic site.
            address:         Full geocoded address (city/state included).
            street:          Street-only portion; preferred for the search query.
            platform_config: Must contain 'app_id'. May contain 'layer_id'.
            client:          Shared httpx.AsyncClient.

        Returns:
            (pid, matched_address, html, parcel_url)

        Raises:
            ValueError:      app_id missing, address not found, or no results parsed.
            httpx.HTTPError: Network or HTTP-level failure.
        """
        app_id = platform_config.get("app_id")
        if not app_id:
            raise ValueError("platform_config must include 'app_id' for qPublic sites")
        layer_id = platform_config.get("layer_id", "Parcels")

        # Use street-only query to reduce noise (city/state confuses the form field).
        query = street or address.split(",")[0].strip()
        print(f"[qpublic] app_id={app_id!r}  query={query!r}")

        # Prefer an explicit search page URL from platform_config — the auto-constructed
        # URL using only the string app_id can land on the GIS map view rather than the
        # address search form. The correct URL uses numeric IDs (AppID, LayerID, PageTypeID=2,
        # PageID) that are county-specific and must be copied from the live site.
        search_url = (
            platform_config.get("search_page_url")
            or f"{self._HOST}/Application.aspx?App={app_id}&PageTypeID=2"
        )

        # ── Step 1: GET the search form and capture ASP.NET tokens ──────────
        print(f"[qpublic] GET search form: {search_url}")
        r1 = await client.get(search_url, headers={"User-Agent": "Mozilla/5.0"})
        r1.raise_for_status()
        tokens = self._extract_viewstate(r1.text)
        print(f"[qpublic] captured {len(tokens)} ASP.NET token(s)")

        # ── Step 2: find the street address input name dynamically ──────────
        # The ASP.NET control path is long and varies across deployments.
        # We locate the input by finding the first text input inside #SearchControl1.
        tree = lxhtml.fromstring(r1.text)
        address_inputs = tree.cssselect("#SearchControl1 input[type='text']")
        if not address_inputs:
            raise ValueError(f"Could not find street address input on qPublic search page for app_id={app_id!r}")
        address_field_name = address_inputs[0].get("name")
        print(f"[qpublic] address field name: {address_field_name!r}")

        # ── Step 3: POST the search form ─────────────────────────────────────
        form_data = {**tokens, address_field_name: query}
        print(f"[qpublic] POST search form: {search_url}")
        r2 = await client.post(
            search_url,
            data=form_data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": search_url,
                "User-Agent": "Mozilla/5.0",
            },
        )
        r2.raise_for_status()

        # ── Step 4: parse results for first parcel detail link ───────────────
        # After a POST, qPublic may redirect directly to the detail page (single match)
        # or render a results table with multiple links.
        result_url = str(r2.url)
        if "PageType=Detail" in result_url:
            # Single-result redirect — already on the detail page.
            pid = self._parse_key_value(result_url)
            matched_address = query
            print(f"[qpublic] redirected to detail: pid={pid!r}")
            return pid, matched_address, r2.text, result_url

        results_tree = lxhtml.fromstring(r2.text)
        detail_links = results_tree.cssselect("a[href*='PageType=Detail']")
        if not detail_links:
            raise ValueError(f"Address not found in qPublic database: {query}")

        first_link = detail_links[0]
        href = first_link.get("href")
        # Resolve relative URLs.
        if href.startswith("/"):
            href = self._HOST + href
        elif not href.startswith("http"):
            href = self._HOST + "/" + href

        pid = self._parse_key_value(href)
        matched_address = (first_link.text_content() or query).strip()
        print(f"[qpublic] first result: pid={pid!r}  address={matched_address!r}")

        # ── Step 5: GET the property detail page ─────────────────────────────
        print(f"[qpublic] fetching detail page: {href}")
        r3 = await client.get(href, headers={"User-Agent": "Mozilla/5.0"})
        r3.raise_for_status()

        return pid, matched_address, r3.text, href

    # ── Media extraction ─────────────────────────────────────────────────────

    def extract_photo_url(self, html: str, base_url: str) -> str | None:
        """
        Extract the property photo URL from qPublic HTML.

        Strategy (in order):
        1. <img> whose src matches a common photo path (/photos/, /images/, /parcel/).
        2. <img> whose alt attribute contains "photo" (case-insensitive).
        3. Any <img> src ending in .jpg/.jpeg/.png that doesn't look like a UI asset.
        """
        tree = lxhtml.fromstring(html)

        for img in tree.iter("img"):
            src = img.get("src", "")
            alt = img.get("alt", "")

            if _PHOTO_PATH_RE.search(src):
                return self._resolve_url(src, base_url)

            if re.search(r'photo', alt, re.I):
                return self._resolve_url(src, base_url)

        # Fallback: any image URL that looks like a photo and not a UI asset.
        for img in tree.iter("img"):
            src = img.get("src", "")
            if _PHOTO_EXT_RE.search(src) and not _UI_ASSET_RE.search(src):
                return self._resolve_url(src, base_url)

        return None

    def extract_sketch_url(self, html: str, base_url: str) -> str | None:
        """
        Extract the building sketch URL from qPublic HTML.
        Searches <img> src and <a> href for 'sketch' or 'building' (case-insensitive).
        Returns None if not found — not all qPublic deployments include sketch images.
        """
        tree = lxhtml.fromstring(html)
        pattern = re.compile(r'sketch|building', re.I)

        for img in tree.iter("img"):
            src = img.get("src", "")
            if pattern.search(src):
                return self._resolve_url(src, base_url)

        for a in tree.iter("a"):
            href = a.get("href", "")
            if pattern.search(href):
                return self._resolve_url(href, base_url)

        return None

    def extraction_hints(self) -> str:
        """
        Claude prompt injection for qPublic-specific field naming conventions.
        These sites use different labels from the VGSI baseline.
        """
        return (
            "qPublic-specific field mapping notes:\n"
            "- 'Total Appraised Value' maps to assessed_value\n"
            "- 'Effective Year Built' is preferred over 'Year Built' if both are present\n"
            "- 'Heated Area' or 'Living Area SF' maps to living_area_sqft\n"
            "- 'Gross Area' or 'Total Area' maps to total_sqft\n"
            "- Sale information may appear under 'Transfer History' rather than a 'Sale' section\n"
        )

    # ── Private helpers ───────────────────────────────────────────────────────

    def _extract_viewstate(self, html: str) -> dict:
        """
        Parse ASP.NET hidden token fields from a page's HTML.

        Handles both the standard single __VIEWSTATE field and the chunked variant
        (__VIEWSTATE_0, __VIEWSTATE_1, …) used by some Schneider deployments.
        Concatenates chunks in numeric order before returning the merged value.
        """
        tree = lxhtml.fromstring(html)
        tokens: dict[str, str] = {}

        # Collect all hidden inputs whose name starts with __ (ASP.NET convention).
        for inp in tree.cssselect("input[type='hidden']"):
            name = inp.get("name", "")
            value = inp.get("value", "")
            if name.startswith("__"):
                tokens[name] = value

        # Detect and merge chunked __VIEWSTATE_N fields.
        chunk_keys = sorted(
            [k for k in tokens if re.match(r'__VIEWSTATE_\d+', k)],
            key=lambda k: int(k.rsplit("_", 1)[-1]),
        )
        if chunk_keys:
            merged = "".join(tokens.pop(k) for k in chunk_keys)
            tokens["__VIEWSTATE"] = merged
            print(f"[qpublic] merged {len(chunk_keys)} __VIEWSTATE chunks")

        return tokens

    @staticmethod
    def _parse_key_value(url: str) -> str:
        """Extract the KeyValue parameter from a qPublic detail page URL."""
        match = re.search(r'KeyValue=([^&]+)', url)
        return match.group(1) if match else url

    @staticmethod
    def _resolve_url(url: str, base_url: str) -> str:
        """Resolve a potentially relative URL against the site base URL."""
        if url.startswith("http"):
            return url
        if url.startswith("/"):
            # Strip path from base_url to get just the origin.
            from urllib.parse import urlparse
            parsed = urlparse(base_url)
            return f"{parsed.scheme}://{parsed.netloc}{url}"
        return base_url.rstrip("/") + "/" + url

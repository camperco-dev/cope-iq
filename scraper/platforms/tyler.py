import re
from urllib.parse import urljoin, urlparse, parse_qs

import httpx
from lxml import html as lxhtml

from .base import PropertyPlatform

# Marker present on every Tyler iasWorld Public Access search page.
_TYLER_MARKER = "frmMain"

# Datalet tabs that carry full COPE data, in order of priority.
_DATALET_MODES = ["profileall", "res_combined", "valuesall", "sales"]


class TylerPlatform(PropertyPlatform):
    """
    Scraper for Tyler Technologies iasWorld Public Access sites
    (*.tylertech.com, *.tylerhost.net, and custom domains).

    Used by hundreds of municipalities across the US (ME, OH, VA, LA, etc.).
    Classic ASP.NET WebForms application with server-side session state.

    Provides full COPE data: year built, style, stories, heat system, rooms,
    bedrooms, baths, living area, land/building/total values, and sale history.

    Scraping flow (5 HTTP requests):
        1. GET   search/commonsearch.aspx?mode=address
                 May redirect to Disclaimer.aspx — detected by presence of btAgree.
        2. POST  Disclaimer.aspx  btAgree=Agree  (only if disclaimer shown)
        3. POST  search/commonsearch.aspx?mode=address  — search by street number + name
        4a. 302 → single result → follow Location header directly to detail URL
        4b. 200 → results list → parse TR[onclick] rows, pick matching result
        5. GET   Datalets/Datalet.aspx?mode={mode}&sIndex=N&idx=M&LMparent=20
                 Fetched for each of: profileall, res_combined, valuesall, sales
                 Results concatenated into a single HTML for Claude extraction.

    Photo and sketch are session-relative; they are valid only while the httpx
    client session remains alive on the server.

    Required platform_config keys:  (none — base_url carries all state)
    """

    async def fetch(
        self,
        base_url: str,
        address: str,
        street: str | None,
        platform_config: dict,
        client: httpx.AsyncClient,
    ) -> tuple[str, str, str, str]:
        """
        Fetch a Tyler iasWorld property card.

        Raises ValueError if the address is not found.
        """
        base = base_url.rstrip("/")
        search_url = f"{base}/search/commonsearch.aspx?mode=address"
        headers = {"User-Agent": "Mozilla/5.0", "Referer": base}

        raw = street or address.split(",")[0].strip()
        house_num, street_name = _split_address(raw)
        print(f"[tyler] searching: num={house_num!r} street={street_name!r}")

        # Step 1: GET search page — may land on disclaimer.
        r1 = await client.get(search_url, headers=headers, follow_redirects=True)
        r1.raise_for_status()

        # Step 2: Accept disclaimer if present.
        if "btAgree" in r1.text:
            print("[tyler] accepting disclaimer")
            tree_d = lxhtml.fromstring(r1.text)
            disc_data = {
                inp.get("name"): inp.get("value", "")
                for inp in tree_d.cssselect("input")
                if inp.get("name")
            }
            disc_data["btAgree"] = "Agree"
            r1 = await client.post(
                str(r1.url), data=disc_data, headers=headers, follow_redirects=True
            )
            r1.raise_for_status()

        # Step 3: POST search — send only the first word of the street name.
        # Tyler uses "Starts With" server-side matching, so "Oak Street" would
        # not match "OAK ST" in the DB. Sending "Oak" returns all OAK* entries;
        # _pick_result() then does client-side matching.
        search_street = street_name.split()[0] if street_name else street_name
        tree_form = lxhtml.fromstring(r1.text)
        form_data = {
            inp.get("name"): inp.get("value", "")
            for inp in tree_form.cssselect("input[type=hidden]")
            if inp.get("name")
        }
        form_data.update({
            "inpNumber": house_num,
            "inpStreet": search_street,
            "hdAction": "Search",
        })

        r2 = await client.post(
            search_url, data=form_data, headers=headers, follow_redirects=False
        )
        if r2.status_code >= 400:
            r2.raise_for_status()

        # Step 4: Resolve to a single detail page.
        if r2.status_code == 302:
            # Single result — server redirects directly to the detail page.
            detail_path = r2.headers.get("location", "")
            detail_url = urljoin(base, detail_path)
        else:
            # Multiple results — parse the results table and pick the best match.
            detail_url = _pick_result(r2.text, house_num, street_name, base)

        print(f"[tyler] detail URL: {detail_url}")

        # Step 5: Fetch all datalet tabs and concatenate.
        sindex, idx = _parse_detail_params(detail_url)
        html_parts = []
        for mode in _DATALET_MODES:
            tab_url = (
                f"{base}/Datalets/Datalet.aspx"
                f"?mode={mode}&sIndex={sindex}&idx={idx}&LMparent=20"
            )
            r_tab = await client.get(tab_url, headers=headers, follow_redirects=True)
            if r_tab.status_code == 200:
                html_parts.append(r_tab.text)

        if not html_parts:
            raise ValueError(
                f"Tyler iasWorld returned no datalet content for {house_num} {street_name}"
            )

        combined_html = "\n\n<!-- DATALET BREAK -->\n\n".join(html_parts)

        # Extract parcel ID and matched address from the HTML.
        parcel_id, matched_address = _extract_parcel_info(html_parts[0], house_num, street_name)
        print(f"[tyler] match: parcel={parcel_id!r}  address={matched_address!r}")

        return parcel_id, matched_address, combined_html, detail_url

    def extract_photo_url(self, html: str, base_url: str) -> str | None:
        """
        Tyler serves photos via idoc2/photoview.aspx (session-relative).
        Returns the URL if the page does not show a PhotoError sentinel.
        """
        if "PhotoError" in html and "photoview.aspx" not in html.lower():
            return None
        if "photoview.aspx" in html.lower() or "idoc2" in html.lower():
            return None  # Don't expose session-relative URL — photos require session
        return None

    def extract_sketch_url(self, html: str, base_url: str) -> str | None:
        """
        Tyler serves sketches via datalets/sketch.aspx (session-relative).
        Not extractable without an active session context.
        """
        return None

    def extraction_hints(self) -> str:
        return (
            "This property card is from Tyler Technologies iasWorld Public Access "
            "(*.tylertech.com / *.tylerhost.net).\n"
            "The HTML contains multiple datalet sections separated by "
            "'<!-- DATALET BREAK -->' comments.\n"
            "Field mappings:\n"
            "  'Parcel ID'              -> parcel/account ID\n"
            "  'Map/Lot'                -> map-lot identifier (MBLU)\n"
            "  'Property Location'      -> property address\n"
            "  'Property Class'         -> occupancy/use type\n"
            "  'Land Area (acreage)'    -> lot size\n"
            "  'Owner'                  -> owner name\n"
            "  'Style'                  -> building style/construction type\n"
            "  'Year Built'             -> year built\n"
            "  'Stories'                -> number of stories\n"
            "  'Living Area'            -> gross living area (sq ft)\n"
            "  'Heat System'            -> heating system type\n"
            "  'Fuel Type'              -> fuel type\n"
            "  'Total Rooms'            -> room count\n"
            "  'Bedrooms'               -> bedroom count\n"
            "  'Full Baths'             -> full bath count\n"
            "  'Half Baths'             -> half bath count\n"
            "  'Basement'               -> basement type\n"
            "  'Current Land'           -> assessed land value\n"
            "  'Current Building'       -> assessed building value\n"
            "  'Current Assessed Total' -> total assessed value\n"
            "  Sale section: 'Deed Date', 'Sale Price', 'Grantor' -> sale history"
        )


# ── Helpers ────────────────────────────────────────────────────────────────────


def _split_address(raw: str) -> tuple[str, str]:
    """
    Split '123 Main Street' into ('123', 'Main Street').
    If the first token is not a number, treat the whole string as the street name.
    """
    parts = raw.strip().split(None, 1)
    if len(parts) == 2 and parts[0].isdigit():
        return parts[0], parts[1]
    return "", raw.strip()


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower().strip())


def _street_match(a: str, b: str) -> bool:
    """
    Return True if street names a and b refer to the same street.
    First word must match exactly; subsequent words use prefix matching
    to handle abbreviations (e.g. 'street' matches 'st').
    """
    a_words = _normalize(a).split()
    b_words = _normalize(b).split()
    if not a_words or not b_words:
        return False
    if a_words[0] != b_words[0]:
        return False
    if len(a_words) == 1 or len(b_words) == 1:
        return True
    shorter = min(len(a_words), len(b_words))
    for i in range(1, shorter):
        wa, wb = a_words[i], b_words[i]
        if not (wa.startswith(wb) or wb.startswith(wa)):
            return False
    return True


def _pick_result(html: str, house_num: str, street_name: str, base: str) -> str:
    """
    Parse the results list page and return the detail URL for the best match.

    Each result row has onclick='selectSearchRow(\"../Datalets/Datalet.aspx?...\")'.
    Columns: [PARID, Map/Lot, Address, Owner, ...].
    """
    tree = lxhtml.fromstring(html)
    rows = tree.cssselect("tr[onclick]")
    if not rows:
        raise ValueError(
            f"Address not found in Tyler iasWorld database: {house_num} {street_name}"
        )

    q_num = house_num.strip()
    q_street = _normalize(street_name)
    first_url = None
    first_addr = None

    for row in rows:
        onclick = row.get("onclick", "")
        m = re.search(r"selectSearchRow\(['\"]([^'\"]+)['\"]\)", onclick)
        if not m:
            continue
        relative_url = m.group(1)
        abs_url = urljoin(base + "/search/", relative_url)

        tds = row.cssselect("td")
        if len(tds) < 3:
            continue
        cell_address = tds[2].text_content().strip()

        # Split address cell into number + street (e.g. "229 OAK ST").
        addr_parts = cell_address.split(None, 1)
        cell_num = addr_parts[0] if addr_parts else ""
        cell_street = addr_parts[1] if len(addr_parts) > 1 else ""

        if first_url is None:
            first_url = abs_url
            first_addr = cell_address

        if cell_num == q_num and _street_match(q_street, cell_street):
            return abs_url

    if first_url:
        return first_url
    raise ValueError(
        f"Address not found in Tyler iasWorld database: {house_num} {street_name}"
    )


def _parse_detail_params(detail_url: str) -> tuple[str, str]:
    """
    Extract sIndex and idx from a detail URL like
    https://example.tylertech.com/Datalets/Datalet.aspx?sIndex=0&idx=1
    """
    qs = parse_qs(urlparse(detail_url).query)
    sindex = qs.get("sIndex", ["0"])[0]
    idx = qs.get("idx", ["1"])[0]
    return sindex, idx


def _extract_parcel_info(html: str, house_num: str, street_name: str) -> tuple[str, str]:
    """
    Extract parcel ID and matched address from a datalet HTML page.

    The datalet header contains a pattern like:
      "PARID: RE00000018229 OAK ST"
    which concatenates the PARID and address. The separate data table rows are:
      "Parcel ID | RE00000018"
      "Property Location | 229  OAK ST"
    which are the authoritative sources.
    """
    tree = lxhtml.fromstring(html)

    parcel_id = ""
    matched_address = ""

    for row in tree.cssselect("tr"):
        tds = row.cssselect("td")
        if len(tds) < 2:
            continue
        label = tds[0].text_content().strip()
        value = tds[1].text_content().strip()
        if label == "Parcel ID" and not parcel_id:
            parcel_id = value
        if label == "Property Location" and not matched_address:
            matched_address = re.sub(r"\s+", " ", value).strip()

    if not parcel_id:
        # Fallback: extract from PARID: pattern in raw HTML.
        m = re.search(r"PARID:\s*([A-Z0-9]+)", html)
        if m:
            parcel_id = m.group(1)

    if not matched_address:
        matched_address = f"{house_num} {street_name}".strip()

    return parcel_id, matched_address

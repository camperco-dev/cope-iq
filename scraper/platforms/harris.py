import re
from urllib.parse import urlparse

import httpx
from lxml import html as lxhtml

from .base import PropertyPlatform

# Marker present on every Harris RE Online search page.
_HARRIS_MARKER = "Harris RE Online Search"


class HarrisPlatform(PropertyPlatform):
    """
    Scraper for Harris Computer Systems RE Online sites
    (reonline.harriscomputer.com).

    Each municipality is identified by a ``clientid`` embedded in the
    ``search_url`` (e.g. ``?clientid=1007`` for Readfield ME).  Harris
    primarily serves rural New England municipalities.

    Provides full COPE data: year built, building style, rooms, bedrooms,
    baths, living area, land/building/taxable values, and sale history.

    Scraping flow (3 HTTP requests):
        1. GET   research.aspx?clientid={id}  — fetch search form + VIEWSTATE
        2. POST  research.aspx?clientid={id}  — search by street name
           Results page: REDetailList.aspx — table with columns:
           [View link | Account | Map/Lot | Name | Acres | Land | Building | ST No | Street]
        3. GET   DetailedView.aspx?id={account}  — full property card

    Required platform_config keys: (none — clientid is embedded in search_url)
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
        Fetch a Harris RE Online property card.

        Raises ValueError if the address is not found.
        """
        parsed = urlparse(base_url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        search_url = base_url  # full URL including clientid query param
        headers = {"User-Agent": "Mozilla/5.0", "Referer": base_url}

        raw = street or address.split(",")[0].strip()
        house_num, street_name = _split_address(raw)
        print(f"[harris] searching: num={house_num!r} street={street_name!r}")

        # Step 1: GET search form to collect VIEWSTATE and hidden fields.
        r1 = await client.get(search_url, headers=headers, follow_redirects=True)
        r1.raise_for_status()

        tree1 = lxhtml.fromstring(r1.text)
        form_data = _collect_form_fields(tree1)

        # Step 2: POST street search — use only the first word of the street
        # name.  Harris does a "Starts With" match on the street field, so
        # "Main Street" would miss "MAIN ST" entries if the DB uses abbreviated
        # types.  Sending "Main" returns all MAIN* streets; _pick_result() then
        # does client-side matching on the full table.
        search_street = street_name.split()[0] if street_name else street_name
        form_data["ctl00$ContentPlaceHolder1$txtDetailStreet"] = search_street
        form_data["ctl00$ContentPlaceHolder1$BtnDetailSearch"] = "Search"

        r2 = await client.post(
            search_url, data=form_data, headers=headers, follow_redirects=True
        )
        r2.raise_for_status()

        # Step 3: Pick the matching result from REDetailList.aspx.
        account_id, matched_address, detail_path = _pick_result(
            r2.text, house_num, street_name
        )
        detail_url = f"{base}/{detail_path}"
        print(f"[harris] match: account={account_id!r}  address={matched_address!r}")

        # Step 4: GET the full property card.
        r3 = await client.get(detail_url, headers=headers, follow_redirects=True)
        r3.raise_for_status()

        return account_id, matched_address, r3.text, detail_url

    def extract_photo_url(self, html: str, base_url: str) -> str | None:
        """Harris RE Online does not publish property photos."""
        return None

    def extract_sketch_url(self, html: str, base_url: str) -> str | None:
        """Harris RE Online does not publish building sketches."""
        return None

    def extraction_hints(self) -> str:
        return (
            "This property card is from Harris Computer Systems RE Online "
            "(reonline.harriscomputer.com).\n"
            "Field mappings:\n"
            "  'Map/Lot'         -> map-lot identifier (MBLU)\n"
            "  'Account'         -> parcel/account ID\n"
            "  'Location'        -> property address\n"
            "  'Owner'           -> owner name\n"
            "  'Land'            -> assessed land value\n"
            "  'Building'        -> assessed building value\n"
            "  'Taxable'         -> total taxable assessed value\n"
            "  Building section: 'Type' (first entry) -> building style\n"
            "  Building section: 'Year Built'         -> year built\n"
            "  Building section: 'Area'  (first entry) -> gross living area (sq ft)\n"
            "  Building section: 'Rooms'               -> room count\n"
            "  Building section: 'Bedrooms'            -> bedroom count\n"
            "  Building section: 'Full Baths'          -> full bath count\n"
            "  Building section: 'Half Baths'          -> half bath count\n"
            "  Sale section: 'Previous Owner', 'Sale Date', 'Sale Price' -> sale history\n"
            "Note: heating system and exterior material are not published on this platform."
        )


# ── Helpers ────────────────────────────────────────────────────────────────────


def _split_address(raw: str) -> tuple[str, str]:
    """
    Split '123 Main Street' into ('123', 'Main Street').
    If the first token is not a number, treat the whole string as street name.
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


def _collect_form_fields(tree: lxhtml.HtmlElement) -> dict:
    """
    Collect all non-checkbox form field values for a VIEWSTATE POST.
    Radio buttons: include the first value encountered per name (unchecked
    radios are not submitted in real browsers, but Harris doesn't enforce this).
    """
    form_data: dict = {}
    for inp in tree.cssselect("input"):
        name = inp.get("name")
        if not name:
            continue
        typ = inp.get("type", "text").lower()
        if typ == "checkbox":
            continue
        if typ == "radio":
            if inp.get("checked") is not None or name not in form_data:
                form_data[name] = inp.get("value", "")
        else:
            form_data[name] = inp.get("value", "")
    return form_data


def _pick_result(
    html: str, house_num: str, street_name: str
) -> tuple[str, str, str]:
    """
    Parse REDetailList.aspx and return (account_id, matched_address, detail_path).

    Results table columns (9 cells per data row):
      [0] View link  →  DetailedView.aspx?id=NNNN
      [1] Account
      [2] Map/Lot
      [3] Name (owner)
      [4] Acres
      [5] Land value
      [6] Building value
      [7] ST No  (house number)
      [8] Street (street name, e.g. "MAIN STREET")

    Data rows are identified by the presence of a DetailedView link in TD[0].
    """
    tree = lxhtml.fromstring(html)

    # Identify data rows by the DetailedView link in the first cell.
    data_rows = [
        row
        for row in tree.cssselect("table tr")
        if row.cssselect('td a[href*="DetailedView"]')
    ]

    if not data_rows:
        raise ValueError(
            f"Address not found in Harris RE Online database: "
            f"{house_num} {street_name}"
        )

    q_num = house_num.strip()
    q_street = _normalize(street_name)
    first_id = first_addr = first_path = None

    for row in data_rows:
        tds = row.cssselect("td")
        if len(tds) < 9:
            continue

        a = tds[0].cssselect("a")
        if not a:
            continue
        detail_path = a[0].get("href", "")  # e.g. "DetailedView.aspx?id=2130"

        account_id = tds[1].text_content().strip()
        cell_num = tds[7].text_content().strip()
        cell_street = tds[8].text_content().strip()

        if first_id is None:
            first_id = account_id
            first_addr = f"{cell_num} {cell_street}".strip()
            first_path = detail_path

        if cell_num == q_num and _street_match(q_street, cell_street):
            matched = f"{cell_num} {cell_street}".strip()
            return account_id, matched, detail_path

    if first_id:
        return first_id, first_addr, first_path
    raise ValueError(
        f"Address not found in Harris RE Online database: {house_num} {street_name}"
    )

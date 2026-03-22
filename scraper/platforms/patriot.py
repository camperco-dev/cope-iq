import re

import httpx
from lxml import html as lxhtml

from .base import PropertyPlatform

# Marker present on every Patriot Properties WebPro search page.
_PATRIOT_MARKER = "SearchStreetName"

# Pattern for the property photo and sketch — session-relative ASP pages.
_PHOTO_RE = re.compile(r'showimage\.asp', re.I)
_SKETCH_RE = re.compile(r'showsketch\.asp', re.I)


class PatriotPlatform(PropertyPlatform):
    """
    Scraper for Patriot Properties WebPro assessor sites
    (*.patriotproperties.com).

    Used by hundreds of New England municipalities (ME, NH, MA, RI, CT).
    Classic ASP frameset application with session-based state.

    Provides full COPE data: year built, exterior, roof cover, rooms,
    bedrooms, baths, land area, land/building/total values, and sale history.

    Scraping flow (3 HTTP requests, session cookies required):
        1. POST  SearchResults.asp  — search by street number + name
        2. GET   Summary.asp?AccountNumber={id}  — load parcel into session
        3. GET   summary-bottom.asp  — retrieve the property card HTML

    Photo (showimage.asp) and sketch (showsketch.asp) are session-relative
    URLs returned by the third request. They are valid only while the httpx
    client's session cookie remains alive on the server side.

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
        Fetch a Patriot Properties WebPro property card.

        Raises ValueError if the address is not found.
        """
        base = base_url.rstrip("/")
        headers = {"User-Agent": "Mozilla/5.0", "Referer": f"{base}/default.asp"}

        # Split address into house number and street name.
        raw = street or address.split(",")[0].strip()
        house_num, street_name = _split_address(raw)
        print(f"[patriot] searching: num={house_num!r} street={street_name!r}")

        # Use only the first word of the street name for the server-side search.
        # Patriot uses "Starts With" server-side, so sending "Oak Street" would
        # fail to match the DB value "OAK ST" (different length). Sending "Oak"
        # returns all OAK* streets; _parse_results then does client-side matching.
        search_street = street_name.split()[0] if street_name else street_name

        # Step 1: POST search.
        search_url = f"{base}/SearchResults.asp"
        data = {
            "SearchStreetNum": house_num,
            "SearchStreetName": search_street,
            "SearchStreetNameCompare": "Starts With",
        }
        r1 = await client.post(search_url, data=data, headers=headers,
                               follow_redirects=True)
        r1.raise_for_status()

        account_id, matched_address = _parse_results(r1.text, house_num, street_name)
        print(f"[patriot] match: account={account_id!r}  address={matched_address!r}")

        # Step 2: GET Summary.asp to load parcel into server-side session.
        summary_url = f"{base}/Summary.asp?AccountNumber={account_id}"
        r2 = await client.get(summary_url, headers=headers, follow_redirects=True)
        r2.raise_for_status()

        # Step 3: GET summary-bottom.asp for the property card.
        card_url = f"{base}/summary-bottom.asp"
        r3 = await client.get(card_url, headers={"User-Agent": "Mozilla/5.0",
                                                  "Referer": summary_url},
                              follow_redirects=True)
        r3.raise_for_status()

        if "session has timed out" in r3.text.lower():
            raise ValueError(
                "Patriot Properties session expired before card could be fetched"
            )

        return account_id, matched_address, r3.text, summary_url

    def extract_photo_url(self, html: str, base_url: str) -> str | None:
        """
        Return the session-relative photo URL if an actual image was served.

        Patriot Properties uses ``showimage.asp`` as the photo URL. The page
        also falls back to ``images/nopic.jpg`` when no photo exists —
        detect that sentinel and return None.
        """
        # Skip the no-photo sentinel.
        if "nopic.jpg" in html and _PHOTO_RE.search(html) is None:
            return None
        if _PHOTO_RE.search(html):
            return base_url.rstrip("/") + "/showimage.asp"
        return None

    def extract_sketch_url(self, html: str, base_url: str) -> str | None:
        """
        Return the session-relative sketch URL if an actual sketch was served.

        Falls back to ``images/nosketch.jpg`` when no sketch exists.
        """
        if "nosketch.jpg" in html and _SKETCH_RE.search(html) is None:
            return None
        if _SKETCH_RE.search(html):
            return base_url.rstrip("/") + "/showsketch.asp"
        return None

    def extraction_hints(self) -> str:
        return (
            "This property card is from Patriot Properties WebPro "
            "(*.patriotproperties.com).\n"
            "The Narrative Description section at the bottom is the richest source "
            "of construction data — extract year built, exterior material, roof cover, "
            "residential/commercial units, rooms, bedrooms, and baths from it.\n"
            "Field mappings:\n"
            "  'Location'              → property address\n"
            "  'Property Account Number' → parcel/account ID\n"
            "  'Parcel ID'             → map-lot identifier\n"
            "  'Owner'                 → owner name\n"
            "  'Sale Date' / 'Sale Price' / 'Grantor(Seller)' → sale history\n"
            "  'Building Value' / 'Land Value' / 'Total Value' → assessment\n"
            "  'Land Area'             → lot size\n"
            "  Narrative: 'classified as X' → occupancy/land use code\n"
            "  Narrative: 'style building' → construction/building style\n"
            "  Narrative: 'built about YYYY' → year built\n"
            "  Narrative: 'having X exterior' → exterior material\n"
            "  Narrative: 'Y roof cover' → roof cover type\n"
            "  Narrative: totals for rooms/bedrooms/baths → unit counts"
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


def _parse_results(html: str, house_num: str, street_name: str) -> tuple[str, str]:
    """
    Parse SearchResults.asp HTML and return (account_id, matched_address).

    Matches the first result row where the house number and street name align.
    Falls back to the first result if no exact match is found.
    """
    tree = lxhtml.fromstring(html)

    # Each result row has structure: [ParcelID link | StreetNum + StreetName | Owner | ...]
    # The parcel link is: <a href="Summary.asp?AccountNumber=NNN">ParcelID</a>
    account_links = tree.cssselect('a[href*="AccountNumber="]')
    if not account_links:
        raise ValueError(
            f"Address not found in Patriot Properties database: "
            f"{house_num} {street_name}"
        )

    q_num = house_num.strip()
    q_street = _normalize(street_name)
    first_id = None
    first_addr = None

    for link in account_links:
        href = link.get("href", "")
        m = re.search(r"AccountNumber=(\d+)", href, re.I)
        if not m:
            continue
        acct_id = m.group(1)

        # The address cell is the next <td> sibling after the parcel link's <td>.
        td = link.getparent()
        next_td = td.getnext()
        if next_td is None:
            # Fallback: grab all text in parent row.
            row_text = " ".join(td.getparent().text_content().split())
            cell_text = row_text
        else:
            cell_text = next_td.text_content()

        # cell_text is like "1  OAK ST" — split into number and street.
        cell_parts = cell_text.strip().split(None, 1)
        cell_num = cell_parts[0].strip() if cell_parts else ""
        cell_street = cell_parts[1].strip() if len(cell_parts) > 1 else ""

        if first_id is None:
            first_id = acct_id
            first_addr = f"{cell_num} {cell_street}".strip()

        # Match: house numbers must agree; street names must share a common prefix
        # in either direction (handles "Oak Street" vs "OAK ST").
        if cell_num == q_num and _street_match(q_street, cell_street):
            matched = f"{cell_num} {cell_street}".strip()
            return acct_id, matched

    if first_id:
        return first_id, first_addr
    raise ValueError(
        f"Address not found in Patriot Properties database: {house_num} {street_name}"
    )


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower().strip())


def _street_match(a: str, b: str) -> bool:
    """
    Return True if street names ``a`` and ``b`` refer to the same street.

    Handles mismatches between full type words and abbreviations
    (e.g. "Oak Street" vs "OAK ST") by:
      1. Requiring the first word (base name) to match exactly.
      2. For subsequent words, accepting one as a prefix of the other
         (so "street" matches "st", "road" matches "rd", etc.).
    """
    a_words = _normalize(a).split()
    b_words = _normalize(b).split()
    if not a_words or not b_words:
        return False
    # First word (base street name) must always match exactly.
    if a_words[0] != b_words[0]:
        return False
    # If only one word in either, that's enough.
    if len(a_words) == 1 or len(b_words) == 1:
        return True
    # For remaining words, use prefix matching to handle abbreviations.
    shorter = min(len(a_words), len(b_words))
    for i in range(1, shorter):
        wa, wb = a_words[i], b_words[i]
        if not (wa.startswith(wb) or wb.startswith(wa)):
            return False
    return True

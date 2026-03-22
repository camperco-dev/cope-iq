import json
import re

import httpx

from .base import PropertyPlatform


class OdonnellPlatform(PropertyPlatform):
    """
    Scraper for John E. O'Donnell & Associates CAMA sites (jeodonnell.com/cama/).

    These are WordPress sites running a custom jeo-cama plugin. The full parcel
    dataset is embedded as JSON in a ``<script id="jeo-cama-js-extra">`` tag on
    each municipality page. Individual parcels are matched by street address.

    Data availability note: This platform exposes ownership and assessed value
    data only. Construction details (year built, square footage, construction
    type, stories, roof, foundation, heating) are not published online — those
    COPE fields will be null for all O'Donnell properties.

    Required platform_config keys:
        slug (str): URL path slug for the municipality, e.g. ``"turner"``.
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
        Fetch an O'Donnell CAMA property card.

        1. GET the municipality page (base_url).
        2. Extract ``script_vars.dataSet`` from the inline jeo-cama script block.
        3. Match by ``StreetNumber + StreetName`` against the input address.
        4. Return a synthetic HTML card for Claude extraction.
        """
        page_url = base_url.rstrip("/") + "/"
        print(f"[odonnell] fetching dataset: {page_url}")

        r = await client.get(
            page_url,
            headers={"User-Agent": "Mozilla/5.0"},
            follow_redirects=True,
        )
        r.raise_for_status()

        dataset = _extract_dataset(r.text, page_url)
        print(f"[odonnell] dataset loaded: {len(dataset)} records")

        query = street or address.split(",")[0].strip()
        record = _match_record(dataset, query)
        if record is None:
            raise ValueError(f"Address not found in O'Donnell CAMA database: {query!r}")

        pid = record["Key"]
        matched_address = (
            f"{record.get('StreetNumber', '')} {record.get('StreetName', '')}".strip()
        )
        print(f"[odonnell] matched: pid={pid!r}  address={matched_address!r}")

        html = _build_card_html(record, page_url)
        parcel_url = f"{page_url}{pid}/"

        return pid, matched_address, html, parcel_url

    def extract_photo_url(self, html: str, base_url: str) -> str | None:
        return None  # O'Donnell does not publish property photos online.

    def extract_sketch_url(self, html: str, base_url: str) -> str | None:
        return None  # O'Donnell does not publish building sketches online.

    def extraction_hints(self) -> str:
        return (
            "This property card is from John E. O'Donnell & Associates "
            "(jeodonnell.com/cama/). Only ownership and assessment value data is "
            "available online; construction details are not published.\n"
            "Field mappings:\n"
            "  Key          → parcel ID (Map-Lot format, e.g. '047-014')\n"
            "  OwnerName1   → owner name\n"
            "  StreetNumber + StreetName → property address\n"
            "  LandValue    → assessed land value\n"
            "  BuildingValue→ assessed building value\n"
            "  BoughtFor    → last sale price\n"
            "  OwnerSince   → last sale date\n"
            "Set all construction fields (year_built, square_footage, construction_type, "
            "stories, roof_cover, foundation, heating) to null — they are not available."
        )


# ── Helpers ────────────────────────────────────────────────────────────────────


def _extract_dataset(html: str, page_url: str) -> list[dict]:
    """Pull the dataSet array from the jeo-cama-js-extra inline script block."""
    # Isolate the script block by id.
    block_match = re.search(
        r'id=["\']jeo-cama-js-extra["\'][^>]*>(.*?)</script>',
        html,
        re.DOTALL | re.IGNORECASE,
    )
    if not block_match:
        raise ValueError(
            f"O'Donnell jeo-cama-js-extra script block not found on {page_url}"
        )

    script_text = block_match.group(1)

    # Extract the full JSON object assigned to script_vars.
    # Greedy match from first { to last } captures the full object.
    json_match = re.search(r"var\s+script_vars\s*=\s*(\{.+\})", script_text, re.DOTALL)
    if not json_match:
        raise ValueError(
            f"O'Donnell script_vars assignment not found on {page_url}"
        )

    try:
        script_vars = json.loads(json_match.group(1))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to parse O'Donnell script_vars JSON: {exc}") from exc

    dataset = script_vars.get("dataSet") or []
    if not dataset:
        raise ValueError(f"O'Donnell dataSet is empty on {page_url}")
    return dataset


def _normalize(s: str) -> str:
    """Lowercase, collapse whitespace, strip punctuation for address comparison."""
    s = s.lower().strip()
    s = re.sub(r"[.,#]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s


def _match_record(dataset: list[dict], query: str) -> dict | None:
    """
    Find the dataset record whose address matches ``query``.

    Matching strategy:
    1. Exact normalised match of ``StreetNumber + StreetName``.
    2. Partial fallback: house number exact + street name prefix (first 8 chars).
    Private records (PrivateData == "1") are skipped.
    """
    q = _normalize(query)
    q_parts = q.split()
    q_num = q_parts[0] if q_parts else ""
    q_street = " ".join(q_parts[1:])

    partial_hit = None

    for rec in dataset:
        if rec.get("PrivateData") == "1":
            continue
        candidate = _normalize(
            f"{rec.get('StreetNumber', '')} {rec.get('StreetName', '')}".strip()
        )
        if candidate == q:
            return rec  # exact match — done

        # Accumulate partial match (house number + street prefix)
        if partial_hit is None and q_num and q_street:
            rec_num = rec.get("StreetNumber", "").strip()
            rec_street = _normalize(rec.get("StreetName", ""))
            if rec_num == q_num and rec_street.startswith(q_street[:8]):
                partial_hit = rec

    return partial_hit


def _build_card_html(record: dict, page_url: str) -> str:
    """Render a record dict as a minimal HTML table for Claude extraction."""
    field_labels = [
        ("Key",           "Parcel ID (Map-Lot)"),
        ("OwnerName1",    "Owner Name"),
        ("StreetNumber",  "Street Number"),
        ("StreetName",    "Street Name"),
        ("LandValue",     "Assessed Land Value"),
        ("BuildingValue", "Assessed Building Value"),
        ("BoughtFor",     "Last Sale Price"),
        ("OwnerSince",    "Last Sale Date"),
    ]
    rows = "\n".join(
        f"  <tr><th>{label}</th><td>{record.get(key, '')}</td></tr>"
        for key, label in field_labels
        if record.get(key)
    )
    return (
        "<html><body>\n"
        "<h1>O'Donnell &amp; Associates Property Assessment</h1>\n"
        f"<p>Source: {page_url}</p>\n"
        "<table>\n"
        f"{rows}\n"
        "</table>\n"
        "<p>Construction details (year built, square footage, construction type, "
        "stories, roof, foundation, heating) are not available on this platform.</p>\n"
        "</body></html>"
    )

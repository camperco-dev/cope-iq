import re
from datetime import datetime, timezone

import httpx

from scraper.platforms.base import PropertyPlatform


class ArcGISPlatform(PropertyPlatform):
    """
    Scraper for Esri ArcGIS MapServer / FeatureServer parcel layers.

    Many county GIS departments expose their parcel data through public
    ArcGIS REST services (e.g. Pitkin County, CO at maps.pitkincounty.com).
    The endpoints return structured JSON attributes, so no HTML parsing is
    needed — we render the attributes as a minimal HTML card for Claude.

    Single HTTP request — no browser automation. The underlying ArcGIS
    services are typically Cloudflare-free even when the corresponding
    qPublic / partner UI is gated; we still construct a qPublic deeplink
    (when ``viewer_url_template`` is set) so a real browser can follow it
    to the assessor's full card.

    Property photos and building sketches are not exposed on parcel
    feature layers, so ``extract_photo_url`` / ``extract_sketch_url``
    always return None for ArcGIS-backed municipalities.

    Required ``platform_config`` keys: none — ``search_url`` is the full
    layer URL (e.g. ``.../MapServer/9``).

    Optional ``platform_config`` keys:
        city (str): Value for the ``CITY`` filter; useful when a single
                    county's parcel layer covers multiple municipalities
                    and we only want to match within one. Defaults to no
                    city filter.
        viewer_url_template (str): ``str.format()`` template with an
                    ``{account}`` placeholder (substituted with the
                    ``ACCOUNTNUMBER`` attribute) for building the
                    user-facing parcel_url. Falls back to the raw /query
                    URL when omitted.
        house_number_field (str): ArcGIS field name carrying the parsed
                    house number. Defaults to ``SITUS_ADDRESS_HOUSENUMBER``
                    (Pitkin's convention).
        address_field (str): ArcGIS field name carrying the full street
                    address. Defaults to ``SITUS_ADDRESS``.
        city_field (str): ArcGIS field name carrying the situs city.
                    Defaults to ``CITY``.
    """

    _DIRECTIONALS = {"n", "s", "e", "w", "north", "south", "east", "west"}

    async def fetch(
        self,
        base_url: str,
        address: str,
        street: str | None,
        platform_config: dict,
        client: httpx.AsyncClient,
    ) -> tuple[str, str, str, str]:
        layer_url = base_url.rstrip("/")
        query_text = (street or address.split(",")[0]).strip()

        house_no, street_word = _parse_house_and_street(query_text)

        house_field = platform_config.get("house_number_field", "SITUS_ADDRESS_HOUSENUMBER")
        addr_field = platform_config.get("address_field", "SITUS_ADDRESS")
        city_field = platform_config.get("city_field", "CITY")
        city = platform_config.get("city")

        where_parts = [
            f"{house_field}='{_sql_escape(house_no)}'",
            f"UPPER({addr_field}) LIKE '%{_sql_escape(street_word.upper())}%'",
        ]
        if city:
            where_parts.append(f"UPPER({city_field})='{_sql_escape(city.upper())}'")
        where = " AND ".join(where_parts)

        query_url = f"{layer_url}/query"
        params = {
            "where": where,
            "outFields": "*",
            "returnGeometry": "false",
            "f": "json",
            "resultRecordCount": 5,
        }

        print(f"[arcgis] query: {query_url}")
        print(f"[arcgis] where: {where}")

        r = await client.get(query_url, params=params, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        data = r.json()

        features = data.get("features", [])
        print(f"[arcgis] returned {len(features)} feature(s)")
        if not features:
            raise ValueError(f"Address not found in ArcGIS parcel database: {query_text}")

        attrs = features[0].get("attributes", {})
        _convert_epoch_dates(attrs)

        pid = str(attrs.get("PARCEL") or attrs.get("ACCOUNTNUMBER") or "")
        matched = str(attrs.get(addr_field) or attrs.get("SITUS_ADDRESS") or query_text)
        print(f"[arcgis] matched: pid={pid!r}  address={matched!r}")

        template = platform_config.get("viewer_url_template")
        if template:
            parcel_url = template.format(account=attrs.get("ACCOUNTNUMBER", ""))
        else:
            parcel_url = f"{query_url}?where={where}&outFields=*&f=json"

        html = _build_card_html(attrs, parcel_url)
        return pid, matched, html, parcel_url

    def extract_photo_url(self, html: str, base_url: str) -> str | None:
        return None

    def extract_sketch_url(self, html: str, base_url: str) -> str | None:
        return None

    def extraction_hints(self) -> str:
        return (
            "This property card was rendered from an Esri ArcGIS parcel feature layer "
            "(structured JSON, not a CAMA HTML form). Field naming follows the Pitkin "
            "County, CO schema; other counties may use the same names.\n"
            "Field mappings:\n"
            "  PARCEL / PIN / ACCOUNTNUMBER → parcel_id\n"
            "  SITUS_ADDRESS                → matched address\n"
            "  OWNER_NAME, OWNER_ADDRESS1..ZIP → owner.name / owner.address\n"
            "  SALE_PRICE / SALE_DATE       → sale.price / sale.date (already ISO)\n"
            "  LAND_ACTUAL                  → valuation.land_value (use ACTUAL not ASSESSED)\n"
            "  IMPROVEMENTS_ACTUAL          → valuation.building_value\n"
            "  FINAL_ACTUAL_VALUE           → valuation.assessed_value\n"
            "  ACTUAL_YR_BUILT              → construction.year_built\n"
            "  ACTUAL_AREA / AREA_SQFT      → construction.total_sqft\n"
            "  LIVE_AREA / HEATED_AREA      → construction.living_area_sqft\n"
            "  STORIES                      → construction.stories\n"
            "  BEDROOMS                     → occupancy.num_bedrooms\n"
            "  BATHS (decimal, e.g. 5.5)    → split into num_bathrooms (5) + num_half_baths (1)\n"
            "  ACCOUNT_TYPE / MODEL_TYPE    → occupancy.occupancy_class\n"
            "  AbstractCode1 / AbstractDesc1 → occupancy.use_code / use_description\n"
            "  Mapped_Acres / Platted_Acres → exposure.lot_size_acres\n"
            "  NEIGHBORHOOD                 → exposure.neighborhood\n"
            "Construction sub-fields not in this schema (exterior_wall, roof_cover, "
            "heat_fuel, foundation, etc.) and the entire protection block are not "
            "available — leave them null."
        )


# ── Helpers ────────────────────────────────────────────────────────────────────


def _sql_escape(value: str) -> str:
    """Escape single quotes for an ArcGIS REST where-clause string literal."""
    return value.replace("'", "''")


def _parse_house_and_street(query: str) -> tuple[str, str]:
    """
    Extract (house_number, first_distinctive_street_word) from a street query.

    Skips leading directionals (N/S/E/W) so e.g. ``"1008 East Hopkins Ave"``
    yields ``("1008", "Hopkins")``. Raises ValueError if the query has no
    house number or no street name beyond directionals.
    """
    m = re.match(r"^\s*(\d+)\s+(.+)$", query)
    if not m:
        raise ValueError(f"Could not parse house number from address: {query!r}")
    house_no = m.group(1)
    rest = m.group(2)

    words = re.findall(r"[A-Za-z]+", rest)
    street_word = next(
        (w for w in words if w.lower() not in ArcGISPlatform._DIRECTIONALS),
        None,
    )
    if not street_word:
        raise ValueError(f"Could not identify street name in: {rest!r}")
    return house_no, street_word


def _convert_epoch_dates(attrs: dict) -> None:
    """In-place: convert ArcGIS ms-since-epoch date fields to ISO date strings."""
    for k, v in list(attrs.items()):
        if isinstance(v, (int, float)) and v > 1_000_000_000_000 and (
            "DATE" in k.upper() or k.endswith("date")
        ):
            try:
                attrs[k] = datetime.fromtimestamp(v / 1000, tz=timezone.utc).date().isoformat()
            except (ValueError, OSError):
                pass


def _build_card_html(attrs: dict, parcel_url: str) -> str:
    """Render ArcGIS feature attributes as a minimal HTML card for Claude."""
    skip = {
        "OBJECTID", "SHAPE", "SHAPE_Length", "SHAPE_Area",
        "created_user", "created_date", "last_edited_user", "last_edited_date",
        "RECEPT_NO", "RECEPT_DATE", "MULT_ID", "OWNER_OCCURANCE",
    }
    rows = []
    for k, v in attrs.items():
        if k in skip:
            continue
        if v in (None, "", 0):
            continue
        rows.append(f"  <tr><th>{k}</th><td>{v}</td></tr>")
    body = "\n".join(rows)
    return (
        "<html><body>\n"
        "<h1>ArcGIS Parcel Feature</h1>\n"
        f"<p>Source: {parcel_url}</p>\n"
        "<table>\n"
        f"{body}\n"
        "</table>\n"
        "</body></html>"
    )

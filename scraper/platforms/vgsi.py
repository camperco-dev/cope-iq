import json
import re

import httpx

from scraper.platforms.base import PropertyPlatform


class VGSIPlatform(PropertyPlatform):
    """
    Scraper for VGSI (Vision Government Solutions) GIS assessor sites.

    These are ASP.NET WebForms SPAs used by many New England municipalities.
    The platform exposes a JSON autocomplete endpoint and a property card page.
    """

    _SUFFIXES = (
        r'\b(dr|drive|rd|road|st|street|ave|avenue|blvd|boulevard|ln|lane|'
        r'ct|court|pl|place|way|ter|terrace|ext|loop|cir|circle|'
        r'hwy|highway|pike|trl|trail|run)\.?\s*$'
    )

    async def fetch(
        self,
        base_url: str,
        address: str,
        street: str | None,
        platform_config: dict,
        client: httpx.AsyncClient,
    ) -> tuple[str, str, str, str]:
        """
        Search VGSI for the address, return (pid, matched_address, html, parcel_url).

        Uses a two-step approach:
        1. POST to async.asmx/GetDataAddress for address autocomplete
        2. GET Parcel.aspx?Pid=<pid> for the full property card HTML

        Raises ValueError if no match is found.
        """
        base_url = base_url.rstrip("/")
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Referer": f"{base_url}/Search.aspx",
            "User-Agent": "Mozilla/5.0",
        }

        # Use street-only query — VGSI autocomplete is sensitive to city/state noise.
        # Strip street type suffix to handle mismatches (e.g. geocoder "Dr" vs VGSI "EXT").
        query = street or address.split(",")[0].strip()
        query = re.sub(self._SUFFIXES, "", query, flags=re.I).strip()
        print(f"[vgsi] normalized query (suffix stripped): {query!r}")

        # Step 1: address autocomplete
        print(f"[vgsi] search API: {base_url}/async.asmx/GetDataAddress")
        r = await client.post(
            f"{base_url}/async.asmx/GetDataAddress",
            headers=headers,
            content=json.dumps({"inVal": query, "src": "i_address"}),
        )
        r.raise_for_status()
        results = r.json().get("d", [])
        print(f"[vgsi] search returned {len(results)} result(s)")
        if not results:
            raise ValueError(f"Address not found in VGSI database: {query}")

        best = results[0]
        pid = best["id"]
        matched = best["value"]
        print(f"[vgsi] best match: pid={pid!r}  address={matched!r}")

        # Step 2: fetch property card HTML
        parcel_url = f"{base_url}/Parcel.aspx?Pid={pid}"
        print(f"[vgsi] fetching property card: {parcel_url}")
        r2 = await client.get(parcel_url, headers={"User-Agent": "Mozilla/5.0"})
        r2.raise_for_status()

        return pid, matched, r2.text, parcel_url

    def extract_photo_url(self, html: str, base_url: str) -> str | None:
        """Extract property photo URL from images.vgsi.com CDN references in the HTML."""
        match = re.search(r'https://images\.vgsi\.com/[^\s"\']+', html)
        return match.group(0).rstrip(")") if match else None

    def extract_sketch_url(self, html: str, base_url: str) -> str | None:
        """Extract building sketch URL from ParcelSketch.ashx references in the HTML."""
        match = re.search(r'ParcelSketch\.ashx\?[^\s"\']+', html)
        if not match:
            return None
        return base_url.rstrip("/") + "/" + match.group(0).rstrip(")")

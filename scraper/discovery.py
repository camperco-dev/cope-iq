"""
Municipality auto-discovery.

When a municipality is not in our database, probe supported platforms in order.
If found, the municipality is inserted into MongoDB and the doc is returned so
the calling router can proceed immediately without a second lookup.

Discovery order:
  1. VGSI  — https://gis.vgsi.com/{municipality_nospaces}{state_lower}/
  2. qPublic — https://qpublic.schneidercorp.com/Application.aspx?App={county}County{state}

Adding support for a new platform: implement a `_probe_<name>` coroutine with the
same signature as the existing probes and append a call to it in `discover_and_register`.
"""

import re
from datetime import datetime, timezone

import httpx

from db.mongo import municipalities as muni_col

_VGSI_BASE = "https://gis.vgsi.com"
_QPUBLIC_BASE = "https://qpublic.schneidercorp.com"

# Strings present on every real VGSI municipality landing page.
# Sub-page markers (getdataaddress, parcel.aspx) are not on the root page.
_VGSI_MARKERS = ["vision government", "vgs_icon"]


async def _probe_vgsi(
    locality: str, state: str, client: httpx.AsyncClient
) -> dict | None:
    """Probe https://gis.vgsi.com/{locality_nospaces}{state_lower}/."""
    slug = re.sub(r"[^a-z0-9]", "", locality.lower()) + state.lower()
    url = f"{_VGSI_BASE}/{slug}/"
    try:
        r = await client.get(url, follow_redirects=True, timeout=10.0)
        if r.status_code == 200:
            text = r.text.lower()
            if any(m in text for m in _VGSI_MARKERS):
                print(f"[discovery] VGSI probe hit → {url}")
                return {
                    "state": state.upper(),
                    "county": "",
                    "municipality": locality.lower(),
                    "municipality_display": locality.title(),
                    "search_url": f"{_VGSI_BASE}/{slug}/",
                    "search_type": "vgsi",
                    "platform_config": {},
                    "active": True,
                }
        print(f"[discovery] VGSI probe miss ({r.status_code}) → {url}")
    except httpx.HTTPError as exc:
        print(f"[discovery] VGSI probe error → {url}: {exc}")
    return None


async def _probe_qpublic(
    locality: str, state: str, county: str, client: httpx.AsyncClient
) -> dict | None:
    """
    Probe https://qpublic.schneidercorp.com/Application.aspx?App={county}County{state}.

    Requires county (from geocoding). Skipped if county is empty.
    """
    if not county:
        return None

    county_slug = re.sub(r"[^a-zA-Z0-9]", "", county)
    app_id = f"{county_slug}County{state.upper()}"
    url = f"{_QPUBLIC_BASE}/Application.aspx?App={app_id}"
    try:
        r = await client.get(url, follow_redirects=True, timeout=10.0)
        if r.status_code == 200:
            text = r.text.lower()
            if "schneidercorp" in text or "qpublic" in text:
                muni_name = f"{county.lower()} county"
                print(f"[discovery] qPublic probe hit → {url} (app_id={app_id})")
                return {
                    "state": state.upper(),
                    "county": county.title(),
                    "municipality": muni_name,
                    "municipality_display": f"{county.title()} County",
                    "search_url": _QPUBLIC_BASE,
                    "search_type": "qpublic",
                    "platform_config": {"app_id": app_id, "layer_id": "Parcels"},
                    "active": True,
                }
        print(f"[discovery] qPublic probe miss ({r.status_code}) → {url}")
    except httpx.HTTPError as exc:
        print(f"[discovery] qPublic probe error → {url}: {exc}")
    return None


async def discover_and_register(
    locality: str, state: str, county: str = ""
) -> dict | None:
    """
    Try each platform probe in order. On first hit, insert the municipality into
    MongoDB and return the doc (with _id as str). Returns None if no platform
    recognises the locality.

    Args:
        locality: city/town name as returned by geocoding (e.g. "Augusta")
        state:    two-letter state abbreviation (e.g. "ME")
        county:   county name without "County" suffix (e.g. "Kennebec"); used
                  only for qPublic discovery — safe to omit.
    """
    async with httpx.AsyncClient(verify=False, timeout=10.0) as client:
        muni = await _probe_vgsi(locality, state, client)
        if muni is None:
            muni = await _probe_qpublic(locality, state, county, client)

    if muni is None:
        print(f"[discovery] no platform found for {locality!r}, {state!r}")
        return None

    muni["date_added"] = datetime.now(timezone.utc)
    muni["added_by"] = "auto-discovery"

    result = await muni_col().insert_one(muni)
    muni["_id"] = result.inserted_id
    print(
        f"[discovery] registered {muni['municipality_display']}, {muni['state']} "
        f"({muni['search_type']}) → _id={muni['_id']}"
    )
    return muni

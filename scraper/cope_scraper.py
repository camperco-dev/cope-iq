import anthropic
import httpx
import json
import re
import warnings
warnings.filterwarnings("ignore", message="Unverified HTTPS request")
from scraper.prompts import SYSTEM_PROMPT, extraction_prompt
from config import settings


async def _vgsi_fetch_property_html(base_url: str, address: str) -> tuple[str, str, str]:
    """
    Search VGSI for the address, return (pid, matched_address, parcel_html).
    Raises ValueError on no match.
    """
    base_url = base_url.rstrip("/")
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Referer": f"{base_url}/Search.aspx",
        "User-Agent": "Mozilla/5.0",
    }

    # Strip street type suffix — avoids mismatches when VGSI uses a different
    # suffix than the geocoder (e.g. VGSI "EXT" vs geocoder "Dr")
    _SUFFIXES = r'\b(dr|drive|rd|road|st|street|ave|avenue|blvd|boulevard|ln|lane|ct|court|pl|place|way|ter|terrace|ext|loop|cir|circle|hwy|highway|pike|trl|trail|run)\.?\s*$'
    address = re.sub(_SUFFIXES, '', address, flags=re.I).strip()
    print(f"[scraper] normalized query (suffix stripped): {address!r}")

    async with httpx.AsyncClient(timeout=15.0, verify=False) as client:
        # Step 1: address autocomplete API
        print(f"[scraper] VGSI search API: {base_url}/async.asmx/GetDataAddress")
        r = await client.post(
            f"{base_url}/async.asmx/GetDataAddress",
            headers=headers,
            content=json.dumps({"inVal": address, "src": "i_address"}),
        )
        r.raise_for_status()
        results = r.json().get("d", [])
        print(f"[scraper] search returned {len(results)} result(s)")
        if not results:
            raise ValueError(f"Address not found in VGSI database: {address}")

        best = results[0]
        pid = best["id"]
        matched = best["value"]
        print(f"[scraper] best match: pid={pid!r}  address={matched!r}")

        # Step 2: fetch property card HTML
        parcel_url = f"{base_url}/Parcel.aspx?Pid={pid}"
        print(f"[scraper] fetching property card: {parcel_url}")
        r2 = await client.get(parcel_url, headers={"User-Agent": "Mozilla/5.0"})
        r2.raise_for_status()
        return pid, matched, r2.text, parcel_url


async def search_cope(address: str, municipality: dict, street: str | None = None) -> dict:
    if not settings.anthropic_api_key:
        return {"error": "AI service not configured"}

    search_type = municipality.get("search_type", "vgsi")
    base_url = municipality["search_url"]

    # ── Fetch property HTML ──────────────────────────────────────────────────
    if search_type == "vgsi":
        try:
            # VGSI search only wants the street portion, not city/state
            vgsi_query = street or address.split(",")[0].strip()
            print(f"[scraper] VGSI query: {vgsi_query!r}")
            pid, matched_address, html, parcel_url = await _vgsi_fetch_property_html(base_url, vgsi_query)
        except ValueError as e:
            return {"error": str(e)}
        except httpx.HTTPError as e:
            print(f"[scraper] HTTP error fetching VGSI: {e}")
            return {"error": f"Could not reach property database: {e}"}
    else:
        return {"error": f"Unsupported search_type: {search_type}"}

    # ── Preserve image/sketch URLs before stripping HTML ────────────────────
    photo_match = re.search(r'https://images\.vgsi\.com/[^\s"\']+', html)
    photo_url = photo_match.group(0).rstrip(')') if photo_match else None

    sketch_match = re.search(r'ParcelSketch\.ashx\?[^\s"\']+', html)
    sketch_url = (base_url.rstrip('/') + '/' + sketch_match.group(0).rstrip(')')) if sketch_match else None

    print(f"[scraper] photo_url={photo_url!r}")
    print(f"[scraper] sketch_url={sketch_url!r}")

    # ── Strip HTML down to readable text to save tokens ─────────────────────
    # Remove scripts, styles, comments
    html_clean = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.S | re.I)
    html_clean = re.sub(r'<style[^>]*>.*?</style>', '', html_clean, flags=re.S | re.I)
    html_clean = re.sub(r'<!--.*?-->', '', html_clean, flags=re.S)
    # Preserve href/src values as inline text before stripping tags
    html_clean = re.sub(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>', lambda m: m.group(0) + f' [{m.group(1)}] ', html_clean, flags=re.I)
    # Strip tags, collapse whitespace
    text = re.sub(r'<[^>]+>', ' ', html_clean)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n\s*\n+', '\n', text).strip()
    print(f"[scraper] property card text: {len(text)} chars")

    # ── Ask Claude to extract COPE JSON from the text ────────────────────────
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    print(f"[scraper] sending to Claude for extraction (no tools)")
    try:
        response = await client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=2000,
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": extraction_prompt(address, matched_address, pid, parcel_url, text),
            }],
        )
    except anthropic.APITimeoutError:
        print(f"[scraper] ERROR: Claude timeout")
        return {"error": "AI extraction timed out"}
    except anthropic.APIError as e:
        print(f"[scraper] ERROR: Claude API error: {e}")
        return {"error": f"AI error: {e}"}

    print(f"[scraper] Claude stop_reason={response.stop_reason}")
    raw_text = "\n".join(b.text for b in response.content if hasattr(b, "text"))
    print(f"[scraper] raw response length={len(raw_text)} chars")

    json_match = re.search(r'\{[\s\S]*\}', raw_text)
    if not json_match:
        print(f"[scraper] ERROR: no JSON in response. Preview: {raw_text[:300]!r}")
        return {"error": "Could not parse extraction response"}

    try:
        result = json.loads(json_match.group())
        print(f"[scraper] JSON parsed OK  keys={list(result.keys())}")
        return result
    except json.JSONDecodeError as e:
        print(f"[scraper] ERROR: malformed JSON: {e}")
        return {"error": "Malformed JSON in extraction response"}

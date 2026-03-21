import anthropic
import httpx
import json
import re
import warnings
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

from scraper.platforms import PLATFORM_REGISTRY
from scraper.prompts import SYSTEM_PROMPT, extraction_prompt
from config import settings


def _html_to_text(html: str) -> str:
    """
    Strip an HTML property card down to readable plain text.

    Removes scripts, styles, and comments; preserves href values as inline
    text so link targets (e.g. sketch/photo URLs) survive the tag strip.
    Collapses whitespace to keep the token count manageable for Claude.
    """
    # Remove scripts, styles, and HTML comments.
    cleaned = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.S | re.I)
    cleaned = re.sub(r'<style[^>]*>.*?</style>', '', cleaned, flags=re.S | re.I)
    cleaned = re.sub(r'<!--.*?-->', '', cleaned, flags=re.S)
    # Preserve href values as inline text before stripping tags.
    cleaned = re.sub(
        r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>',
        lambda m: m.group(0) + f' [{m.group(1)}] ',
        cleaned,
        flags=re.I,
    )
    # Strip remaining tags, collapse whitespace.
    text = re.sub(r'<[^>]+>', ' ', cleaned)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n\s*\n+', '\n', text).strip()
    return text


async def search_cope(address: str, municipality: dict, street: str | None = None) -> dict:
    """
    Fetch and extract COPE data for an address.

    Looks up the platform implementation from PLATFORM_REGISTRY using the
    municipality's search_type, delegates fetching and media extraction to
    the platform, then calls Claude to extract structured JSON from the
    property card text.

    Args:
        address:      Full geocoded address including city and state.
        municipality: MongoDB municipality document. Must contain search_type
                      and search_url. May contain platform_config dict.
        street:       Street-only portion from geocoder; passed to platform.fetch()
                      for platforms that are sensitive to city/state noise.

    Returns:
        Dict matching the COPE JSON schema, or {"error": "<message>"} on failure.
    """
    if not settings.anthropic_api_key:
        return {"error": "AI service not configured"}

    search_type = municipality.get("search_type", "vgsi")
    base_url = municipality["search_url"]
    platform_config = municipality.get("platform_config", {})

    print(f"[scraper] platform={search_type!r}  config_keys={list(platform_config.keys())}")

    # ── Resolve platform implementation ──────────────────────────────────────
    platform = PLATFORM_REGISTRY.get(search_type)
    if platform is None:
        return {"error": f"Unsupported search_type: {search_type!r}. "
                         f"Registered platforms: {list(PLATFORM_REGISTRY.keys())}"}

    # ── Fetch property HTML via the platform ─────────────────────────────────
    # The shared client owns SSL settings (verify=False for Windows cert chain issues
    # with some municipal HTTPS hosts) and connection pooling.
    async with httpx.AsyncClient(timeout=15.0, verify=False) as client:
        try:
            pid, matched_address, html, parcel_url = await platform.fetch(
                base_url, address, street, platform_config, client
            )
        except ValueError as e:
            return {"error": str(e)}
        except httpx.HTTPError as e:
            print(f"[scraper] HTTP error fetching {search_type}: {e}")
            return {"error": f"Could not reach property database: {e}"}

    # ── Extract media URLs before stripping HTML ──────────────────────────────
    photo_url = platform.extract_photo_url(html, base_url)
    sketch_url = platform.extract_sketch_url(html, base_url)
    print(f"[scraper] photo_url={photo_url!r}")
    print(f"[scraper] sketch_url={sketch_url!r}")

    # ── Convert HTML to plain text for Claude ─────────────────────────────────
    text = _html_to_text(html)
    print(f"[scraper] property card text: {len(text)} chars")

    # ── Build system prompt, injecting platform hints if present ─────────────
    hints = platform.extraction_hints()
    system_prompt = SYSTEM_PROMPT if not hints else f"{SYSTEM_PROMPT}\n\n{hints}"

    # ── Ask Claude to extract COPE JSON ──────────────────────────────────────
    ai_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    print(f"[scraper] sending to Claude for extraction (no tools)")
    try:
        response = await ai_client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=2000,
            system=system_prompt,
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

    # ── Parse JSON from Claude's response ────────────────────────────────────
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

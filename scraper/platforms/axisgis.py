"""
AxisGIS platform (CAI Technologies, axisgis.com).

Discovery notes (2026-03-22):
  - CamdenME is hosted on gisserver3.axisgis.com, but that ArcGIS server
    requires an auth token and is not directly queryable without one.
  - Instead, the public Node.js API at api.axisgis.com provides two
    unauthenticated endpoints that together cover the full scraping flow:

    1. Search:
       GET https://api.axisgis.com/node/axisapi/search/{municipalityId}?q={query}
       Returns: {results: [{PID, PropertyAddress, PropertyStreet, ParcelNumber,
                             CamaFullNumber, OwnerName, CoOwnerName, ImagePath,
                             Category, ...}]}

    2. Property card PDF (if CAMA vendor configured):
       GET https://api.axisgis.com/node/axisapi/document-view/{municipalityId}
           ?path=Docs/Batch/{cama_vendor}_Property_Card/{PID}.pdf
       Returns: PDF binary. The PID is the numeric PID from the search result,
       NOT the encoded map/lot string described in some AxisGIS documentation.

  - Camden ME uses Vision CAMA. Confirmed working PDF path:
       Docs/Batch/Vision_Property_Card/{PID}.pdf
    Example: PID=1833 for 34 Elm St → 2.7 MB, 3-page Vision property card PDF.

  - Photos are not accessible via any public AxisGIS URL endpoint.
    They ARE embedded as JPEG images inside Form XObjects within the CAMA
    property card PDF. pymupdf (fitz) is used to scan the document xref table
    for /Image objects, extract the two images (photo + sketch), resize the
    photo to ≤1024 px wide, and return both as base64 data URIs embedded as
    HTML-comment sentinels in the returned content string.  The dispatcher's
    _html_to_text() strips those comments before passing text to Claude, so
    only extract_photo_url() / extract_sketch_url() ever see them.
"""
import base64
import io
import json
import math
import re

import fitz  # pymupdf — image extraction from Form XObjects
import httpx
from pypdf import PdfReader

from .base import PropertyPlatform
from .vgsi import VGSIPlatform

_vgsi = VGSIPlatform()

# Sentinel patterns appended to the returned html string so the dispatcher can
# recover the data URIs via extract_photo_url / extract_sketch_url.  They are
# HTML comments, so _html_to_text() strips them before the text reaches Claude.
_PHOTO_SENTINEL  = "<!--AXISGIS_PHOTO:{data_uri}-->"
_SKETCH_SENTINEL = "<!--AXISGIS_SKETCH:{data_uri}-->"
_PHOTO_RE  = re.compile(r"<!--AXISGIS_PHOTO:(data:image/[^;]+;base64,[^-]*)-->", re.S)
_SKETCH_RE = re.compile(r"<!--AXISGIS_SKETCH:(data:image/[^;]+;base64,[^-]*)-->", re.S)

_AXIS_API = "https://api.axisgis.com/node/axisapi"
_AXIS_REPORTS = "https://axisreports.axisgis.com/"
_ORIGIN = "https://www.axisgis.com"

# CAMA vendors tried in order when cama_vendor is not configured.
# Each maps to a path prefix under Docs/Batch/ on the document API.
# "Trio" is CAI Technologies' own CAMA product; its PDF path uses only the
# numeric account number portion of the PID (e.g. "2158" from PID "2158-1").
_KNOWN_VENDORS = ["Vision", "Avitar", "Munis", "Trio"]


def _headers(referer: str) -> dict:
    """Build request headers for the AxisGIS Node API.

    The API checks the Referer header and returns 'permission denied' without it.
    The Referer must point to the municipality's AxisGIS page (e.g.
    https://www.axisgis.com/CamdenME/).
    """
    return {
        "User-Agent": "Mozilla/5.0",
        "Origin": _ORIGIN,
        "Referer": referer,
        "Accept": "application/json",
    }


class AxisGISPlatform(PropertyPlatform):
    """
    Scraper for AxisGIS municipalities (CAI Technologies, axisgis.com).

    Uses the public AxisGIS Node.js API to search for parcels by address,
    then fetches the CAMA property card PDF via the document-view endpoint.
    Falls back to formatting the search result attributes as plain text if
    no PDF is available.

    Required platform_config keys:
        municipality_id (str): AxisGIS municipality ID, e.g. "CamdenME".
        cama_vendor     (str|None): CAMA software vendor used for PDF path
                        construction. Known values: "Vision", "Avitar", "Munis".
                        If absent or None, all known vendors are probed in order
                        so the platform works for any AxisGIS municipality without
                        requiring this to be pre-configured.
        vgsi_url        (str|None): If the municipality also has a VGSI endpoint
                        (e.g. "https://gis.vgsi.com/camdenme/"), VGSI is tried
                        first because it returns richer structured HTML.  AxisGIS
                        is used as the fallback if VGSI fails or finds no match.
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
        Fetch an AxisGIS property card.

        Raises ValueError if the address is not found.
        """
        municipality_id = platform_config.get("municipality_id") or _muni_id_from_url(
            base_url
        )
        cama_vendor = platform_config.get("cama_vendor")

        # Ensure base_url ends with / for use as Referer
        referer = base_url if base_url.endswith("/") else base_url + "/"
        hdrs = _headers(referer)

        raw = street or address.split(",")[0].strip()
        house_num, street_name = _split_address(raw)
        search_word = street_name.split()[0] if street_name else street_name
        query = f"{house_num} {search_word}".strip()
        print(f"[axisgis] searching: municipality={municipality_id!r} q={query!r}")

        # Step 0 — VGSI preferred path
        # If the municipality also has a VGSI URL, try VGSI first.  VGSI returns
        # richer structured HTML with full COPE data, so it's preferable to the
        # AxisGIS PDF path.  Fall through to AxisGIS on any error or no-match.
        vgsi_url = platform_config.get("vgsi_url")
        if vgsi_url:
            print(f"[axisgis] vgsi_url configured — trying VGSI first: {vgsi_url}")
            try:
                result = await _vgsi.fetch(vgsi_url, address, street, {}, client)
                print("[axisgis] VGSI succeeded — returning VGSI result")
                return result
            except (ValueError, httpx.HTTPError) as exc:
                print(f"[axisgis] VGSI attempt failed ({exc}) — falling through to AxisGIS")

        # Step 1 — address search via AxisGIS Node API
        search_url = f"{_AXIS_API}/search/{municipality_id}"
        r1 = await client.get(
            search_url,
            params={"q": query},
            headers=hdrs,
            follow_redirects=True,
        )
        r1.raise_for_status()

        data = r1.json()
        results = data.get("results", [])
        if not results:
            raise ValueError(
                f"Address not found in AxisGIS database ({municipality_id}): {address}"
            )

        # Pick best match from the result list
        best = _pick_result(results, house_num, street_name)
        pid = str(best.get("PID", ""))
        matched_address = (best.get("PropertyAddress") or "").strip()
        print(f"[axisgis] match: pid={pid!r}  address={matched_address!r}")

        # Step 2a — fetch CAMA property card PDF
        # vendors_to_try: explicit config value first; if absent or None, probe
        # all known vendors in order so any AxisGIS municipality works without
        # requiring cama_vendor to be pre-configured.
        pdf_url = None
        text_content = None

        if pid:
            vendors_to_try = [cama_vendor] if cama_vendor else _KNOWN_VENDORS
            # Trio CAMA uses the numeric account number only (e.g. "2158" from
            # PID "2158-1"). All other vendors use the full PID as-is.
            pid_for_vendor = {
                "Trio": pid.split("-")[0] if "-" in pid else pid,
            }
            for vendor in vendors_to_try:
                doc_pid = pid_for_vendor.get(vendor, pid)
                pdf_path = f"Docs/Batch/{vendor}_Property_Card/{doc_pid}.pdf"
                candidate_url = f"{_AXIS_API}/document-view/{municipality_id}?path={pdf_path}"
                print(f"[axisgis] trying PDF ({vendor}): {candidate_url}")
                try:
                    r2 = await client.get(candidate_url, headers=hdrs, follow_redirects=True)
                    if (
                        r2.status_code == 200
                        and "application/pdf" in r2.headers.get("content-type", "")
                    ):
                        text, photo_bytes, sketch_bytes = _extract_pdf_content(r2.content)
                        if text.strip():
                            text_content = text
                            pdf_url = candidate_url
                            # Append image sentinels so extract_photo/sketch_url
                            # can recover them without breaking the text pipeline.
                            if photo_bytes:
                                uri = "data:image/jpeg;base64," + base64.b64encode(photo_bytes).decode()
                                text_content += "\n" + _PHOTO_SENTINEL.format(data_uri=uri)
                            if sketch_bytes:
                                uri = "data:image/jpeg;base64," + base64.b64encode(sketch_bytes).decode()
                                text_content += "\n" + _SKETCH_SENTINEL.format(data_uri=uri)
                            print(
                                f"[axisgis] PDF extracted via {vendor}: "
                                f"{len(text)} chars, photo={len(photo_bytes) if photo_bytes else 0}B "
                                f"sketch={len(sketch_bytes) if sketch_bytes else 0}B"
                            )
                            break
                        else:
                            print(f"[axisgis] {vendor} PDF empty — trying next vendor")
                    else:
                        print(f"[axisgis] {vendor} PDF not found (status={r2.status_code})")
                except httpx.HTTPError as exc:
                    print(f"[axisgis] {vendor} PDF fetch error ({exc})")

        # Step 2b — axisreports.axisgis.com report endpoint (CAI Trio CAMA)
        # POST https://axisreports.axisgis.com/ with JSON body (sent as text/plain).
        # Response body is base64-encoded PDF.  The Referer must be the AxisGIS
        # root (https://www.axisgis.com/), NOT the municipality-specific page.
        if text_content is None:
            parcel_num_for_report = (
                best.get("CamaFullNumber") or best.get("ParcelNumber") or pid
            )
            report_payload = json.dumps({
                "format": "PDF",
                "path": f"/PropertyCards/PCard_{municipality_id}",
                "rpDatabaseName": municipality_id,
                "rpDisclaimer": (
                    "This information is believed to be correct but is subject "
                    "to change and is not warranteed."
                ),
                "rpSubjectCamaFullNum": parcel_num_for_report,
            })
            report_hdrs = {
                **hdrs,
                "Content-Type": "text/plain;charset=UTF-8",
                "Referer": f"{_ORIGIN}/",   # root, not municipality page
                "Origin": _ORIGIN,
            }
            report_url = _AXIS_REPORTS
            print(f"[axisgis] trying axisreports: parcel={parcel_num_for_report!r}")
            try:
                r_rep = await client.post(
                    report_url,
                    content=report_payload.encode(),
                    headers=report_hdrs,
                    follow_redirects=True,
                )
                print(f"[axisgis] axisreports status={r_rep.status_code}")
                if (
                    r_rep.status_code == 200
                    and "application/pdf" in r_rep.headers.get("content-type", "")
                ):
                    # Response body is base64-encoded PDF bytes per content-encoding header.
                    # Try raw bytes first (in case httpx already decoded it), fall back
                    # to explicit base64 decode.
                    raw = r_rep.content
                    if raw[:4] == b"%PDF":
                        pdf_bytes = raw
                    else:
                        pdf_bytes = base64.b64decode(raw)
                    text, photo_bytes, sketch_bytes = _extract_pdf_content(pdf_bytes)
                    if text.strip():
                        text_content = text
                        pdf_url = report_url
                        if photo_bytes:
                            uri = "data:image/jpeg;base64," + base64.b64encode(photo_bytes).decode()
                            text_content += "\n" + _PHOTO_SENTINEL.format(data_uri=uri)
                        if sketch_bytes:
                            uri = "data:image/jpeg;base64," + base64.b64encode(sketch_bytes).decode()
                            text_content += "\n" + _SKETCH_SENTINEL.format(data_uri=uri)
                        print(
                            f"[axisgis] axisreports PDF extracted: "
                            f"{len(text)} chars, photo={len(photo_bytes) if photo_bytes else 0}B "
                            f"sketch={len(sketch_bytes) if sketch_bytes else 0}B"
                        )
                    else:
                        print("[axisgis] axisreports PDF empty")
                else:
                    print(f"[axisgis] axisreports body: {r_rep.text[:200]}")
            except (httpx.HTTPError, Exception) as exc:
                print(f"[axisgis] axisreports error: {exc}")

        # Step 2d — CAI properties JSON endpoint (municipalities using CAI CAMA,
        # which serves a client-side blob: property card rather than a vendor PDF)
        # Endpoint: GET /properties/{municipalityId}?f=json&q={parcelNum}&parcelNum={parcelNum}
        # parcelNum is CamaFullNumber (map/lot, e.g. "U03-011") from the search result.
        if text_content is None:
            parcel_num = (
                best.get("CamaFullNumber")
                or best.get("ParcelNumber")
                or pid
            )
            props_url = (
                f"{_AXIS_API}/properties/{municipality_id}"
                f"?f=json&q={parcel_num}&parcelNum={parcel_num}"
            )
            print(f"[axisgis] trying CAI properties JSON: {props_url}")
            try:
                r3 = await client.get(props_url, headers=hdrs, follow_redirects=True)
                print(f"[axisgis] CAI properties JSON status={r3.status_code}")
                if r3.status_code == 200:
                    try:
                        props_data = r3.json()
                    except ValueError:
                        props_data = {}
                    # Detect API-level permission denial returned as 200 JSON
                    if isinstance(props_data, dict) and props_data.get("status") == "permission denied":
                        print(f"[axisgis] CAI properties JSON permission denied: {props_data}")
                    else:
                        formatted = _format_properties_json(props_data, municipality_id)
                        if formatted.strip():
                            text_content = formatted
                            pdf_url = props_url
                            print(f"[axisgis] CAI properties JSON: {len(formatted)} chars")
                        else:
                            print("[axisgis] CAI properties JSON empty")
                else:
                    print(f"[axisgis] CAI properties JSON body: {r3.text[:300]}")
            except (httpx.HTTPError, ValueError) as exc:
                print(f"[axisgis] CAI properties JSON error: {exc}")

        # Step 2e — fall back to formatting the search result attributes
        if text_content is None:
            print("[axisgis] using attribute fallback text")
            text_content = _format_attributes(best, municipality_id)
            pdf_url = search_url  # use the search URL as the parcel URL

        parcel_url = pdf_url or search_url
        return pid, matched_address, text_content, parcel_url

    def extract_photo_url(self, html: str, base_url: str) -> str | None:
        """Return property photo data URI embedded by fetch() as an HTML-comment sentinel."""
        m = _PHOTO_RE.search(html)
        return m.group(1) if m else None

    def extract_sketch_url(self, html: str, base_url: str) -> str | None:
        """Return building sketch data URI embedded by fetch() as an HTML-comment sentinel."""
        m = _SKETCH_RE.search(html)
        return m.group(1) if m else None

    def extraction_hints(self) -> str:
        return (
            "This property card is from AxisGIS (CAI Technologies / axisgis.com).\n"
            "Data may come from (a) a CAMA vendor PDF (Vision/Avitar/Munis layout),\n"
            "(b) the CAI CAMA properties JSON (dot-notation keys, e.g. "
            "'Building.YearBuilt', 'Land.LandArea', 'Assessment.TotalValue'), or\n"
            "(c) basic AxisGIS search result attributes.\n"
            "Field mappings (attribute fallback / CAI JSON mode):\n"
            "  'PropertyAddress' / 'Building.Location'  → property address\n"
            "  'ParcelNumber' / 'CamaFullNumber'         → parcel ID\n"
            "  'OwnerName' / 'Owner.Name'                → owner name\n"
            "  'Building.YearBuilt'                      → year built\n"
            "  'Building.LivingArea'                     → living area (sq ft)\n"
            "  'Assessment.LandValue'                    → assessed land value\n"
            "  'Assessment.BuildingValue'                → assessed building value\n"
            "  'Assessment.TotalValue'                   → total assessed value\n"
            "Note: exact key names vary — extract whatever COPE-relevant fields are present.\n"
            "When the source is a Vision PDF, use the standard Vision/VGSI field layout."
        )


# ── Helpers ─────────────────────────────────────────────────────────────────


def _muni_id_from_url(base_url: str) -> str:
    """
    Derive the AxisGIS municipality ID from the search_url.
    e.g. "https://www.axisgis.com/CamdenME/" → "CamdenME"
    """
    path = base_url.rstrip("/").split("/")[-1]
    return path


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


def _pick_result(results: list[dict], house_num: str, street_name: str) -> dict:
    """
    Return the best matching result from the AxisGIS search results list.
    Tries exact house number + street name match first; falls back to first result.
    """
    q_num = house_num.strip()
    q_street = _normalize(street_name)

    for item in results:
        addr = item.get("PropertyAddress", "")
        parts = addr.strip().split(None, 1)
        if len(parts) == 2:
            r_num, r_street = parts[0], parts[1]
        else:
            r_num, r_street = "", addr.strip()

        if r_num == q_num and _street_match(q_street, r_street):
            return item

    # Fallback: return first result
    return results[0]


def _extract_pdf_text(content: bytes) -> str:
    """Extract plain text from a PDF binary using pypdf."""
    reader = PdfReader(io.BytesIO(content))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _to_rgb(pix: "fitz.Pixmap") -> "fitz.Pixmap":
    """
    Normalise a fitz Pixmap to plain RGB (no alpha, RGB colorspace) so it can
    be JPEG-encoded.  JPEG supports neither alpha channels nor CMYK directly.

    Strategy:
      1. Strip alpha by rebuilding the pixmap from its raw samples with the
         alpha byte removed per pixel.  fitz.Pixmap(cs, src) fails when src
         has alpha, so we use the fitz.Pixmap(cs, w, h, samples, alpha)
         constructor which accepts raw bytes directly.
      2. Convert non-RGB colorspace (CMYK etc.) using fitz.Pixmap(csRGB, src)
         which works once alpha has been removed.
    """
    if pix.alpha:
        n_color = pix.n - 1  # color channels without alpha (3 for RGBA)
        raw = bytes(pix.samples)
        # Drop the alpha byte from each pixel: keep first n_color of every pix.n bytes
        rgb_data = bytes(b for i, b in enumerate(raw) if (i % pix.n) < n_color)
        cs = pix.colorspace if pix.colorspace else fitz.csRGB
        pix = fitz.Pixmap(cs, pix.width, pix.height, rgb_data, False)
    if pix.colorspace != fitz.csRGB:
        pix = fitz.Pixmap(fitz.csRGB, pix)
    return pix


def _is_logo(w: int, h: int) -> bool:
    """
    Return True if image dimensions are obviously a logo/banner or a tiny icon.

    Only dimension-based checks that are safe across all CAMA vendors:
      - Landscape aspect ratio >3:1  → horizontal banner/logo (e.g. 636×203)
      - Very small area (<5 000 px²)  → tiny icon / graphic

    Near-square filtering is intentionally absent: building sketches can also
    be near-square, and municipality seals are better identified by proximity
    to their surrounding text (see _label_images_by_proximity).
    """
    if h == 0:
        return True
    return (w / h) > 3.0 or (w * h) < 5_000


_LOGO_LABEL_RE = re.compile(
    r"\b(town\s+of|city\s+of|village\s+of|county\s+of|seal|crest|incorporated)\b", re.I
)


def _find_logo_xrefs(doc: "fitz.Document") -> set[int]:
    """
    Return the set of xrefs for municipality logos/seals identified by proximity
    to civic identity text ("Town of X", "City of", "seal", "crest", etc.)
    within ~1 inch of the image's bounding rectangle on the page.
    """
    logos: set[int] = set()
    PROX = 72  # points (~1 inch)

    for page in doc:
        text_blocks = [
            (b[0], b[1], b[2], b[3], b[4])
            for b in page.get_text("blocks")
            if b[6] == 0
        ]
        for img_info in page.get_images(full=True):
            xref = img_info[0]
            if xref in logos:
                continue
            try:
                rects = page.get_image_rects(xref)
            except Exception:
                continue
            if not rects:
                continue
            ir = rects[0]
            nearby = " ".join(
                txt
                for x0, y0, x1, y1, txt in text_blocks
                if x0 < ir.x1 + PROX and x1 > ir.x0 - PROX
                and y0 < ir.y1 + PROX and y1 > ir.y0 - PROX
            )
            if _LOGO_LABEL_RE.search(nearby):
                logos.add(xref)

    return logos


def _classify_pixels(pix: "fitz.Pixmap") -> tuple[float, float]:
    """
    Sample every 4th pixel and return (white_ratio, midtone_ratio).

    white_ratio   — fraction of pixels where all channels ≥ 220 (near-white).
    midtone_ratio — fraction of pixels with average brightness in [60, 200).

    Sampling every 4th pixel is fast enough for images up to several megapixels.
    """
    samples = bytes(pix.samples)
    n = pix.n
    step = n * 4
    white = mid = sampled = 0
    for i in range(0, len(samples), step):
        r = samples[i]
        g = samples[i + 1] if n > 1 else r
        b = samples[i + 2] if n > 2 else r
        if r >= 220 and g >= 220 and b >= 220:
            white += 1
        elif 60 <= (r + g + b) // 3 < 200:
            mid += 1
        sampled += 1
    if sampled == 0:
        return 0.0, 0.0
    return white / sampled, mid / sampled


def _is_sketch_image(pix: "fitz.Pixmap") -> bool:
    """
    Return True if the pixmap looks like a line drawing rather than a photograph.

    Line drawings (building sketches, floor plans) are predominantly white with
    sparse black lines — more than 85% of sampled pixels are near-white.
    """
    white_ratio, _ = _classify_pixels(pix)
    return white_ratio > 0.85


def _looks_like_photo(pix: "fitz.Pixmap") -> bool:
    """
    Return True if the pixel distribution is consistent with a real photograph.

    Photos have smooth tonal gradients: typically ≥25% of pixels fall in the
    mid-tone range (average brightness 60–200).  Seals, crests, and logos have
    a bimodal distribution — mostly near-black ink on near-white background —
    so their mid-tone fraction is low.  This lets us reject the town seal even
    when the proximity logo filter misses it (e.g. when seal text is rasterized
    into the image rather than present as PDF text elements).
    """
    _, midtone_ratio = _classify_pixels(pix)
    return midtone_ratio >= 0.25


def _extract_pdf_content(content: bytes) -> tuple[str, bytes | None, bytes | None]:
    """
    Extract text and the two embedded JPEG images from a CAMA property card PDF.

    Vision (and other CAMA vendors) embed a property photo and a building sketch
    as JPEG streams inside PDF Form XObjects.  pypdf cannot reach these; fitz
    (pymupdf) scans the entire xref table for /Image objects regardless of nesting.

    Image classification strategy:
      1. Proximity logo filter — images near "Town of"/"City of"/"seal" text are
         dropped as municipality logos before any slot assignment.
      2. Pixel content analysis — each remaining image is decoded and sampled:
         >85% near-white pixels → line drawing (sketch); otherwise → photo.
         This is more reliable than position or label proximity because building
         sketches vary in shape and the sketch section header can be close to
         the photo cell in table-based PDF layouts.
      3. Slot assignment — largest sketch-classified image → sketch slot;
         largest photo-classified image with area ≥ 40 000 px² → photo slot.
         (The 40 000 px² floor excludes tiny decorative graphics left over after
         the sketch is claimed, e.g. a 230×160 ornament in CAI Trio cards.)
      4. Size fallback — if content analysis yields nothing, fall back to
         largest-first size ordering with has_photo from text.

    The photo is shrunk to ≤1200 px wide before JPEG-encoding.

    Returns:
        (text, photo_jpeg_bytes, sketch_jpeg_bytes)
        Either image value is None if no suitable image was found for that slot.
    """
    # ── Text extraction (pypdf) ───────────────────────────────────────────────
    reader = PdfReader(io.BytesIO(content))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)

    has_photo = "no photo" not in text.lower()

    # ── Image extraction (fitz) ───────────────────────────────────────────────
    photo_bytes: bytes | None = None
    sketch_bytes: bytes | None = None

    try:
        doc = fitz.open(stream=content, filetype="pdf")

        # Step 1: drop municipality logos identified by proximity to civic text
        logo_xrefs = _find_logo_xrefs(doc)

        # Step 2: collect all non-trivial, non-logo images sorted largest-first
        image_xrefs: list[tuple[int, int]] = []  # (xref, pixel_area)
        for xref in range(1, doc.xref_length()):
            try:
                if doc.xref_get_key(xref, "Subtype") != ("name", "/Image"):
                    continue
                if xref in logo_xrefs:
                    continue
                w_val = doc.xref_get_key(xref, "Width")
                h_val = doc.xref_get_key(xref, "Height")
                w = int(w_val[1]) if w_val and w_val[0] == "int" else 0
                h = int(h_val[1]) if h_val and h_val[0] == "int" else 0
                if w > 0 and h > 0 and not _is_logo(w, h):
                    image_xrefs.append((xref, w * h))
            except Exception:
                continue

        image_xrefs.sort(key=lambda x: x[1], reverse=True)

        # Step 3: classify each image as sketch (line drawing) or photo by pixel content
        _MIN_PHOTO_AREA = 40_000
        sketch_xref: int | None = None
        photo_xref:  int | None = None
        sketch_candidates: list[tuple[int, int]] = []
        photo_candidates:  list[tuple[int, int]] = []

        for xref, area in image_xrefs:
            try:
                pix = _to_rgb(fitz.Pixmap(doc, xref))
                if _is_sketch_image(pix):
                    sketch_candidates.append((xref, area))
                elif _looks_like_photo(pix):
                    photo_candidates.append((xref, area))
                # else: bimodal image (seal/crest/logo) — discard
            except Exception:
                photo_candidates.append((xref, area))

        if sketch_candidates:
            sketch_xref = sketch_candidates[0][0]
        if has_photo and photo_candidates and photo_candidates[0][1] >= _MIN_PHOTO_AREA:
            photo_xref = photo_candidates[0][0]

        print(
            f"[axisgis] PDF images found: {len(image_xrefs)} (after logo filter)  "
            f"has_photo={has_photo}  "
            f"sketches={len(sketch_candidates)}  photos={len(photo_candidates)}"
        )

        # Step 4: size-based fallback when content analysis finds nothing
        if sketch_xref is None and photo_xref is None and image_xrefs:
            photo_slot  = 0 if has_photo else None
            sketch_slot = 1 if has_photo else 0
            photo_xref  = image_xrefs[photo_slot][0]  if photo_slot  is not None and len(image_xrefs) > photo_slot  else None
            sketch_xref = image_xrefs[sketch_slot][0] if len(image_xrefs) > sketch_slot else None

        # Step 5: render to JPEG
        if photo_xref is not None:
            pix = _to_rgb(fitz.Pixmap(doc, photo_xref))
            if pix.width > 1200:
                n = max(1, math.floor(math.log2(pix.width / 1200)))
                pix.shrink(n)
            photo_bytes = pix.tobytes("jpeg")
            print(f"[axisgis] photo: {pix.width}x{pix.height}  {len(photo_bytes)} bytes")

        if sketch_xref is not None:
            pix = _to_rgb(fitz.Pixmap(doc, sketch_xref))
            sketch_bytes = pix.tobytes("jpeg")
            print(f"[axisgis] sketch: {pix.width}x{pix.height}  {len(sketch_bytes)} bytes")

        doc.close()
    except Exception as exc:
        print(f"[axisgis] image extraction error (non-fatal): {exc}")

    return text, photo_bytes, sketch_bytes


def _format_attributes(item: dict, municipality_id: str) -> str:
    """
    Format a search result attribute dict as a readable text block for Claude.
    Used when no PDF or CAI properties JSON is available.
    """
    lines = [f"PROPERTY CARD — {municipality_id}"]
    field_labels = {
        "PropertyAddress": "Address",
        "ParcelNumber": "Parcel Number (GIS)",
        "CamaFullNumber": "CAMA Parcel Number",
        "PID": "Property ID",
        "OwnerName": "Owner Name",
        "CoOwnerName": "Co-Owner / C/O",
        "PropertyStreet": "Street",
    }
    for key, label in field_labels.items():
        val = item.get(key)
        if val:
            lines.append(f"{label}: {val}")
    # Append any remaining fields not already shown
    shown = set(field_labels.keys()) | {"ImagePath", "ImageStaffOnly", "Category"}
    for key, val in item.items():
        if key not in shown and val not in (None, "", "null"):
            lines.append(f"{key}: {val}")
    return "\n".join(lines)


def _format_properties_json(data: dict | list, municipality_id: str) -> str:
    """
    Format the CAI properties JSON response as a readable text block for Claude.

    The /properties/{municipalityId}?f=json endpoint returns either a single
    property dict or a list of property records.  Each record may contain nested
    sections (e.g. "Building", "Land", "Sales") as well as top-level fields.
    All non-empty fields are emitted so Claude can extract whatever COPE data
    is present regardless of the exact schema variation.
    """
    # Normalise to a list of records
    records = data if isinstance(data, list) else [data]
    if not records:
        return ""

    # Use the first record (parcel-number query should return exactly one)
    record = records[0]

    lines = [f"PROPERTY CARD — {municipality_id} (CAI CAMA)"]

    def _emit(obj: dict | list, prefix: str = "") -> None:
        """Recursively emit key: value lines, flattening nested dicts/lists."""
        if isinstance(obj, dict):
            for k, v in obj.items():
                label = f"{prefix}{k}" if not prefix else f"{prefix}.{k}"
                if isinstance(v, (dict, list)):
                    _emit(v, label)
                elif v not in (None, "", "null", 0) or isinstance(v, bool):
                    lines.append(f"{label}: {v}")
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                _emit(item, f"{prefix}[{i}]" if prefix else f"[{i}]")

    _emit(record)
    return "\n".join(lines)

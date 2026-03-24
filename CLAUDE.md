# COPE Property Intelligence

**Last updated: 2026-03-23**

## What This Project Does

COPE Property Intelligence is an insurance underwriting tool that retrieves
Construction, Occupancy, Protection, and Exposure (COPE) data for any physical
property address by searching publicly available municipal property card databases.

A user enters a street address. The app:
1. Geocodes it via Google Maps to extract the municipality, state, and county
2. Looks up the municipality in the database; if not found, **auto-discovers** it by probing
   known platform URL patterns and registers it automatically
3. Looks up the platform implementation from `PLATFORM_REGISTRY` by `search_type`
4. Directly HTTP-scrapes the assessor's property card site (no browser automation)
5. Passes the raw property card text to Claude (claude-sonnet-4-5) for structured extraction
6. Returns a structured COPE report and caches it for 30 days per user

Supported platforms: **VGSI** (Maine municipalities), **qPublic / Schneider Corp**
(GA, SC, FL counties), **O'Donnell & Associates** (37 Maine municipalities — ownership
and valuation data only), **Patriot Properties WebPro** (New England municipalities —
full COPE data), **Tyler Technologies iasWorld** (hundreds of US municipalities —
full COPE data), **Harris Computer Systems RE Online** (rural New England
municipalities — full COPE data), and **AxisGIS** (CAI Technologies — Maine
municipalities using Vision, Avitar, Munis, or CAI Trio CAMA). New platforms are added
by implementing `PropertyPlatform` and registering the class in `PLATFORM_REGISTRY` —
no changes to the dispatcher or router.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11, FastAPI, Uvicorn |
| Database | MongoDB Atlas (motor async driver) |
| Auth | Supabase — email/password + magic link, JWT verified server-side via JWKS (ES256) |
| Frontend | Single HTML file, vanilla JS/CSS, served by FastAPI |
| Address validation | Google Maps Geocoding API (server-side only; Places Autocomplete disabled) |
| AI extraction | Anthropic claude-sonnet-4-5 — structured JSON extraction from scraped HTML text |
| HTTP scraping | httpx async client — platform-specific flows via Strategy + Registry pattern |
| HTML parsing | lxml — used by qPublic platform for form field and result link extraction |
| Container | Docker |
| Runtime | GCP Cloud Run |
| Secrets (prod) | GCP Secret Manager via --set-secrets |
| Secrets (local) | .env file loaded by python-dotenv |

---

## Repository Layout

```
cope-iq/
├── CLAUDE.md                  ← you are here
├── .env                       ← local secrets, never committed
├── .env.example               ← safe template, committed
├── .gitignore
├── Dockerfile
├── cloudbuild.yaml            ← GCP Cloud Build → Cloud Run deploy
├── requirements.txt
├── start.bat                  ← activates venv + starts uvicorn (Windows/PowerShell)
├── validate_phase6.py         ← end-to-end validation script (no server/auth needed)
├── README.md
├── main.py                    ← FastAPI app, lifespan hooks, router mounts
├── config.py                  ← pydantic-settings, loads .env
├── db/mongo.py                ← motor client, collection helpers, index + seed logic
├── auth/supabase.py           ← PyJWKClient-based ES256 JWT verify dependency
├── routers/
│   ├── municipalities.py      ← GET/POST municipality registry
│   ├── properties.py          ← POST /cope/search, GET /properties/history, DELETE
│   └── admin.py               ← health check, seed trigger (admin-only)
├── scraper/
│   ├── cope_scraper.py        ← dispatcher: registry lookup, shared client, Claude call
│   ├── discovery.py           ← auto-discovery: probe platforms, register unknown municipalities
│   ├── qpublic_browser.py     ← headless Playwright browser: navigates qPublic state/county UI
│   ├── prompts.py             ← SYSTEM_PROMPT + extraction_prompt() template
│   └── platforms/
│       ├── __init__.py        ← PLATFORM_REGISTRY dict
│       ├── base.py            ← PropertyPlatform abstract base class
│       ├── vgsi.py            ← VGSIPlatform (Maine municipalities)
│       ├── qpublic.py         ← QPublicPlatform (Schneider Corp / GA, SC, FL)
│       ├── odonnell.py        ← OdonnellPlatform (O'Donnell & Assoc. / 37 ME towns)
│       ├── patriot.py         ← PatriotPlatform (Patriot Properties WebPro / New England)
│       ├── tyler.py           ← TylerPlatform (Tyler Technologies iasWorld / nationwide)
│       ├── harris.py          ← HarrisPlatform (Harris Computer Systems RE Online / rural NE)
│       └── axisgis.py         ← AxisGISPlatform (CAI Technologies axisgis.com / ME municipalities)
├── models/
│   ├── municipality.py        ← Pydantic municipality doc model (incl. platform_config)
│   └── property.py            ← Pydantic COPE result doc model
└── frontend/index.html        ← full UI: auth, search, results panel, history, DB panel
```

---

## Shell / Terminal

Always use **PowerShell** for terminal commands on this project. Do not use bash syntax.
Use `.\start.bat` to start the dev server.

---

## Local Development Setup

### Prerequisites
- Python 3.11+
- A MongoDB Atlas cluster (free tier M0 is fine for dev)
- A Supabase project (free tier)
- Google Maps API key with Geocoding API enabled
- An Anthropic API key

### Steps

```powershell
git clone <repo-url>
cd cope-iq
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium   # download Chromium for headless qPublic browser
copy .env.example .env        # then fill in your real keys
.\start.bat
```

Open http://localhost:8000 — the frontend is served by FastAPI.

### Running Without All Keys

The app degrades gracefully:
- Missing `GOOGLE_MAPS_API_KEY` → geocoding falls back to comma-split heuristic; no hard failure
- Missing `ANTHROPIC_API_KEY` → scraper returns `{"error": "AI service not configured"}`; all other routes work
- Missing Supabase keys → auth middleware raises 500 on protected routes; public routes still work

### Validation Script

To smoke-test the scraper layer without a running server or Supabase auth:

```powershell
venv\Scripts\python validate_phase6.py
```

Runs 4 test groups (15 checks): registry structure, unsupported platform error path,
VGSI regression against Rockland ME, and qPublic connectivity check.

---

## MongoDB Collections

### `municipalities`
Registry of supported property card databases. Seeded automatically on first run.
Key fields: `state`, `municipality` (lowercase normalized), `municipality_display`,
`search_url`, `search_type`, `platform_config`, `active`.

The `platform_config` dict carries all platform-specific parameters (e.g. `app_id`
for qPublic). Never add new top-level fields to this collection for platform-specific
state — it all goes in `platform_config`.

### `properties`
Cached COPE search results. One document per unique (address, user) lookup.
Key fields: all COPE sub-objects (`construction`, `occupancy`, `protection`, `exposure`,
`valuation`, `owner`, `sale`), plus `photo_url`, `sketch_url`, `mblu`, `parcel_id`,
`completeness_pct`, `cache_expires_at`, `searched_by`, `municipality_display`, `raw_json`.

---

## Authentication Model

- Supabase handles identity. Users sign up/in via the frontend using the Supabase JS SDK.
- The frontend passes the Supabase JWT as `Authorization: Bearer <token>` on every API call.
- FastAPI verifies the JWT using **PyJWKClient** fetching JWKS from Supabase's
  `{SUPABASE_URL}/auth/v1/.well-known/jwks.json`. Newer Supabase projects sign tokens
  with ES256 (asymmetric), not HS256 — the JWKS approach handles both.
- Admin actions (adding municipalities) require `user.app_metadata.role == "admin"`,
  which must be set manually in the Supabase dashboard or via the service role API.

---

## Scraper Architecture — Strategy + Registry Pattern

The scraper uses a **Strategy + Registry** pattern so new platforms can be added without
touching the dispatcher or any router.

### Key files

| File | Role |
|------|------|
| `scraper/platforms/base.py` | `PropertyPlatform` ABC — defines the interface all platforms must satisfy |
| `scraper/platforms/vgsi.py` | `VGSIPlatform` — VGSI two-step HTTP scraper |
| `scraper/platforms/qpublic.py` | `QPublicPlatform` — Schneider Corp GET→POST→parse flow |
| `scraper/platforms/odonnell.py` | `OdonnellPlatform` — O'Donnell JSON dataset extraction |
| `scraper/platforms/patriot.py` | `PatriotPlatform` — Patriot WebPro 3-step session flow |
| `scraper/platforms/tyler.py` | `TylerPlatform` — Tyler iasWorld 5-step session flow |
| `scraper/platforms/harris.py` | `HarrisPlatform` — Harris RE Online 3-step form flow |
| `scraper/platforms/__init__.py` | `PLATFORM_REGISTRY` dict mapping `search_type` → platform instance |
| `scraper/cope_scraper.py` | Dispatcher — looks up platform, owns `httpx.AsyncClient`, calls Claude |

### PropertyPlatform interface (`base.py`)

```python
class PropertyPlatform(ABC):
    async def fetch(base_url, address, street, platform_config, client) -> (pid, matched_address, html, parcel_url)
    def extract_photo_url(html, base_url) -> str | None
    def extract_sketch_url(html, base_url) -> str | None
    def extraction_hints() -> str   # optional Claude prompt injection; default ""
```

### Dispatcher responsibilities (`cope_scraper.py`)

- Creates the shared `httpx.AsyncClient(timeout=15.0, verify=False)` — **not** the platform
- Calls `platform.fetch()`, `extract_photo_url()`, `extract_sketch_url()`
- Appends `platform.extraction_hints()` to `SYSTEM_PROMPT` when non-empty
- Runs `_html_to_text()` to strip HTML before passing to Claude
- All error handling (ValueError → error dict, HTTPError → error dict) lives here

### Adding a new platform

1. Create `scraper/platforms/<name>.py` implementing `PropertyPlatform`
2. Add `"<search_type>": <ClassName>()` to `PLATFORM_REGISTRY` in `scraper/platforms/__init__.py`
3. Add seed municipalities to `SEED_MUNICIPALITIES` in `db/mongo.py` with `"search_type": "<name>"`
   and any platform-specific keys inside `"platform_config": {}`
4. Optionally add a `_probe_<name>()` coroutine to `scraper/discovery.py` and call it in
   `discover_and_register()` so unseen municipalities on that platform are auto-registered
5. No changes needed to `cope_scraper.py`, `routers/`, or any model

---

## VGSI Platform

VGSI (Vision Government Solutions) is an ASP.NET WebForms SPA used by many New England
municipalities. Two HTTP calls:

1. **Address autocomplete** — `POST {base_url}/async.asmx/GetDataAddress`
   Body: `{"inVal": "<street only>", "src": "i_address"}`
   Returns: `{"d": [{"id": "<pid>", "value": "<matched address>"}, ...]}`

2. **Property card** — `GET {base_url}/Parcel.aspx?Pid=<pid>`

Street query is stripped of type suffixes (Dr, Rd, St, etc.) before submission because
VGSI often uses non-standard abbreviations (e.g. "EXT" instead of "Dr").

Photo URLs (`images.vgsi.com`) and sketch URLs (`ParcelSketch.ashx`) are extracted from
the raw HTML before tag-stripping.

SSL `verify=False` is set on the shared client due to Windows cert chain issues with
VGSI hosts. This is set in the dispatcher, not in `VGSIPlatform` itself.

**Windows / OpenSSL 3.0 TLS 1.3 fix (`main.py`):** Python 3.11 on Windows ships OpenSSL 3.0
whose TLS 1.3 handshake is incompatible with some MongoDB Atlas shard configurations. The fix
patches `get_ssl_context()` to append `OP_NO_TLSv1_3`, forcing TLS 1.2. Critically, **both**
`pymongo.ssl_support.get_ssl_context` and `pymongo.client_options.get_ssl_context` must be
patched — `client_options` does `from pymongo.ssl_support import get_ssl_context` at import
time, creating a local binding that is unaffected by patching `ssl_support` alone.

---

## qPublic Platform

Schneider Corp / qPublic (`qpublic.schneidercorp.com`) is used by hundreds of county
assessors across the South and Midwest. Each municipality's site is identified by an
`app_id` stored in `platform_config`.

Four-step Playwright flow (browser automation):

1. **GET** search form via `headless=False` Chromium (Cloudflare blocks headless)
2. **Dismiss T&C modal** — qPublic shows a Terms modal on first visit; dismiss it to unblock clicks
3. **Fill address + click search** — address input: `input.tt-upm-address-search`; button: `a[searchintent='Address']`
4. **Wait for results** (`PageTypeID=3`) or direct detail redirect (`PageTypeID=4` / `KeyValue=`)
5. **GET property detail page** and return `(pid, matched_address, html, parcel_url)`

**Quirks handled:**
- Search form uses Twitter Typeahead inputs and `<a>` submit buttons — not standard `<input type=submit>`
- The `__doPostBack` form POST to the search URL changes the page to `PageTypeID=3` (results) or directly to detail
- Results table has columns: [select, icon, Account#, Parcel#, Owner, **Property Address**, City, Map]
  — matched_address is extracted from column index 5 of the first result row
- `extract_photo_url()` checks `/photos/`, `/images/`, `/parcel/` paths, then `alt="photo"`, then any `.jpg`/`.png` not matching UI asset patterns
- `extraction_hints()` injects qPublic-specific field label mappings into the Claude prompt

**Cloudflare / CDN:** Schneider Corp uses Cloudflare Bot Management with **interactive Turnstile**
on POST/XHR requests. Headless Chromium triggers the challenge; non-headless (`headless=False`)
passes because headed Chrome has a genuine browser fingerprint. All qPublic browser automation
uses `headless=False`. Local dev (Windows): works natively. Docker (Cloud Run): Xvfb virtual
display required — the Dockerfile installs `xvfb` and starts it as `Xvfb :99` before the server.

**Required `platform_config` keys:**
- `app_id` (str) — the `App=` parameter from the site URL, e.g. `"BryanCountyGA"`

**Optional `platform_config` keys:**
- `layer_id` (str) — defaults to `"Parcels"`
- `search_page_url` (str) — full URL to the county's address search form, containing
  numeric IDs (`AppID=`, `LayerID=`, `PageTypeID=2`, `PageID=`). Populated automatically
  by `scraper/qpublic_browser.py` during discovery or via `POST /api/admin/enrich-qpublic`.
  Without it, the scraper falls back to `Application.aspx?App={app_id}&PageTypeID=2`.

---

## O'Donnell & Associates Platform

John E. O'Donnell & Associates (`jeodonnell.com/cama/`) serves 37+ Maine municipalities
through a WordPress site running the custom `jeo-cama` plugin.

**Data availability:** Ownership and financial assessment data only. Construction details
(year built, square footage, construction type, stories, roof, foundation, heating) are
**not published online** — those COPE fields will always be null for O'Donnell properties.
Expected completeness: ~30–40%.

**Available fields:** Parcel ID (Map-Lot format), owner name, street address, assessed land
value, assessed building value, last sale price, last sale date.

**Scraping flow (single HTTP request — no browser automation):**

1. `GET https://jeodonnell.com/cama/{slug}/`
2. Extract `script_vars.dataSet` JSON array from `<script id="jeo-cama-js-extra">` inline block
3. Match parcel by normalised `StreetNumber + StreetName`; partial fallback on house number + street prefix
4. Build synthetic HTML property card table for Claude extraction
5. Return `(Key, matched_address, html, parcel_url)`

**Dataset structure:** Each record in `dataSet` contains:
`Key` (Map-Lot), `OwnerName1`, `StreetNumber`, `StreetName`, `LandValue`, `BuildingValue`,
`BoughtFor`, `OwnerSince`, `PrivateData` (skip when `"1"`).

**Required `platform_config` keys:**
- `slug` (str) — URL path segment, e.g. `"turner"`, `"livermore-falls"`

**Individual parcel URLs** (`/cama/{slug}/{Key}/`) are client-side JavaScript routing only —
the server returns the full municipality page for every sub-path. Scraping does not use them.

**Auto-discovery probe:** `_probe_odonnell()` in `scraper/discovery.py` — only probes for
`state == "ME"`; slug derived by replacing spaces/punctuation with hyphens.

---

## Patriot Properties Platform

Patriot Properties WebPro (`*.patriotproperties.com`) is a Classic ASP frameset application
used by hundreds of New England municipalities (ME, NH, MA, RI, CT).

**Data availability:** Full COPE data — year built, exterior material, roof cover, rooms,
bedrooms, baths, land area, land/building/total values, and sale history. Photo
(`showimage.asp`) and building sketch (`showsketch.asp`) are session-relative URLs.

**Scraping flow (3 HTTP requests, session cookies required):**

1. **POST** `SearchResults.asp` — search by house number + first word of street name
2. **GET** `Summary.asp?AccountNumber={id}` — load parcel into server-side ASP session
3. **GET** `summary-bottom.asp` — retrieve the full property card HTML

**Street name search quirk:** Patriot stores abbreviated street types ("OAK ST" not "OAK
STREET"). The server uses "Starts With" comparison, so sending "Oak Street" fails to match
"OAK ST". Fix: only the first word of the street name is sent to the server; `_street_match()`
handles type-suffix matching on the client side using word-level prefix comparison (e.g.
"street" matches "st", "lane" matches "ln").

**Address cell format:** SearchResults.asp TD[1] contains house number + street name
separated by `\xa0` (non-breaking space) — e.g. `1\xa0OAK ST`. `split(None, 1)` handles
this correctly.

**Photo and sketch detection:**
- `extract_photo_url()`: returns `{base_url}/showimage.asp` if `showimage.asp` appears in HTML
  and `nopic.jpg` sentinel is absent.
- `extract_sketch_url()`: returns `{base_url}/showsketch.asp` if `showsketch.asp` appears in HTML
  and `nosketch.jpg` sentinel is absent.
- Both URLs are valid only while the httpx client's ASP session cookie remains alive.

**Required `platform_config` keys:** none — `base_url` (the `search_url` field) carries
all state; e.g. `https://auburnmaine.patriotproperties.com`.

**Slug variants tried by auto-discovery probe:**
1. `{locality_lower_nospaces}` — e.g. "auburn" → `auburn.patriotproperties.com`
2. `{locality_lower_nospaces}{state_lower}` — e.g. "auburnme" → `auburnme.patriotproperties.com`
3. `{locality_lower_nospaces}maine` — e.g. "auburnmaine" → `auburnmaine.patriotproperties.com`

Note: Auburn ME uses the unusual `auburnmaine` slug (not `auburnme`), which redirects to a
marketing page — this is handled by trying the `{name}maine` variant for ME.

**Auto-discovery probe:** `_probe_patriot()` in `scraper/discovery.py` — tries slug variants
in order, confirms hit by checking for `SearchStreetName` form field marker.

---

## Tyler Technologies Platform

Tyler Technologies iasWorld Public Access (`*.tylertech.com`, `*.tylerhost.net`, and custom
domains) is used by hundreds of municipalities across the US (ME, OH, VA, LA, and more).

**Data availability:** Full COPE data — year built, building style, stories, heating system,
fuel type, rooms, bedrooms, baths, living area, land/building/total values, and sale history.

**Scraping flow (5 HTTP requests, ASP.NET session cookies required):**

1. **GET** `search/commonsearch.aspx?mode=address` — may redirect to Disclaimer.aspx
2. **POST** Disclaimer.aspx with `btAgree=Agree` — accepts ToS, sets session cookie
   (skipped if already accepted in the current session)
3. **POST** `search/commonsearch.aspx?mode=address` — search by house number + first word
   of street name
4a. **302** → single result → server redirects to `Datalets/Datalet.aspx?sIndex=N&idx=M`
4b. **200** → results list → parse `TR[onclick]` rows to find match, extract detail URL
5. **GET** 4 datalet tabs (profileall, res_combined, valuesall, sales) — concatenated into
   one HTML block separated by `<!-- DATALET BREAK -->` comments

**Results list structure:** Each `TR[onclick]` row has onclick handler:
`selectSearchRow('../Datalets/Datalet.aspx?sIndex=0&idx=N')`.
Columns: `[PARID, Map/Lot, Address, Owner, ...]` — address is at column index 2.

**Street name search quirk:** Same as Patriot — Tyler uses "Starts With" server-side
matching. Only the first word of the street name is sent; `_street_match()` handles
type-suffix matching on the client side.

**Disclaimer handling:** Tyler sites show a Terms of Use disclaimer on first visit.
Detected by presence of `btAgree` in the page HTML. Accepted by POSTing `btAgree=Agree`
along with all hidden form fields (`__VIEWSTATE`, `__VIEWSTATEGENERATOR`,
`__EVENTVALIDATION`, `hdURL`, `action`).

**Datalet tabs:**
- `profileall` — Parcel ID, Map/Lot, Property Location, Property Class, Land Area, Owner
- `res_combined` — Year Built, Style, Stories, Heat System, Fuel Type, Rooms, Baths,
  Living Area, Basement, Attic, Fireplaces
- `valuesall` — Current Land, Current Building, Current Assessed Total
- `sales` — Deed Date, Sale Price, Grantor (seller)

**Required `platform_config` keys:** none — `base_url` (the `search_url` field) carries
all state; e.g. `https://lewistonmaine.tylertech.com`.

**Slug variants tried by auto-discovery probe:**
1. `{locality_lower_nospaces}{state_lower}` — e.g. "lewistonme" → `lewistonme.tylertech.com`
2. `{locality_lower_nospaces}` — e.g. "lewiston" → `lewiston.tylertech.com`
3. `{locality_lower_nospaces}maine` — ME only (e.g. "lewistonmaine") — Lewiston ME uses this

**Auto-discovery probe:** `_probe_tyler()` in `scraper/discovery.py` — confirms hit by
checking for `frmMain` form marker or `btAgree` disclaimer marker.

---

## AxisGIS Platform

AxisGIS (CAI Technologies, `axisgis.com`) is used by many Maine municipalities. Each
municipality has an alphanumeric `municipality_id` (e.g. `"CamdenME"`, `"WarrenME"`).

**Data availability:** Full COPE data when a CAMA vendor PDF is available (Vision,
Avitar, Munis). CAI Trio municipalities serve a generated PDF via `axisreports.axisgis.com`.

**Scraping flow:**

1. **GET** `https://api.axisgis.com/node/axisapi/search/{municipalityId}?q={query}` — address search
2. **Step 0 (optional)** — if `vgsi_url` is in `platform_config`, try `VGSIPlatform.fetch()` first;
   return immediately on success, fall through on failure
3. **Step 2a** — probe CAMA vendor PDF: `GET /document-view/{municipalityId}?path=Docs/Batch/{vendor}_Property_Card/{pid}.pdf`.
   Tries vendors in order: Vision → Avitar → Munis → Trio. Trio uses the numeric account
   portion of the PID only (e.g. `"2390"` from `"2390-1"`).
4. **Step 2b** — if no vendor PDF found, POST to `https://axisreports.axisgis.com/` with JSON body
   (CAI Trio CAMA). Response is raw PDF bytes despite `content-encoding: base64` header.
   Required headers: `Content-Type: text/plain;charset=UTF-8`, `Referer: https://www.axisgis.com/`
   (root, not municipality page). Payload: `{format, path, rpDatabaseName, rpDisclaimer, rpSubjectCamaFullNum}`.
5. **Step 2d** — fallback: GET CAI properties JSON endpoint; last resort: format search result attributes.

**Image extraction from CAMA PDFs (pymupdf / fitz):**

pypdf cannot reach JPEG images embedded inside PDF Form XObjects. fitz (`pymupdf`) scans
the full xref table for `/Image` objects regardless of nesting depth.

Image classification pipeline (three stages):

1. **Logo filter (proximity)** — `_find_logo_xrefs()` scans each page with `page.get_images()`
   and `page.get_image_rects()`. Images within 72 pt (~1 inch) of civic identity text
   (`"Town of"`, `"City of"`, `"seal"`, `"crest"`, etc.) are tagged as logos and dropped.
   Handles municipality seals whose text is present as PDF text elements. Seals with fully
   rasterized text (no PDF text elements) fall through to stage 3.

2. **Dimension filter** — `_is_logo(w, h)`: drops wide banners (aspect > 3:1) and tiny
   icons (area < 5 000 px²). Near-square filtering was intentionally removed — building
   sketches can legitimately be near-square.

3. **Pixel content classification** — `_classify_pixels()` samples every 4th pixel and
   returns `(white_ratio, midtone_ratio)`:
   - `_is_sketch_image()`: white_ratio > 0.85 → line drawing → sketch candidate
   - `_looks_like_photo()`: midtone_ratio ≥ 0.25 → smooth tonal gradients → photo candidate
   - Neither (bimodal: near-black + near-white, few mid-tones) → municipal seal/crest → discarded.
     This catches seals with rasterized text that the proximity filter missed.

   Largest sketch candidate → sketch slot. Largest photo candidate with area ≥ 40 000 px² →
   photo slot. If content analysis yields nothing, falls back to size-based ordering.

**RGBA/CMYK → RGB conversion:** `_to_rgb()` — fitz `Pixmap(cs, src, bool)` 3-arg constructor
does not exist in pymupdf 1.24. Alpha stripping is done manually by dropping the alpha byte from
each pixel in the raw samples buffer, then reconstructing with `Pixmap(cs, w, h, samples, False)`.

**`vgsi_url` platform_config key:** If a municipality is served by both AxisGIS and VGSI
(e.g. Camden ME uses AxisGIS as its GIS map but Vision CAMA is accessible via VGSI),
set `vgsi_url` in `platform_config`. `AxisGISPlatform.fetch()` will try VGSI first and only
fall through to the AxisGIS PDF path on error or no-match. Camden ME is currently the only
seeded municipality with this dual-platform configuration.

**`next.axisgis.com`:** Some municipalities use this alternate subdomain instead of
`www.axisgis.com` (e.g. Westport Island ME, East Machias ME). The `municipality_id` in
`platform_config` and the `search_url` must match.

**Required `platform_config` keys:**
- `municipality_id` (str) — AxisGIS municipality ID, e.g. `"CamdenME"`, `"WarrenME"`

**Optional `platform_config` keys:**
- `cama_vendor` (str) — skip auto-probe and use this vendor directly: `"Vision"`, `"Avitar"`,
  `"Munis"`, or `"Trio"`. Omit to auto-probe all vendors in order.
- `vgsi_url` (str) — VGSI base URL if municipality also has a VGSI endpoint. VGSI is
  tried first; AxisGIS PDF is the fallback.

---

## Harris Computer Systems Platform

Harris Computer Systems RE Online (`reonline.harriscomputer.com`) is used by rural New
England municipalities. Each municipality has an opaque numeric `clientid` embedded in
the search URL (e.g. `?clientid=1007` for Readfield ME).

**Data availability:** Full COPE data — year built, building style, rooms, bedrooms,
baths, living area, land/building/taxable values, and sale history. Heating and exterior
are not published. No photos or sketches.

**Scraping flow (3 HTTP requests):**

1. **GET** `research.aspx?clientid={id}` — fetch search form and ASP.NET VIEWSTATE
2. **POST** `research.aspx?clientid={id}` with `txtDetailStreet` = first word of street
   name → results page at `REDetailList.aspx`
3. **GET** `DetailedView.aspx?id={account}` — full property card

**Results table structure** (`REDetailList.aspx`):
Rows identified by `td a[href*="DetailedView"]` in first cell.
Columns: `[View link | Account | Map/Lot | Name | Acres | Land | Building | ST No | Street]`
— ST No (index 7) is the house number; Street (index 8) is the street name.

**clientid registry:** Harris client IDs are opaque integers — not derivable from the
locality name. Known IDs are stored in `_HARRIS_CLIENTS` in `scraper/discovery.py`.
Auto-discovery for unknown municipalities returns None; new municipalities must be
seeded manually with their known clientid in `search_url`.

**Required `platform_config` keys:** none — clientid is embedded in `search_url`.

**Auto-discovery probe:** `_probe_harris()` in `scraper/discovery.py` — looks up the
locality in `_HARRIS_CLIENTS`; returns None for unknown municipalities.

---

## Municipality Auto-Discovery

`scraper/discovery.py` — `discover_and_register(locality, state, county) -> dict | None`

When a municipality is not found in the database, the router calls `discover_and_register()`
before returning an error. It probes each supported platform in order:

1. **VGSI** — GETs `https://gis.vgsi.com/{municipality_nospaces}{state_lower}/` and checks
   the response for VGSI page markers (`"vision government"`, `"vgs_icon"`). The slug is
   built by stripping non-alphanumeric characters from the locality name and appending the
   lowercase state code (e.g. Augusta ME → `augustame`).

2. **O'Donnell** — GETs `https://jeodonnell.com/cama/{slug}/` where slug is the locality
   name lowercased with spaces replaced by hyphens (e.g. "Livermore Falls" → `livermore-falls`).
   Checks for the `jeo-cama-js-extra` script marker. Only probes when `state == "ME"`.

3. **Patriot Properties** — Tries slug variants in order: `{name}`, `{name}{state}`,
   `{name}maine` (ME only). GETs `{slug}.patriotproperties.com/search-middle-ns.asp` and
   checks for the `SearchStreetName` form field marker. Covers ME, NH, MA, RI, CT.

4. **Tyler Technologies** — Tries slug variants: `{name}{state}`, `{name}`,
   `{name}maine` (ME only). GETs `{slug}.tylertech.com/search/commonsearch.aspx?mode=address`
   and checks for `frmMain` marker or `btAgree` disclaimer marker.

5. **Harris Computer Systems** — Looks up locality in `_HARRIS_CLIENTS` dict (pre-seeded
   clientid registry). GETs `reonline.harriscomputer.com/research.aspx?clientid={id}` and
   checks for `Harris RE Online Search` page marker. Returns None for unknown municipalities.

6. **qPublic** — GETs `https://qpublic.schneidercorp.com/Application.aspx?App={county}County{state}`
   and checks for Schneider Corp content. Requires `county` from geocoding. Skipped if county
   is empty. Subject to the same 403 CDN limitation as the scraper itself.

On the first successful probe, the municipality document is inserted into MongoDB with
`added_by: "auto-discovery"` and returned to the router, which continues the search
transparently in the same request. Subsequent searches for that municipality hit the DB directly.

**`_geocode()` now returns `county`** — extracted from Google's `administrative_area_level_2`
component with the " County" suffix stripped (e.g. "Kennebec County" → "Kennebec").

**VGSI marker rationale:** Sub-page markers (`getdataaddress`, `parcel.aspx`) do not appear
on the root landing page. `"vision government"` (from `<title>`) and `"vgs_icon"` (favicon
path) are present on every VGSI municipality's root page.

---

## Seeded Municipalities

### VGSI — Maine
**Androscoggin:** Auburn, Lewiston, Sabattus
**Cumberland:** Baldwin, Brunswick, Casco, Cumberland, Falmouth, Freeport, Gorham, Harpswell, North Yarmouth, Portland, Raymond, Scarborough, South Portland, Standish, Westbrook, Windham, Yarmouth
**Hancock:** Mount Desert
**Kennebec:** Augusta, Gardiner, Monmouth, Waterville, Winslow, Winthrop
**Knox:** Rockland, South Thomaston
**Penobscot:** Bangor, Orono
**Sagadahoc:** Bath, Topsham
**Waldo:** Belfast
**York:** Arundel, Berwick, Biddeford, Eliot, Kennebunk, Kittery, Ogunquit, Saco, Wells, York

Note: Camden (Knox) is seeded as `axisgis` with `vgsi_url` set — VGSI is tried first.

### qPublic — Georgia
Bryan County (`BryanCountyGA`), Haralson County (`HaralsonCountyGA`), Polk County (`PolkCountyGA`)

### qPublic — South Carolina
Spartanburg County (`SpartanburgCountySC`), Lancaster County (`LancasterCountySC`)

### qPublic — Florida
Okaloosa County (`OkaloosaCountyFL`)

### O'Donnell & Associates — Maine
**Androscoggin:** Livermore, Livermore Falls, Mechanic Falls, Minot, Turner, Wales
**Cumberland:** Bridgton, Naples, New Gloucester, Sebago
**Franklin:** Andover, Carthage, Jay, Temple, Weld, Wilton
**Lincoln:** Alna, Boothbay, Edgecomb
**Oxford:** Canton, Dixfield, Gilead, Greenwood, Hanover, Hartford, Hebron, Otisfield, Stow, Sumner, Sweden, Woodstock
**York:** Acton, Alfred, Lebanon, Limerick, Shapleigh

### Patriot Properties WebPro — Maine
**Androscoggin:** Auburn (`auburnmaine.patriotproperties.com`)
**Knox:** Rockport (`rockport.patriotproperties.com`)

### Tyler Technologies iasWorld — Maine
**Androscoggin:** Lewiston (`lewistonmaine.tylertech.com`)

### Harris Computer Systems RE Online — Maine
**Kennebec:** Readfield (`clientid=1007`)

### AxisGIS (CAI Technologies) — Maine
**Knox:** Camden (`vgsi_url` set; VGSI tried first), Union, Warren
**Kennebec:** China
**Lincoln:** Newcastle, Westport Island (`next.axisgis.com`), Wiscasset
**Oxford:** Brownfield, Fryeburg, Oxford, Porter
**Penobscot:** Brewer, Hampden, Lincoln, Old Town
**Somerset:** Fairfield
**Washington:** Calais, East Machias (`next.axisgis.com`)
**York:** Kennebunkport, Sanford, South Berwick, Waterboro

To re-seed a dev environment: drop the `municipalities` collection in Atlas, restart the
server, and hit `POST /admin/seed`.

---

## Current Development Goals

### Phase 1 — MVP (complete)
- [x] Project scaffold, MongoDB schema, seed data
- [x] Supabase auth flow (email + magic link)
- [x] Google Maps geocoding (server-side; Places Autocomplete disabled)
- [x] Municipality lookup with normalization
- [x] VGSI direct HTTP scraper + Claude extraction
- [x] Full COPE schema: construction, occupancy, valuation, owner, sale, protection, exposure
- [x] Property photo + building sketch image capture and display
- [x] 30-day result caching per user
- [x] Frontend: search, results panel (with images), history (expandable rows + image overlays), municipality DB view
- [x] JSON + CSV export
- [x] Dockerfile + cloudbuild.yaml for GCP Cloud Run

### Phase 2 — Multi-Platform Architecture (complete)
- [x] `PropertyPlatform` abstract base class (`scraper/platforms/base.py`)
- [x] `VGSIPlatform` extracted from dispatcher (`scraper/platforms/vgsi.py`)
- [x] `QPublicPlatform` for Schneider Corp sites (`scraper/platforms/qpublic.py`)
- [x] `PLATFORM_REGISTRY` dict — dispatcher decoupled from platform logic
- [x] `platform_config` field on municipality model + seed documents
- [x] 6 qPublic municipalities seeded (GA, SC, FL)
- [x] End-to-end validation script (`validate_phase6.py`)

### Phase 3 — Coverage Expansion (in progress)
- [x] Municipality auto-discovery (`scraper/discovery.py`) — unknown municipalities probed and registered on first search
- [x] `_geocode()` returns county for qPublic discovery
- [x] Augusta, ME added to seed data
- [x] Playwright browser for qPublic (`scraper/qpublic_browser.py`) — bypasses Cloudflare, navigates state/county UI, captures Property Search URL with numeric IDs
- [x] `POST /api/admin/enrich-qpublic` — backfills `search_page_url` for existing qPublic municipalities
- [x] qPublic property scraping via `scrape_property_search()` — non-headless Chromium bypasses Cloudflare Turnstile; results extracted from PageTypeID=3 table; Dockerfile updated with Xvfb for Cloud Run
- [x] O'Donnell & Associates platform (`scraper/platforms/odonnell.py`) — JSON dataset extraction from embedded `script_vars.dataSet`; 36 ME municipalities seeded; `_probe_odonnell()` added to auto-discovery
- [x] VGSI ME seed expansion — 34 additional municipalities seeded across 9 counties (45 total VGSI ME seeds)
- [x] Patriot Properties platform (`scraper/platforms/patriot.py`) — 3-step ASP session flow; street type abbreviation handling; Auburn ME + Rockport ME seeded; `_probe_patriot()` added to auto-discovery
- [x] Tyler Technologies iasWorld platform (`scraper/platforms/tyler.py`) — 5-step disclaimer+search flow; multi-tab datalet fetching (profileall, res_combined, valuesall, sales); Lewiston ME seeded; `_probe_tyler()` added to auto-discovery
- [x] Harris Computer Systems RE Online platform (`scraper/platforms/harris.py`) — 3-step form flow; clientid-based municipality identification; Readfield ME seeded; `_probe_harris()` added to auto-discovery (pre-seeded clientid registry)
- [x] AxisGIS platform (`scraper/platforms/axisgis.py`) — vendor PDF probe (Vision/Avitar/Munis/Trio), axisreports POST for CAI Trio, pixel-content image classification (sketch vs photo), proximity logo detection; 21 ME municipalities seeded across 8 counties
- [x] AxisGIS `vgsi_url` fallback — Camden ME (and any municipality with both VGSI and AxisGIS endpoints) tries VGSI first for richer structured HTML
- [ ] Bulk municipality import tool (CSV upload in admin panel)
- [ ] Expand VGSI seed data to NH, VT, MA municipalities
- [ ] Expand qPublic seed data to additional GA, SC, FL, LA counties
- [ ] Expand Tyler seed data to additional ME municipalities and other states

### Phase 4 — Protection & Exposure Enrichment
- [ ] Fire station distance via NFPA / ISO FireLine secondary lookup
- [ ] Flood zone via FEMA NFHL API (using geocoded lat/lng)
- [ ] Protection class (ISO) lookup integration
- [ ] Map view of property location using Google Maps embed

### Phase 5 — Enterprise
- [ ] Team/org accounts with shared search history
- [ ] Batch address processing (CSV upload → bulk COPE export)
- [ ] PDF report generation per property
- [ ] Webhook for completed searches
- [ ] Rate limiting and usage metering per user

---

## Key Conventions

- All COPE sub-object values are stored as **strings** (not typed), since assessor data
  is inconsistently formatted across municipalities. Consumers should parse as needed.
- Null fields are stored as `null` in MongoDB and rendered as `—` in the UI.
- `municipality` field in the DB is always lowercase with punctuation stripped.
  Matching normalizes the user's input the same way via `_normalize_muni()`.
- `municipality_display` (e.g. "Rockland, ME") is stored directly on each property
  document at save time so history queries don't need to join the municipalities collection.
- The `raw_json` field on property documents stores the full stringified scraper result
  for debugging. It is excluded from history list queries (`{"raw_json": 0}`) for efficiency.
- Image URLs in the history UI are stored in a `_historyData[]` JS array and referenced
  by index in onclick handlers — never embedded directly as strings in HTML attributes,
  to avoid quoting conflicts with URL characters.
- The `platform_config` dict is the extension point for all platform-specific state.
  Never add new top-level fields to the municipality document for a single platform's needs.
- The `httpx.AsyncClient` (with `verify=False` and `timeout=15.0`) is owned by the
  dispatcher in `cope_scraper.py` and injected into platform `fetch()` calls. Do not
  create clients inside platform classes.
- Never commit `.env`. All production secrets live in GCP Secret Manager.

# COPE Property Intelligence

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

Supported platforms: **VGSI** (Maine municipalities) and **qPublic / Schneider Corp**
(GA, SC, FL counties). New platforms are added by implementing `PropertyPlatform` and
registering the class in `PLATFORM_REGISTRY` — no changes to the dispatcher or router.

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
│   ├── prompts.py             ← SYSTEM_PROMPT + extraction_prompt() template
│   └── platforms/
│       ├── __init__.py        ← PLATFORM_REGISTRY dict
│       ├── base.py            ← PropertyPlatform abstract base class
│       ├── vgsi.py            ← VGSIPlatform (Maine municipalities)
│       └── qpublic.py         ← QPublicPlatform (Schneider Corp / GA, SC, FL)
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
copy .env.example .env   # then fill in your real keys
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

Four-step flow:

1. **GET** search form → capture ASP.NET hidden tokens (`__VIEWSTATE`, `__EVENTVALIDATION`, etc.)
2. **POST** form with street address (field name discovered dynamically via CSS selector on `#SearchControl1`)
3. **Parse results** for first `<a href*=PageType=Detail>` link, or detect single-result redirect
4. **GET** property detail page

**Quirks handled:**
- Chunked `__VIEWSTATE_0`, `__VIEWSTATE_1`, … fields are detected and concatenated
- If the POST response URL already contains `PageType=Detail`, the results-parsing step is skipped
- `extract_photo_url()` checks `/photos/`, `/images/`, `/parcel/` paths, then `alt="photo"`, then any `.jpg`/`.png` not matching UI asset patterns
- `extraction_hints()` injects qPublic-specific field label mappings into the Claude prompt

**Known limitation:** Schneider Corp's CDN returns 403 for non-browser User-Agents on
the search form endpoint. Full end-to-end requires either a session cookie warm-up or
a less-restricted network path. Flagged as a TODO for a future PR.

**Required `platform_config` keys:**
- `app_id` (str) — the `App=` parameter from the site URL, e.g. `"BryanCountyGA"`
- `layer_id` (str, optional) — defaults to `"Parcels"`

---

## Municipality Auto-Discovery

`scraper/discovery.py` — `discover_and_register(locality, state, county) -> dict | None`

When a municipality is not found in the database, the router calls `discover_and_register()`
before returning an error. It probes each supported platform in order:

1. **VGSI** — GETs `https://gis.vgsi.com/{municipality_nospaces}{state_lower}/` and checks
   the response for VGSI page markers (`"vision government"`, `"vgs_icon"`). The slug is
   built by stripping non-alphanumeric characters from the locality name and appending the
   lowercase state code (e.g. Augusta ME → `augustame`).

2. **qPublic** — GETs `https://qpublic.schneidercorp.com/Application.aspx?App={county}County{state}`
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
Rockland, Camden, Belfast, Portland, Bangor, Biddeford, Saco, Auburn, Lewiston, Bath, Augusta

### qPublic — Georgia
Bryan County (`BryanCountyGA`), Haralson County (`HaralsonCountyGA`), Polk County (`PolkCountyGA`)

### qPublic — South Carolina
Spartanburg County (`SpartanburgCountySC`), Lancaster County (`LancasterCountySC`)

### qPublic — Florida
Okaloosa County (`OkaloosaCountyFL`)

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
- [ ] Resolve qPublic 403 (session cookie warm-up or User-Agent rotation)
- [ ] Add Patriot Properties scraper strategy (`search_type: patriot`)
- [ ] Bulk municipality import tool (CSV upload in admin panel)
- [ ] Expand VGSI seed data to NH, VT, MA municipalities
- [ ] Expand qPublic seed data to additional GA, SC, FL, LA counties

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

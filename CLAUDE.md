# COPE Property Intelligence

## What This Project Does

COPE Property Intelligence is an insurance underwriting tool that retrieves
Construction, Occupancy, Protection, and Exposure (COPE) data for any physical
property address by searching publicly available municipal property card databases.

A user enters a street address. The app:
1. Geocodes it via Google Maps to extract the municipality and state
2. Confirms that municipality is in our supported database
3. Directly HTTP-scrapes the assessor's VGSI property card site (no browser automation)
4. Passes the raw property card text to Claude (claude-sonnet-4-5) for structured extraction
5. Returns a structured COPE report and caches it for 30 days per user

This is an early-stage product. The initial dataset covers Maine municipalities
served by the VGSI GIS platform. Coverage will expand to other states and
assessor platforms (Patriot Properties, Vision Government Solutions, etc.).

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
| HTTP scraping | httpx async client — direct VGSI API calls (`async.asmx/GetDataAddress` + `Parcel.aspx`) |
| Container | Docker |
| Runtime | GCP Cloud Run |
| Secrets (prod) | GCP Secret Manager via --set-secrets |
| Secrets (local) | .env file loaded by python-dotenv |

---

## Repository Layout

```
cope-iq/
├── CLAUDE.md              ← you are here
├── .env                   ← local secrets, never committed
├── .env.example           ← safe template, committed
├── .gitignore
├── Dockerfile
├── cloudbuild.yaml        ← GCP Cloud Build → Cloud Run deploy
├── requirements.txt
├── start.bat              ← activates venv + starts uvicorn (Windows/PowerShell)
├── README.md
├── main.py                ← FastAPI app, lifespan hooks, router mounts
├── config.py              ← pydantic-settings, loads .env
├── db/mongo.py            ← motor client, collection helpers, index + seed logic
├── auth/supabase.py       ← PyJWKClient-based ES256 JWT verify dependency
├── routers/
│   ├── municipalities.py  ← GET/POST municipality registry
│   ├── properties.py      ← POST /cope/search, GET /properties/history, DELETE
│   └── admin.py           ← health check, seed trigger (admin-only)
├── scraper/
│   ├── cope_scraper.py    ← VGSI HTTP scraper + Claude JSON extraction
│   └── prompts.py         ← SYSTEM_PROMPT + extraction_prompt() template
├── models/
│   ├── municipality.py    ← Pydantic municipality doc model
│   └── property.py        ← Pydantic COPE result doc model
└── frontend/index.html    ← full UI: auth, search, results panel, history, DB panel
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

---

## MongoDB Collections

### `municipalities`
Registry of supported property card databases. Seeded automatically on first run.
Key fields: `state`, `municipality` (lowercase normalized), `municipality_display`, `search_url`, `search_type`, `active`.

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

## VGSI Scraper Pipeline

VGSI (Vision Government Solutions) is an ASP.NET WebForms SPA used by many New England
municipalities to host property assessment data. The scraper uses two HTTP calls:

1. **Address autocomplete** — `POST {base_url}/async.asmx/GetDataAddress`
   Body: `{"inVal": "<street only>", "src": "i_address"}`
   Returns: `{"d": [{"id": "<pid>", "value": "<matched address>"}, ...]}`

2. **Property card** — `GET {base_url}/Parcel.aspx?Pid=<pid>`
   Returns full HTML of the property assessment card.

The street query is stripped of street-type suffixes (Dr, Rd, St, etc.) before submission
because VGSI often uses non-standard abbreviations (e.g., "EXT" instead of "Dr").

The HTML is cleaned to plain text, then passed to Claude for structured JSON extraction.
Photo URLs (`images.vgsi.com`) and sketch URLs (`ParcelSketch.ashx`) are extracted from
the raw HTML before stripping, since they may not survive text cleaning.

SSL certificate verification is disabled (`verify=False`) due to Windows cert chain
issues with VGSI hosts.

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

### Phase 2 — Coverage Expansion
- [ ] Add Patriot Properties scraper strategy (`search_type: patriot`)
- [ ] Add Vision Government Solutions strategy (`search_type: vision`)
- [ ] Bulk municipality import tool (CSV upload in admin panel)
- [ ] Expand seed data to NH, VT, MA municipalities

### Phase 3 — Protection & Exposure Enrichment
- [ ] Fire station distance via NFPA / ISO FireLine secondary lookup
- [ ] Flood zone via FEMA NFHL API (using geocoded lat/lng)
- [ ] Protection class (ISO) lookup integration
- [ ] Map view of property location using Google Maps embed

### Phase 4 — Enterprise
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
- Never commit `.env`. All production secrets live in GCP Secret Manager.

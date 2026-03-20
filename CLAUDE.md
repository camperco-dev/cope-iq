# COPE Property Intelligence

## What This Project Does

COPE Property Intelligence is an insurance underwriting tool that retrieves
Construction, Occupancy, Protection, and Exposure (COPE) data for any physical
property address by searching publicly available municipal property card databases.

A user enters a street address. The app:
1. Geocodes it via Google Maps to extract the municipality and state
2. Confirms that municipality is in our supported database
3. Uses an Anthropic AI agent (with web search) to navigate to the assessor's
   property card site and extract all available data fields
4. Returns a structured COPE report and caches it for 30 days

This is an early-stage product. The initial dataset covers Maine municipalities
served by the VGSI GIS platform. Coverage will expand to other states and
assessor platforms (Patriot Properties, Vision Government Solutions, etc.).

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11, FastAPI, Uvicorn |
| Database | MongoDB Atlas (motor async driver) |
| Auth | Supabase — email/password + magic link, JWT verified server-side |
| Frontend | Single HTML file, vanilla JS/CSS, served by FastAPI |
| Address validation | Google Maps Geocoding API + Places Autocomplete |
| AI scraping | Anthropic claude-sonnet-4-5 with web_search tool |
| Container | Docker |
| Runtime | GCP Cloud Run |
| Secrets (prod) | GCP Secret Manager via --set-secrets |
| Secrets (local) | .env file loaded by python-dotenv |

---

## Repository Layout

```
cope-intel/
├── CLAUDE.md              ← you are here
├── .env                   ← local secrets, never committed
├── .env.example           ← safe template, committed
├── .gitignore
├── Dockerfile
├── cloudbuild.yaml        ← GCP Cloud Build → Cloud Run deploy
├── requirements.txt
├── README.md
├── main.py                ← FastAPI app, lifespan hooks, router mounts
├── config.py              ← pydantic-settings, loads .env
├── db/mongo.py            ← motor client, collection helpers, index + seed logic
├── auth/supabase.py       ← Supabase client, JWT verify dependency
├── routers/
│   ├── municipalities.py  ← GET/POST municipality registry
│   ├── properties.py      ← POST /cope/search, GET /properties/history
│   └── admin.py           ← health check, seed trigger (admin-only)
├── scraper/
│   ├── cope_scraper.py    ← Anthropic API call, JSON extraction
│   └── prompts.py         ← SYSTEM_PROMPT + user_prompt() template
├── models/
│   ├── municipality.py    ← Pydantic municipality doc model
│   └── property.py        ← Pydantic COPE result doc model
└── frontend/index.html    ← full UI: auth, search, results, history, DB panel
```

---

## Local Development Setup

### Prerequisites
- Python 3.11+
- A MongoDB Atlas cluster (free tier M0 is fine for dev)
- A Supabase project (free tier)
- Google Maps API key with Geocoding API + Maps JS API + Places API enabled
- An Anthropic API key

### Steps

```bash
git clone <repo-url>
cd cope-intel
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env              # then fill in your real keys
uvicorn main:app --reload --port 8000
```

Open http://localhost:8000 — the frontend is served by FastAPI.

### Running Without All Keys

The app degrades gracefully:
- Missing `GOOGLE_MAPS_API_KEY` → geocoding fails with a clear 422; address parsing falls back to comma-split heuristic
- Missing `ANTHROPIC_API_KEY` → scraper returns an error payload; all other routes work
- Missing Supabase keys → auth middleware raises 500 on protected routes; public routes still work

---

## MongoDB Collections

### `municipalities`
Registry of supported property card databases. Seeded automatically on first run.
Key fields: `state`, `municipality` (lowercase), `search_url`, `search_type`, `active`.

### `properties`
Cached COPE search results. One document per unique address+user lookup.
Key fields: all COPE sub-objects (`construction`, `occupancy`, `protection`, `exposure`),
`completeness_pct`, `cache_expires_at`, `searched_by`, `raw_json`.

---

## Authentication Model

- Supabase handles identity. Users sign up/in via the frontend using the Supabase JS SDK.
- The frontend passes the Supabase JWT as `Authorization: Bearer <token>` on every API call.
- FastAPI verifies the JWT using `SUPABASE_JWT_SECRET` in `auth/supabase.py`.
- Admin actions (adding municipalities) require `user.app_metadata.role == "admin"`,
  which must be set manually in the Supabase dashboard or via the service role API.

---

## Current Development Goals

### Phase 1 — MVP (active)
- [x] Project scaffold, MongoDB schema, seed data
- [x] Supabase auth flow (email + magic link)
- [x] Google Maps geocoding + Places Autocomplete
- [x] Municipality lookup with fuzzy matching
- [x] Anthropic-powered COPE scraper (VGSI sites)
- [x] 30-day result caching per user
- [x] Frontend: search, results panel, history, municipality DB view
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

- All COPE sub-objects store values as strings (not typed), since assessor data
  is inconsistently formatted. Consumers should parse as needed.
- Null fields are stored as `null` in MongoDB and rendered as `—` in the UI.
- `municipality` field in the DB is always lowercase, no punctuation.
  Matching normalizes the query the same way.
- The `raw_json` field on property documents stores the full Anthropic response
  for debugging. It is excluded from history list queries for payload efficiency.
- Never commit `.env`. All production secrets live in GCP Secret Manager.

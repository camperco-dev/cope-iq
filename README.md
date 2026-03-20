# COPE Property Intelligence

An insurance underwriting tool that retrieves Construction, Occupancy, Protection, and Exposure (COPE) data for any property address by searching publicly available municipal assessment databases.

## Prerequisites

- Python 3.11+
- [MongoDB Atlas](https://www.mongodb.com/atlas) cluster (free M0 tier works)
- [Supabase](https://supabase.com) project (free tier)
- [Google Maps Platform](https://console.cloud.google.com) API key with:
  - Geocoding API
  - Maps JavaScript API
  - Places API
- [Anthropic](https://console.anthropic.com) API key

## Local Development Setup

```bash
git clone <repo-url>
cd cope-intel
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env       # Fill in your real keys
uvicorn main:app --reload --port 8000
```

Open http://localhost:8000

## MongoDB Setup

1. Create a free M0 cluster on [MongoDB Atlas](https://cloud.mongodb.com)
2. Add a database user with **Read and Write** to any database
3. Whitelist your IP (or `0.0.0.0/0` for development)
4. Copy the connection string into `MONGODB_URI` in `.env`

Collections and indexes are created automatically on first run.
Seed municipality data (10 Maine municipalities) is inserted if the collection is empty.

## Supabase Setup

1. Create a new project at [supabase.com](https://supabase.com)
2. Enable **Email** provider under Authentication → Providers
3. Copy values from **Settings → API**:
   - Project URL → `SUPABASE_URL`
   - Anon/public key → `SUPABASE_ANON_KEY`
   - Service role key → `SUPABASE_SERVICE_ROLE_KEY`
   - JWT secret → `SUPABASE_JWT_SECRET`

## Google Maps Setup

1. Enable **Geocoding API**, **Maps JavaScript API**, and **Places API** in Google Cloud Console
2. Create an API key and restrict by HTTP referrer in production
3. Copy key to `GOOGLE_MAPS_API_KEY` in `.env`

## GCP Deployment

1. Enable APIs: Cloud Run, Cloud Build, Container Registry, Secret Manager
2. Create secrets in Secret Manager for all sensitive values
3. Connect your repo to Cloud Build trigger pointing to `cloudbuild.yaml`
4. Push to deploy

## Adding Municipalities

Municipalities can be added via the API (admin users only):

```bash
curl -X POST http://localhost:8000/api/municipalities \
  -H "Authorization: Bearer <admin-jwt>" \
  -H "Content-Type: application/json" \
  -d '{
    "state": "ME",
    "municipality": "Bath",
    "municipality_display": "Bath",
    "search_url": "https://gis.vgsi.com/bathme/",
    "search_type": "vgsi"
  }'
```

To grant admin access, set `app_metadata.role = "admin"` for a user in the Supabase dashboard.

## Cache Behavior

Results are cached for 30 days per address per user (configurable via `CACHE_TTL_DAYS`).
Cached results return `"cached": true` and skip the AI scraper.

## COPE Field Coverage

| Field Group | Source |
|-------------|--------|
| Construction | Municipal assessor property card |
| Occupancy | Municipal assessor property card |
| Protection | Assessor card (partial); fire station distance requires secondary lookup |
| Exposure | Assessor card (lot, zoning); flood zone requires FEMA NFHL API |

import re
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from bson import ObjectId
from db.mongo import municipalities as muni_col
from models.municipality import MunicipalityCreate, MunicipalityResponse
from auth.supabase import verify_token, require_admin
import httpx

router = APIRouter()


def _normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", name.lower()).strip()


def _doc_to_response(doc: dict) -> dict:
    doc["_id"] = str(doc["_id"])
    return doc


@router.get("")
async def list_municipalities():
    """Return all active municipalities sorted by state then name."""
    cursor = muni_col().find({"active": True}, {"_id": 1, "state": 1, "county": 1,
                                                  "municipality": 1, "municipality_display": 1,
                                                  "search_url": 1, "search_type": 1,
                                                  "notes": 1, "active": 1, "date_added": 1})
    cursor.sort([("state", 1), ("municipality", 1)])
    results = []
    async for doc in cursor:
        results.append(_doc_to_response(doc))
    return results


@router.get("/search")
async def search_municipalities(q: str, state: Optional[str] = None):
    """Fuzzy search for a municipality by name."""
    normalized = _normalize(q)
    query: dict = {"active": True}
    if state:
        query["state"] = state.upper()

    # Try exact match first
    exact_query = dict(query, municipality=normalized)
    doc = await muni_col().find_one(exact_query)
    if doc:
        return _doc_to_response(doc)

    # Starts-with match
    async for doc in muni_col().find(query):
        if doc["municipality"].startswith(normalized):
            return _doc_to_response(doc)

    # Contains match
    async for doc in muni_col().find(query):
        if normalized in doc["municipality"]:
            return _doc_to_response(doc)

    raise HTTPException(status_code=404, detail=f"Municipality '{q}' not found")


@router.post("", status_code=201)
async def create_municipality(
    body: MunicipalityCreate,
    user: dict = Depends(verify_token),
):
    """Admin-only: add a new municipality."""
    require_admin(user)

    # Validate URL is reachable
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.head(body.search_url)
            if r.status_code >= 400:
                raise HTTPException(status_code=422, detail=f"Search URL returned {r.status_code}")
    except httpx.RequestError as e:
        raise HTTPException(status_code=422, detail=f"Search URL unreachable: {str(e)}")

    from datetime import datetime, timezone
    doc = body.model_dump()
    doc["municipality"] = _normalize(doc["municipality"])
    doc["date_added"] = datetime.now(timezone.utc)
    doc["added_by"] = user.get("sub", "unknown")

    try:
        result = await muni_col().insert_one(doc)
        doc["_id"] = str(result.inserted_id)
        return doc
    except Exception as e:
        if "duplicate key" in str(e).lower():
            raise HTTPException(status_code=409, detail="Municipality already exists")
        raise HTTPException(status_code=500, detail=str(e))

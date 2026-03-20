from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from datetime import datetime, timezone, timedelta
from bson import ObjectId
import httpx
import re

from db.mongo import municipalities as muni_col, properties as prop_col
from auth.supabase import verify_token
from scraper.cope_scraper import search_cope
from config import settings

router = APIRouter()


class SearchRequest(BaseModel):
    address: str


def _normalize_muni(name: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", name.lower()).strip()


def _doc_to_response(doc: dict) -> dict:
    doc["_id"] = str(doc["_id"])
    if "municipality_id" in doc and isinstance(doc["municipality_id"], ObjectId):
        doc["municipality_id"] = str(doc["municipality_id"])
    return doc


async def _geocode(address: str) -> dict:
    if not settings.google_maps_api_key:
        # Fallback: naive parse
        parts = [p.strip() for p in address.split(",")]
        locality = parts[-2] if len(parts) >= 2 else ""
        state_zip = parts[-1].strip().split() if parts else []
        state = state_zip[0] if state_zip else ""
        return {
            "formatted_address": address,
            "lat": None, "lng": None, "place_id": None,
            "locality": locality,
            "state": state,
            "postal_code": "",
        }

    url = "https://maps.googleapis.com/maps/api/geocode/json"
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(url, params={"address": address, "key": settings.google_maps_api_key})
    data = r.json()
    if not data.get("results"):
        raise HTTPException(status_code=422, detail="Address could not be geocoded")

    result = data["results"][0]
    components = {}
    for c in result["address_components"]:
        if c["types"]:
            components[c["types"][0]] = c["short_name"]

    return {
        "formatted_address": result["formatted_address"],
        "lat": result["geometry"]["location"]["lat"],
        "lng": result["geometry"]["location"]["lng"],
        "place_id": result["place_id"],
        "locality": components.get("locality", components.get("sublocality", "")),
        "state": components.get("administrative_area_level_1", ""),
        "postal_code": components.get("postal_code", ""),
    }


def _count_completeness(cope_result: dict) -> int:
    """Count non-null leaf fields across COPE sub-objects."""
    sections = ["construction", "occupancy", "protection", "exposure"]
    total = 0
    filled = 0
    for section in sections:
        sub = cope_result.get(section, {}) or {}
        for v in sub.values():
            total += 1
            if v is not None:
                filled += 1
    if total == 0:
        return 0
    return round(filled / total * 100)


@router.post("/cope/search")
async def cope_search(body: SearchRequest, user: dict = Depends(verify_token)):
    user_id = user.get("sub")

    # 1. Geocode
    geocode = await _geocode(body.address)
    locality = geocode.get("locality", "")
    state = geocode.get("state", "")

    if not locality or not state:
        raise HTTPException(status_code=422, detail="Could not determine municipality from address")

    # 2. Municipality lookup
    normalized = _normalize_muni(locality)
    muni_doc = await muni_col().find_one({"municipality": normalized, "state": state, "active": True})
    if not muni_doc:
        # Try to suggest closest
        suggestion = None
        async for doc in muni_col().find({"state": state, "active": True}):
            suggestion = doc.get("municipality_display")
            break
        raise HTTPException(
            status_code=422,
            detail={
                "error": "Municipality not supported",
                "municipality": f"{locality}, {state}",
                "suggestion": suggestion,
            },
        )

    # 3. Cache check
    now = datetime.now(timezone.utc)
    cached = await prop_col().find_one({
        "search_address": {"$regex": f"^{re.escape(body.address)}$", "$options": "i"},
        "searched_by": user_id,
        "cache_expires_at": {"$gt": now},
    })
    if cached:
        cached["cached"] = True
        return _doc_to_response(cached)

    # 4. Scrape
    cope_result = await search_cope(body.address, muni_doc)

    # 5. Build and store document
    completeness = _count_completeness(cope_result)
    expires_at = now + timedelta(days=settings.cache_ttl_days)

    prop_doc = {
        "search_address": body.address,
        "matched_address": cope_result.get("matched_address"),
        "parcel_id": cope_result.get("parcel_id"),
        "municipality_id": muni_doc["_id"],
        "data_source_url": cope_result.get("data_source_url"),
        "searched_by": user_id,
        "search_timestamp": now,
        "cache_expires_at": expires_at,
        "cached": False,
        "geocode": {
            "lat": geocode.get("lat"),
            "lng": geocode.get("lng"),
            "formatted_address": geocode.get("formatted_address"),
            "place_id": geocode.get("place_id"),
        },
        "construction": cope_result.get("construction"),
        "occupancy": cope_result.get("occupancy"),
        "protection": cope_result.get("protection"),
        "exposure": cope_result.get("exposure"),
        "notes": cope_result.get("notes"),
        "raw_json": str(cope_result),
        "completeness_pct": completeness,
        "error": cope_result.get("error"),
    }

    # Only persist if no hard error
    if not cope_result.get("error"):
        result = await prop_col().insert_one(prop_doc)
        prop_doc["_id"] = str(result.inserted_id)
    else:
        prop_doc["_id"] = None

    return _doc_to_response(prop_doc)


@router.get("/properties/history")
async def get_history(user: dict = Depends(verify_token)):
    user_id = user.get("sub")
    cursor = prop_col().find(
        {"searched_by": user_id},
        {"raw_json": 0},
    ).sort("search_timestamp", -1).limit(50)

    results = []
    async for doc in cursor:
        results.append(_doc_to_response(doc))
    return results


@router.delete("/properties/{property_id}")
async def delete_property(property_id: str, user: dict = Depends(verify_token)):
    user_id = user.get("sub")
    try:
        oid = ObjectId(property_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid property ID")

    result = await prop_col().delete_one({"_id": oid, "searched_by": user_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Property not found")
    return {"deleted": True}

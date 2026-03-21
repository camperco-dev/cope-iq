from fastapi import APIRouter, Depends, HTTPException
from auth.supabase import verify_token, require_admin
from db.mongo import get_db, municipalities as muni_col, seed_municipalities
from scraper.qpublic_browser import get_property_search_url

router = APIRouter()


@router.get("/health")
async def health_check(user: dict = Depends(verify_token)):
    require_admin(user)
    try:
        db = get_db()
        await db.command("ping")
        muni_count = await muni_col().count_documents({})
        return {"status": "ok", "municipalities": muni_count}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {str(e)}")


@router.post("/seed")
async def trigger_seed(user: dict = Depends(verify_token)):
    require_admin(user)
    await seed_municipalities()
    count = await muni_col().count_documents({})
    return {"seeded": True, "total_municipalities": count}


@router.post("/enrich-qpublic")
async def enrich_qpublic_search_urls(user: dict = Depends(verify_token)):
    """
    Backfill search_page_url for all active qPublic municipalities that don't
    already have one. Uses a headless Playwright browser to navigate
    qpublic.schneidercorp.com and capture the county-specific Property Search URL.

    Safe to re-run — skips municipalities that already have search_page_url set.
    Returns a summary of updated, skipped, and failed municipalities.
    """
    require_admin(user)

    cursor = muni_col().find({"search_type": "qpublic", "active": True})
    updated, skipped, failed = [], [], []

    async for doc in cursor:
        name = f"{doc.get('municipality_display')}, {doc.get('state')}"
        existing_url = (doc.get("platform_config") or {}).get("search_page_url")
        if existing_url:
            skipped.append({"municipality": name, "reason": "already has search_page_url"})
            continue

        state = doc.get("state", "")
        county = doc.get("county", "")
        if not county:
            # Derive county from municipality display (e.g. "Bryan County" → "Bryan")
            county = doc.get("municipality_display", "").replace(" County", "").strip()

        print(f"[admin/enrich-qpublic] enriching {name} (county={county!r})")
        try:
            search_url = await get_property_search_url(state, county)
            if search_url:
                platform_config = dict(doc.get("platform_config") or {})
                platform_config["search_page_url"] = search_url
                await muni_col().update_one(
                    {"_id": doc["_id"]},
                    {"$set": {"platform_config": platform_config}},
                )
                updated.append({"municipality": name, "search_page_url": search_url})
                print(f"[admin/enrich-qpublic] ✓ {name} → {search_url}")
            else:
                failed.append({"municipality": name, "reason": "browser probe found no Property Search link"})
                print(f"[admin/enrich-qpublic] ✗ {name} — no link found")
        except Exception as exc:
            failed.append({"municipality": name, "reason": str(exc)})
            print(f"[admin/enrich-qpublic] ✗ {name} — error: {exc}")

    return {
        "updated": updated,
        "skipped": skipped,
        "failed": failed,
        "summary": {
            "updated": len(updated),
            "skipped": len(skipped),
            "failed": len(failed),
        },
    }

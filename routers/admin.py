from fastapi import APIRouter, Depends, HTTPException
from auth.supabase import verify_token, require_admin
from db.mongo import get_db, municipalities as muni_col, seed_municipalities

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

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager

from db.mongo import ensure_indexes, seed_municipalities
from routers import municipalities, properties, admin
from config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    await ensure_indexes()
    await seed_municipalities()
    yield


app = FastAPI(title="COPE Property Intelligence", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://localhost:8000", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(municipalities.router, prefix="/api/municipalities", tags=["municipalities"])
app.include_router(properties.router, prefix="/api", tags=["properties"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])


@app.get("/api/config")
async def get_config():
    """Return public config values for frontend initialization."""
    return JSONResponse({
        "supabase_url": settings.supabase_url,
        "supabase_anon_key": settings.supabase_anon_key,
        "google_maps_api_key": settings.google_maps_api_key,
        "app_env": settings.app_env,
    })


app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")

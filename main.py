# ── Windows / OpenSSL 3.0 TLS 1.3 compatibility fix ──────────────────────────
# Python 3.11 on Windows ships OpenSSL 3.0 whose TLS 1.3 handshake is
# incompatible with some MongoDB Atlas shard configurations (internal_error).
# We patch get_ssl_context() to append OP_NO_TLSv1_3, forcing TLS 1.2.
#
# pymongo.client_options does `from pymongo.ssl_support import get_ssl_context`
# at import time, binding the name locally. Patching only ssl_support leaves
# that local reference unchanged. We must patch BOTH modules.
import pymongo.ssl_support as _pymongo_ssl_support
import pymongo.client_options as _pymongo_client_options
_OP_NO_TLSv1_3 = 0x20000000  # OpenSSL SSL_OP_NO_TLSv1_3
_orig_get_ssl_context = _pymongo_ssl_support.get_ssl_context

def _get_ssl_context_tls12(*args, **kwargs):
    ctx = _orig_get_ssl_context(*args, **kwargs)
    if ctx is not None:
        try:
            ctx.options |= _OP_NO_TLSv1_3
        except (AttributeError, OSError):
            pass
    return ctx

_pymongo_ssl_support.get_ssl_context = _get_ssl_context_tls12
_pymongo_client_options.get_ssl_context = _get_ssl_context_tls12
# ─────────────────────────────────────────────────────────────────────────────

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

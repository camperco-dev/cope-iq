from supabase import create_client, Client
import jwt
from jwt import PyJWKClient
from fastapi import HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from config import settings

_supabase_client: Client = None
_jwks_client: PyJWKClient = None


def get_supabase() -> Client:
    global _supabase_client
    if _supabase_client is None and settings.supabase_url and settings.supabase_service_role_key:
        _supabase_client = create_client(settings.supabase_url, settings.supabase_service_role_key)
    return _supabase_client


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        jwks_url = f"{settings.supabase_url}/auth/v1/.well-known/jwks.json"
        _jwks_client = PyJWKClient(jwks_url)
    return _jwks_client


security = HTTPBearer()


def verify_token(credentials: HTTPAuthorizationCredentials = Security(security)) -> dict:
    """Decode and verify Supabase JWT using JWKS. Supports ES256 and HS256."""
    token = credentials.credentials
    try:
        signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256", "HS256"],
            audience="authenticated",
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Auth error: {e}")


def require_admin(payload: dict) -> dict:
    """Check that the user has admin role in app_metadata."""
    app_meta = payload.get("app_metadata", {})
    if app_meta.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return payload

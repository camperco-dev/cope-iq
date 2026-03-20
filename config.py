from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    # Anthropic
    anthropic_api_key: str = Field(default="", env="ANTHROPIC_API_KEY")

    # MongoDB
    mongodb_uri: str = Field(default="", env="MONGODB_URI")
    mongodb_db: str = Field(default="cope_intel", env="MONGODB_DB")

    # Supabase
    supabase_url: str = Field(default="", env="SUPABASE_URL")
    supabase_anon_key: str = Field(default="", env="SUPABASE_ANON_KEY")
    supabase_service_role_key: str = Field(default="", env="SUPABASE_SERVICE_ROLE_KEY")
    supabase_jwt_secret: str = Field(default="", env="SUPABASE_JWT_SECRET")

    # Google Maps
    google_maps_api_key: str = Field(default="", env="GOOGLE_MAPS_API_KEY")

    # GCP
    gcp_project_id: str = Field(default="", env="GCP_PROJECT_ID")
    gcp_region: str = Field(default="us-east1", env="GCP_REGION")

    # App
    app_env: str = Field(default="development", env="APP_ENV")
    frontend_url: str = Field(default="http://localhost:8000", env="FRONTEND_URL")
    cache_ttl_days: int = Field(default=30, env="CACHE_TTL_DAYS")

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()

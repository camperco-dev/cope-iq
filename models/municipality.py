from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class MunicipalityCreate(BaseModel):
    state: str
    county: Optional[str] = None
    municipality: str
    municipality_display: str
    search_url: str
    search_type: str = "vgsi"
    notes: Optional[str] = None
    active: bool = True


class MunicipalityResponse(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    state: str
    county: Optional[str] = None
    municipality: str
    municipality_display: str
    search_url: str
    search_type: str
    notes: Optional[str] = None
    active: bool
    date_added: Optional[datetime] = None
    added_by: Optional[str] = None

    class Config:
        populate_by_name = True

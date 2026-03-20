from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class GeocodeData(BaseModel):
    lat: Optional[float] = None
    lng: Optional[float] = None
    formatted_address: Optional[str] = None
    place_id: Optional[str] = None


class ConstructionData(BaseModel):
    year_built: Optional[str] = None
    construction_type: Optional[str] = None
    stories: Optional[str] = None
    total_sqft: Optional[str] = None
    living_area_sqft: Optional[str] = None
    roof_shape: Optional[str] = None
    roof_material: Optional[str] = None
    foundation_type: Optional[str] = None
    exterior_walls: Optional[str] = None
    heating_type: Optional[str] = None
    num_buildings: Optional[str] = None


class OccupancyData(BaseModel):
    use_code: Optional[str] = None
    use_description: Optional[str] = None
    occupancy_class: Optional[str] = None
    num_units: Optional[str] = None
    num_bedrooms: Optional[str] = None
    num_bathrooms: Optional[str] = None
    assessed_value: Optional[str] = None
    land_value: Optional[str] = None
    building_value: Optional[str] = None


class ProtectionData(BaseModel):
    fire_district: Optional[str] = None
    distance_to_station: Optional[str] = None
    sprinkler_system: Optional[str] = None
    alarm_system: Optional[str] = None
    hydrant_proximity: Optional[str] = None
    protection_class: Optional[str] = None


class ExposureData(BaseModel):
    flood_zone: Optional[str] = None
    lot_size: Optional[str] = None
    zoning_code: Optional[str] = None
    neighborhood: Optional[str] = None
    latitude: Optional[str] = None
    longitude: Optional[str] = None


class PropertyResponse(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    search_address: str
    matched_address: Optional[str] = None
    parcel_id: Optional[str] = None
    data_source_url: Optional[str] = None
    searched_by: Optional[str] = None
    search_timestamp: Optional[datetime] = None
    cache_expires_at: Optional[datetime] = None
    cached: bool = False
    geocode: Optional[GeocodeData] = None
    construction: Optional[ConstructionData] = None
    occupancy: Optional[OccupancyData] = None
    protection: Optional[ProtectionData] = None
    exposure: Optional[ExposureData] = None
    notes: Optional[str] = None
    completeness_pct: Optional[int] = None
    error: Optional[str] = None

    class Config:
        populate_by_name = True

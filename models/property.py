from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class GeocodeData(BaseModel):
    lat: Optional[float] = None
    lng: Optional[float] = None
    formatted_address: Optional[str] = None
    place_id: Optional[str] = None


class OwnerData(BaseModel):
    name: Optional[str] = None
    co_owner: Optional[str] = None
    address: Optional[str] = None


class SaleData(BaseModel):
    price: Optional[str] = None
    date: Optional[str] = None
    code: Optional[str] = None
    book_page: Optional[str] = None
    certificate: Optional[str] = None


class ConstructionData(BaseModel):
    year_built: Optional[str] = None
    style: Optional[str] = None
    model: Optional[str] = None
    grade: Optional[str] = None
    condition: Optional[str] = None
    stories: Optional[str] = None
    num_buildings: Optional[str] = None
    total_sqft: Optional[str] = None
    living_area_sqft: Optional[str] = None
    replacement_cost: Optional[str] = None
    replacement_cost_depreciated: Optional[str] = None
    building_percent_good: Optional[str] = None
    exterior_wall_1: Optional[str] = None
    exterior_wall_2: Optional[str] = None
    roof_structure: Optional[str] = None
    roof_cover: Optional[str] = None
    interior_wall_1: Optional[str] = None
    interior_wall_2: Optional[str] = None
    interior_floor_1: Optional[str] = None
    interior_floor_2: Optional[str] = None
    heat_fuel: Optional[str] = None
    heat_type: Optional[str] = None
    ac_type: Optional[str] = None
    fireplaces: Optional[str] = None
    foundation_type: Optional[str] = None
    foundation_condition: Optional[str] = None
    basement: Optional[str] = None


class OccupancyData(BaseModel):
    use_code: Optional[str] = None
    use_description: Optional[str] = None
    occupancy_class: Optional[str] = None
    num_units: Optional[str] = None
    num_bedrooms: Optional[str] = None
    num_bathrooms: Optional[str] = None
    num_half_baths: Optional[str] = None
    num_rooms: Optional[str] = None
    bath_style: Optional[str] = None
    kitchen_style: Optional[str] = None
    num_kitchens: Optional[str] = None


class ValuationData(BaseModel):
    valuation_year: Optional[str] = None
    assessed_value: Optional[str] = None
    building_value: Optional[str] = None
    land_value: Optional[str] = None


class ProtectionData(BaseModel):
    fire_district: Optional[str] = None
    distance_to_station: Optional[str] = None
    sprinkler_system: Optional[str] = None
    alarm_system: Optional[str] = None
    hydrant_proximity: Optional[str] = None
    protection_class: Optional[str] = None


class ExposureData(BaseModel):
    flood_zone: Optional[str] = None
    lot_size_acres: Optional[str] = None
    zoning_code: Optional[str] = None
    neighborhood: Optional[str] = None
    latitude: Optional[str] = None
    longitude: Optional[str] = None


class PropertyResponse(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    search_address: str
    matched_address: Optional[str] = None
    parcel_id: Optional[str] = None
    mblu: Optional[str] = None
    data_source_url: Optional[str] = None
    photo_url: Optional[str] = None
    sketch_url: Optional[str] = None
    municipality_display: Optional[str] = None
    searched_by: Optional[str] = None
    search_timestamp: Optional[datetime] = None
    cache_expires_at: Optional[datetime] = None
    cached: bool = False
    geocode: Optional[GeocodeData] = None
    owner: Optional[OwnerData] = None
    sale: Optional[SaleData] = None
    construction: Optional[ConstructionData] = None
    occupancy: Optional[OccupancyData] = None
    valuation: Optional[ValuationData] = None
    protection: Optional[ProtectionData] = None
    exposure: Optional[ExposureData] = None
    notes: Optional[str] = None
    completeness_pct: Optional[int] = None
    error: Optional[str] = None

    class Config:
        populate_by_name = True

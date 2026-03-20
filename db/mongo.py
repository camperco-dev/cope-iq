from motor.motor_asyncio import AsyncIOMotorClient
from config import settings
from datetime import datetime, timezone

_client: AsyncIOMotorClient = None

SEED_MUNICIPALITIES = [
    {"state": "ME", "county": "Knox",         "municipality": "rockland",  "municipality_display": "Rockland",  "search_url": "https://gis.vgsi.com/rocklandme/",   "search_type": "vgsi", "active": True},
    {"state": "ME", "county": "Knox",         "municipality": "camden",    "municipality_display": "Camden",    "search_url": "https://gis.vgsi.com/camdenme/",     "search_type": "vgsi", "active": True},
    {"state": "ME", "county": "Waldo",        "municipality": "belfast",   "municipality_display": "Belfast",   "search_url": "https://gis.vgsi.com/belfastme/",    "search_type": "vgsi", "active": True},
    {"state": "ME", "county": "Cumberland",   "municipality": "portland",  "municipality_display": "Portland",  "search_url": "https://gis.vgsi.com/portlandme/",   "search_type": "vgsi", "active": True},
    {"state": "ME", "county": "Penobscot",    "municipality": "bangor",    "municipality_display": "Bangor",    "search_url": "https://gis.vgsi.com/bangorMe/",     "search_type": "vgsi", "active": True},
    {"state": "ME", "county": "York",         "municipality": "biddeford", "municipality_display": "Biddeford", "search_url": "https://gis.vgsi.com/biddefordme/",  "search_type": "vgsi", "active": True},
    {"state": "ME", "county": "York",         "municipality": "saco",      "municipality_display": "Saco",      "search_url": "https://gis.vgsi.com/sacome/",       "search_type": "vgsi", "active": True},
    {"state": "ME", "county": "Androscoggin", "municipality": "auburn",    "municipality_display": "Auburn",    "search_url": "https://gis.vgsi.com/auburnme/",     "search_type": "vgsi", "active": True},
    {"state": "ME", "county": "Androscoggin", "municipality": "lewiston",  "municipality_display": "Lewiston",  "search_url": "https://gis.vgsi.com/lewistonme/",   "search_type": "vgsi", "active": True},
    {"state": "ME", "county": "Sagadahoc",    "municipality": "bath",      "municipality_display": "Bath",      "search_url": "https://gis.vgsi.com/bathme/",       "search_type": "vgsi", "active": True},
]


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(settings.mongodb_uri)
    return _client


def get_db():
    return get_client()[settings.mongodb_db]


def municipalities():
    return get_db()["municipalities"]


def properties():
    return get_db()["properties"]


async def ensure_indexes():
    """Call on app startup."""
    await municipalities().create_index([("state", 1), ("municipality", 1)], unique=True)
    await municipalities().create_index([("active", 1)])
    await municipalities().create_index([("municipality", "text")])
    await properties().create_index([("search_address", 1), ("searched_by", 1)])
    await properties().create_index([("search_timestamp", -1)])
    await properties().create_index([("searched_by", 1)])
    await properties().create_index([("municipality_id", 1)])


async def seed_municipalities():
    """Insert seed data if collection is empty."""
    count = await municipalities().count_documents({})
    if count == 0:
        docs = [dict(m, date_added=datetime.now(timezone.utc), added_by="seed") for m in SEED_MUNICIPALITIES]
        await municipalities().insert_many(docs)

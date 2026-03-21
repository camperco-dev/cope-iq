from motor.motor_asyncio import AsyncIOMotorClient
from config import settings
from datetime import datetime, timezone

_client: AsyncIOMotorClient = None

SEED_MUNICIPALITIES = [
    # ── Maine / VGSI ──────────────────────────────────────────────────────────
    {"state": "ME", "county": "Knox",         "municipality": "rockland",  "municipality_display": "Rockland",  "search_url": "https://gis.vgsi.com/rocklandme/",   "search_type": "vgsi", "platform_config": {}, "active": True},
    {"state": "ME", "county": "Knox",         "municipality": "camden",    "municipality_display": "Camden",    "search_url": "https://gis.vgsi.com/camdenme/",     "search_type": "vgsi", "platform_config": {}, "active": True},
    {"state": "ME", "county": "Waldo",        "municipality": "belfast",   "municipality_display": "Belfast",   "search_url": "https://gis.vgsi.com/belfastme/",    "search_type": "vgsi", "platform_config": {}, "active": True},
    {"state": "ME", "county": "Cumberland",   "municipality": "portland",  "municipality_display": "Portland",  "search_url": "https://gis.vgsi.com/portlandme/",   "search_type": "vgsi", "platform_config": {}, "active": True},
    {"state": "ME", "county": "Penobscot",    "municipality": "bangor",    "municipality_display": "Bangor",    "search_url": "https://gis.vgsi.com/bangorMe/",     "search_type": "vgsi", "platform_config": {}, "active": True},
    {"state": "ME", "county": "York",         "municipality": "biddeford", "municipality_display": "Biddeford", "search_url": "https://gis.vgsi.com/biddefordme/",  "search_type": "vgsi", "platform_config": {}, "active": True},
    {"state": "ME", "county": "York",         "municipality": "saco",      "municipality_display": "Saco",      "search_url": "https://gis.vgsi.com/sacome/",       "search_type": "vgsi", "platform_config": {}, "active": True},
    {"state": "ME", "county": "Androscoggin", "municipality": "auburn",    "municipality_display": "Auburn",    "search_url": "https://gis.vgsi.com/auburnme/",     "search_type": "vgsi", "platform_config": {}, "active": True},
    {"state": "ME", "county": "Androscoggin", "municipality": "lewiston",  "municipality_display": "Lewiston",  "search_url": "https://gis.vgsi.com/lewistonme/",   "search_type": "vgsi", "platform_config": {}, "active": True},
    {"state": "ME", "county": "Sagadahoc",    "municipality": "bath",      "municipality_display": "Bath",      "search_url": "https://gis.vgsi.com/bathme/",       "search_type": "vgsi", "platform_config": {}, "active": True},
    {"state": "ME", "county": "Kennebec",    "municipality": "augusta",   "municipality_display": "Augusta",   "search_url": "https://gis.vgsi.com/augustame/",    "search_type": "vgsi", "platform_config": {}, "active": True},

    # ── Georgia / qPublic (Schneider Corp) ───────────────────────────────────
    # search_page_url obtained via qpublic_browser.get_property_search_url()
    {
        "state": "GA", "county": "Bryan",
        "municipality": "bryan county",
        "municipality_display": "Bryan County",
        "search_url": "https://qpublic.schneidercorp.com",
        "search_type": "qpublic",
        "platform_config": {
            "app_id": "BryanCountyGA", "layer_id": "Parcels",
            "search_page_url": "https://qpublic.schneidercorp.com/Application.aspx?AppID=639&LayerID=11303&PageTypeID=2&PageID=4634",
        },
        "active": True,
    },
    {
        "state": "GA", "county": "Haralson",
        "municipality": "haralson county",
        "municipality_display": "Haralson County",
        "search_url": "https://qpublic.schneidercorp.com",
        "search_type": "qpublic",
        "platform_config": {
            "app_id": "HaralsonCountyGA", "layer_id": "Parcels",
            "search_page_url": "https://qpublic.schneidercorp.com/Application.aspx?AppID=744&LayerID=11781&PageTypeID=2&PageID=5504",
        },
        "active": True,
    },
    {
        "state": "GA", "county": "Polk",
        "municipality": "polk county",
        "municipality_display": "Polk County",
        "search_url": "https://qpublic.schneidercorp.com",
        "search_type": "qpublic",
        "platform_config": {
            "app_id": "PolkCountyGA", "layer_id": "Parcels",
            "search_page_url": "https://qpublic.schneidercorp.com/Application.aspx?AppID=690&LayerID=11379&PageTypeID=2&PageID=4804",
        },
        "active": True,
    },

    # ── South Carolina / qPublic ─────────────────────────────────────────────
    {
        "state": "SC", "county": "Spartanburg",
        "municipality": "spartanburg county",
        "municipality_display": "Spartanburg County",
        "search_url": "https://qpublic.schneidercorp.com",
        "search_type": "qpublic",
        "platform_config": {
            "app_id": "SpartanburgCountySC", "layer_id": "Parcels",
            "search_page_url": "https://qpublic.schneidercorp.com/Application.aspx?AppID=857&LayerID=16069&PageTypeID=2&PageID=7147",
        },
        "active": True,
    },
    {
        "state": "SC", "county": "Lancaster",
        "municipality": "lancaster county",
        "municipality_display": "Lancaster County",
        "search_url": "https://qpublic.schneidercorp.com",
        "search_type": "qpublic",
        "platform_config": {
            "app_id": "LancasterCountySC", "layer_id": "Parcels",
            "search_page_url": "https://qpublic.schneidercorp.com/Application.aspx?AppID=211&LayerID=2815&PageTypeID=2&PageID=1551",
        },
        "active": True,
    },

    # ── Florida / qPublic ────────────────────────────────────────────────────
    {
        "state": "FL", "county": "Okaloosa",
        "municipality": "okaloosa county",
        "municipality_display": "Okaloosa County",
        "search_url": "https://qpublic.schneidercorp.com",
        "search_type": "qpublic",
        "platform_config": {
            "app_id": "OkaloosaCountyFL", "layer_id": "Parcels",
            "search_page_url": "https://qpublic.schneidercorp.com/Application.aspx?AppID=855&LayerID=15999&PageTypeID=2&PageID=7112",
        },
        "active": True,
    },
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

from motor.motor_asyncio import AsyncIOMotorClient
from config import settings
from datetime import datetime, timezone

_client: AsyncIOMotorClient = None

SEED_MUNICIPALITIES = [
    # ── Maine / VGSI ──────────────────────────────────────────────────────────
    {"state": "ME", "county": "Knox",         "municipality": "rockland",  "municipality_display": "Rockland",  "search_url": "https://gis.vgsi.com/rocklandme/",   "search_type": "vgsi", "platform_config": {}, "active": True},
    {"state": "ME", "county": "Knox",         "municipality": "camden",    "municipality_display": "Camden",    "search_url": "https://www.axisgis.com/CamdenME/", "search_type": "axisgis", "platform_config": {"municipality_id": "CamdenME", "cama_vendor": "Vision", "vgsi_url": "https://gis.vgsi.com/camdenme/"}, "active": True},
    {"state": "ME", "county": "Waldo",        "municipality": "belfast",   "municipality_display": "Belfast",   "search_url": "https://gis.vgsi.com/belfastme/",    "search_type": "vgsi", "platform_config": {}, "active": True},
    {"state": "ME", "county": "Cumberland",   "municipality": "portland",  "municipality_display": "Portland",  "search_url": "https://gis.vgsi.com/portlandme/",   "search_type": "vgsi", "platform_config": {}, "active": True},
    {"state": "ME", "county": "Penobscot",    "municipality": "bangor",    "municipality_display": "Bangor",    "search_url": "https://gis.vgsi.com/bangorMe/",     "search_type": "vgsi", "platform_config": {}, "active": True},
    {"state": "ME", "county": "York",         "municipality": "biddeford", "municipality_display": "Biddeford", "search_url": "https://gis.vgsi.com/biddefordme/",  "search_type": "vgsi", "platform_config": {}, "active": True},
    {"state": "ME", "county": "York",         "municipality": "saco",      "municipality_display": "Saco",      "search_url": "https://gis.vgsi.com/sacome/",       "search_type": "vgsi", "platform_config": {}, "active": True},
    # Auburn uses Patriot Properties (corrected from initial vgsi seed — CSV confirms patriot).
    # Lewiston uses Tyler Technologies iasWorld (Phase 4).
    {"state": "ME", "county": "Androscoggin", "municipality": "lewiston",  "municipality_display": "Lewiston",  "search_url": "https://lewistonmaine.tylertech.com", "search_type": "tyler", "platform_config": {}, "active": True},
    {"state": "ME", "county": "Sagadahoc",    "municipality": "bath",      "municipality_display": "Bath",      "search_url": "https://gis.vgsi.com/bathme/",       "search_type": "vgsi", "platform_config": {}, "active": True},
    {"state": "ME", "county": "Kennebec",    "municipality": "augusta",        "municipality_display": "Augusta",        "search_url": "https://gis.vgsi.com/augustame/",        "search_type": "vgsi", "platform_config": {}, "active": True},
    # Androscoggin County
    {"state": "ME", "county": "Androscoggin", "municipality": "sabattus",       "municipality_display": "Sabattus",       "search_url": "https://gis.vgsi.com/sabattusme/",       "search_type": "vgsi", "platform_config": {}, "active": True},
    # Cumberland County
    {"state": "ME", "county": "Cumberland",   "municipality": "baldwin",         "municipality_display": "Baldwin",         "search_url": "https://gis.vgsi.com/baldwinme/",        "search_type": "vgsi", "platform_config": {}, "active": True},
    {"state": "ME", "county": "Cumberland",   "municipality": "brunswick",       "municipality_display": "Brunswick",       "search_url": "https://gis.vgsi.com/brunswickme/",      "search_type": "vgsi", "platform_config": {}, "active": True},
    {"state": "ME", "county": "Cumberland",   "municipality": "casco",           "municipality_display": "Casco",           "search_url": "https://gis.vgsi.com/CascoME/",          "search_type": "vgsi", "platform_config": {}, "active": True},
    {"state": "ME", "county": "Cumberland",   "municipality": "cumberland",      "municipality_display": "Cumberland",      "search_url": "https://gis.vgsi.com/CumberlandME/",     "search_type": "vgsi", "platform_config": {}, "active": True},
    {"state": "ME", "county": "Cumberland",   "municipality": "falmouth",        "municipality_display": "Falmouth",        "search_url": "https://gis.vgsi.com/falmouthme/",       "search_type": "vgsi", "platform_config": {}, "active": True},
    {"state": "ME", "county": "Cumberland",   "municipality": "freeport",        "municipality_display": "Freeport",        "search_url": "https://gis.vgsi.com/freeportme/",       "search_type": "vgsi", "platform_config": {}, "active": True},
    {"state": "ME", "county": "Cumberland",   "municipality": "gorham",          "municipality_display": "Gorham",          "search_url": "https://gis.vgsi.com/gorhamme/",         "search_type": "vgsi", "platform_config": {}, "active": True},
    {"state": "ME", "county": "Cumberland",   "municipality": "harpswell",       "municipality_display": "Harpswell",       "search_url": "https://gis.vgsi.com/harpswellme/",      "search_type": "vgsi", "platform_config": {}, "active": True},
    {"state": "ME", "county": "Cumberland",   "municipality": "north yarmouth",  "municipality_display": "North Yarmouth",  "search_url": "https://gis.vgsi.com/NorthYarmouthME/",  "search_type": "vgsi", "platform_config": {}, "active": True},
    {"state": "ME", "county": "Cumberland",   "municipality": "raymond",         "municipality_display": "Raymond",         "search_url": "https://gis.vgsi.com/raymondme/",        "search_type": "vgsi", "platform_config": {}, "active": True},
    {"state": "ME", "county": "Cumberland",   "municipality": "scarborough",     "municipality_display": "Scarborough",     "search_url": "https://gis.vgsi.com/scarboroughme/",    "search_type": "vgsi", "platform_config": {}, "active": True},
    {"state": "ME", "county": "Cumberland",   "municipality": "south portland",  "municipality_display": "South Portland",  "search_url": "https://gis.vgsi.com/southportlandme/",  "search_type": "vgsi", "platform_config": {}, "active": True},
    {"state": "ME", "county": "Cumberland",   "municipality": "standish",        "municipality_display": "Standish",        "search_url": "https://gis.vgsi.com/standishme/",       "search_type": "vgsi", "platform_config": {}, "active": True},
    {"state": "ME", "county": "Cumberland",   "municipality": "westbrook",       "municipality_display": "Westbrook",       "search_url": "https://gis.vgsi.com/westbrookme/",      "search_type": "vgsi", "platform_config": {}, "active": True},
    {"state": "ME", "county": "Cumberland",   "municipality": "windham",         "municipality_display": "Windham",         "search_url": "https://gis.vgsi.com/WindhamME/",        "search_type": "vgsi", "platform_config": {}, "active": True},
    {"state": "ME", "county": "Cumberland",   "municipality": "yarmouth",        "municipality_display": "Yarmouth",        "search_url": "https://gis.vgsi.com/yarmouthme/",       "search_type": "vgsi", "platform_config": {}, "active": True},
    # Hancock County
    {"state": "ME", "county": "Hancock",      "municipality": "mount desert",    "municipality_display": "Mount Desert",    "search_url": "https://gis.vgsi.com/mountdesertme/",    "search_type": "vgsi", "platform_config": {}, "active": True},
    # Kennebec County
    {"state": "ME", "county": "Kennebec",     "municipality": "gardiner",        "municipality_display": "Gardiner",        "search_url": "https://gis.vgsi.com/gardinerme/",       "search_type": "vgsi", "platform_config": {}, "active": True},
    {"state": "ME", "county": "Kennebec",     "municipality": "monmouth",        "municipality_display": "Monmouth",        "search_url": "https://gis.vgsi.com/monmouthme/",       "search_type": "vgsi", "platform_config": {}, "active": True},
    {"state": "ME", "county": "Kennebec",     "municipality": "waterville",      "municipality_display": "Waterville",      "search_url": "https://gis.vgsi.com/watervilleme/",     "search_type": "vgsi", "platform_config": {}, "active": True},
    {"state": "ME", "county": "Kennebec",     "municipality": "winslow",         "municipality_display": "Winslow",         "search_url": "https://gis.vgsi.com/winslowme/",        "search_type": "vgsi", "platform_config": {}, "active": True},
    {"state": "ME", "county": "Kennebec",     "municipality": "winthrop",        "municipality_display": "Winthrop",        "search_url": "https://gis.vgsi.com/winthropme/",       "search_type": "vgsi", "platform_config": {}, "active": True},
    # Knox County
    {"state": "ME", "county": "Knox",         "municipality": "south thomaston", "municipality_display": "South Thomaston", "search_url": "https://gis.vgsi.com/souththomastonme/", "search_type": "vgsi", "platform_config": {}, "active": True},
    # Penobscot County
    {"state": "ME", "county": "Penobscot",    "municipality": "orono",           "municipality_display": "Orono",           "search_url": "https://gis.vgsi.com/oronoME/",          "search_type": "vgsi", "platform_config": {}, "active": True},
    # Sagadahoc County (Richmond ME is in Sagadahoc; skip — already seeded under Kennebec above)
    {"state": "ME", "county": "Sagadahoc",    "municipality": "topsham",         "municipality_display": "Topsham",         "search_url": "https://gis.vgsi.com/topshamme/",        "search_type": "vgsi", "platform_config": {}, "active": True},
    # York County
    {"state": "ME", "county": "York",         "municipality": "arundel",         "municipality_display": "Arundel",         "search_url": "https://gis.vgsi.com/arundelme/",        "search_type": "vgsi", "platform_config": {}, "active": True},
    {"state": "ME", "county": "York",         "municipality": "berwick",         "municipality_display": "Berwick",         "search_url": "https://gis.vgsi.com/berwickme/",        "search_type": "vgsi", "platform_config": {}, "active": True},
    {"state": "ME", "county": "York",         "municipality": "eliot",           "municipality_display": "Eliot",           "search_url": "https://gis.vgsi.com/eliotme/",          "search_type": "vgsi", "platform_config": {}, "active": True},
    {"state": "ME", "county": "York",         "municipality": "kennebunk",       "municipality_display": "Kennebunk",       "search_url": "https://gis.vgsi.com/kennebunkme/",      "search_type": "vgsi", "platform_config": {}, "active": True},
    {"state": "ME", "county": "York",         "municipality": "kittery",         "municipality_display": "Kittery",         "search_url": "https://gis.vgsi.com/KitteryME/",        "search_type": "vgsi", "platform_config": {}, "active": True},
    {"state": "ME", "county": "York",         "municipality": "ogunquit",        "municipality_display": "Ogunquit",        "search_url": "https://gis.vgsi.com/OgunquitME/",       "search_type": "vgsi", "platform_config": {}, "active": True},
    {"state": "ME", "county": "York",         "municipality": "wells",           "municipality_display": "Wells",           "search_url": "https://gis.vgsi.com/wellsme/",          "search_type": "vgsi", "platform_config": {}, "active": True},
    {"state": "ME", "county": "York",         "municipality": "york",            "municipality_display": "York",            "search_url": "https://gis.vgsi.com/yorkme/",           "search_type": "vgsi", "platform_config": {}, "active": True},

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

    # ── Maine / Patriot Properties (WebPro) ─────────────────────────────────
    # Note: the CSV lists auburnme.patriotproperties.com but that subdomain now
    # redirects to a marketing page. The canonical live URL uses "auburnmaine".
    {"state": "ME", "county": "Androscoggin", "municipality": "auburn",  "municipality_display": "Auburn",  "search_url": "https://auburnmaine.patriotproperties.com", "search_type": "patriot", "platform_config": {}, "active": True},
    {"state": "ME", "county": "Knox",         "municipality": "rockport", "municipality_display": "Rockport", "search_url": "https://rockport.patriotproperties.com",   "search_type": "patriot", "platform_config": {}, "active": True},

    # ── Maine / Harris Computer Systems RE Online ─────────────────────────────
    {"state": "ME", "county": "Kennebec", "municipality": "readfield", "municipality_display": "Readfield", "search_url": "http://reonline.harriscomputer.com/research.aspx?clientid=1007", "search_type": "harris", "platform_config": {}, "active": True},

    # ── Maine / AxisGIS (CAI Technologies) ───────────────────────────────────
    # Camden (Knox) is seeded at the top of this list as axisgis with vgsi_url set,
    # so VGSI is tried first and AxisGIS PDF is the fallback.
    # All entries below use auto-probe (no cama_vendor) since vendor is unknown.
    # Two entries use next.axisgis.com instead of www.axisgis.com.
    # Kennebec County
    {"state": "ME", "county": "Kennebec",  "municipality": "china",          "municipality_display": "China",          "search_url": "https://www.axisgis.com/ChinaME/",            "search_type": "axisgis", "platform_config": {"municipality_id": "ChinaME"},          "active": True},
    # Knox County
    {"state": "ME", "county": "Knox",      "municipality": "union",          "municipality_display": "Union",          "search_url": "https://www.axisgis.com/UnionME/",            "search_type": "axisgis", "platform_config": {"municipality_id": "UnionME"},          "active": True},
    {"state": "ME", "county": "Knox",      "municipality": "warren",         "municipality_display": "Warren",         "search_url": "https://www.axisgis.com/WarrenME/",           "search_type": "axisgis", "platform_config": {"municipality_id": "WarrenME"},         "active": True},
    # Lincoln County
    {"state": "ME", "county": "Lincoln",   "municipality": "newcastle",      "municipality_display": "Newcastle",      "search_url": "https://www.axisgis.com/NewcastleME/",        "search_type": "axisgis", "platform_config": {"municipality_id": "NewcastleME"},      "active": True},
    {"state": "ME", "county": "Lincoln",   "municipality": "westport island","municipality_display": "Westport Island","search_url": "https://next.axisgis.com/Westport_IslandME/","search_type": "axisgis", "platform_config": {"municipality_id": "Westport_IslandME"},"active": True},
    {"state": "ME", "county": "Lincoln",   "municipality": "wiscasset",      "municipality_display": "Wiscasset",      "search_url": "https://www.axisgis.com/wiscassetme/",        "search_type": "axisgis", "platform_config": {"municipality_id": "wiscassetme"},      "active": True},
    # Oxford County
    {"state": "ME", "county": "Oxford",    "municipality": "brownfield",     "municipality_display": "Brownfield",     "search_url": "https://www.axisgis.com/brownfieldme/",       "search_type": "axisgis", "platform_config": {"municipality_id": "brownfieldme"},     "active": True},
    {"state": "ME", "county": "Oxford",    "municipality": "fryeburg",       "municipality_display": "Fryeburg",       "search_url": "https://www.axisgis.com/fryeburgme/",         "search_type": "axisgis", "platform_config": {"municipality_id": "fryeburgme"},       "active": True},
    {"state": "ME", "county": "Oxford",    "municipality": "oxford",         "municipality_display": "Oxford",         "search_url": "https://www.axisgis.com/oxfordme/",           "search_type": "axisgis", "platform_config": {"municipality_id": "oxfordme"},         "active": True},
    {"state": "ME", "county": "Oxford",    "municipality": "porter",         "municipality_display": "Porter",         "search_url": "https://www.axisgis.com/PorterME/",           "search_type": "axisgis", "platform_config": {"municipality_id": "PorterME"},         "active": True},
    # Penobscot County
    {"state": "ME", "county": "Penobscot", "municipality": "brewer",         "municipality_display": "Brewer",         "search_url": "https://www.axisgis.com/brewerme/",           "search_type": "axisgis", "platform_config": {"municipality_id": "brewerme"},         "active": True},
    {"state": "ME", "county": "Penobscot", "municipality": "hampden",        "municipality_display": "Hampden",        "search_url": "https://www.axisgis.com/hampdenme/",          "search_type": "axisgis", "platform_config": {"municipality_id": "hampdenme"},        "active": True},
    {"state": "ME", "county": "Penobscot", "municipality": "lincoln",        "municipality_display": "Lincoln",        "search_url": "https://www.axisgis.com/LincolnME/",          "search_type": "axisgis", "platform_config": {"municipality_id": "LincolnME"},        "active": True},
    {"state": "ME", "county": "Penobscot", "municipality": "old town",       "municipality_display": "Old Town",       "search_url": "https://www.axisgis.com/Old_TownME/",         "search_type": "axisgis", "platform_config": {"municipality_id": "Old_TownME"},       "active": True},
    # Somerset County
    {"state": "ME", "county": "Somerset",  "municipality": "fairfield",      "municipality_display": "Fairfield",      "search_url": "https://www.axisgis.com/FairfieldME/",        "search_type": "axisgis", "platform_config": {"municipality_id": "FairfieldME"},      "active": True},
    # Washington County
    {"state": "ME", "county": "Washington","municipality": "calais",         "municipality_display": "Calais",         "search_url": "https://www.axisgis.com/CalaisME/",           "search_type": "axisgis", "platform_config": {"municipality_id": "CalaisME"},         "active": True},
    {"state": "ME", "county": "Washington","municipality": "east machias",   "municipality_display": "East Machias",   "search_url": "https://next.axisgis.com/East_MachiasME/",   "search_type": "axisgis", "platform_config": {"municipality_id": "East_MachiasME"},   "active": True},
    # York County
    {"state": "ME", "county": "York",      "municipality": "kennebunkport",  "municipality_display": "Kennebunkport",  "search_url": "https://www.axisgis.com/kennebunkportme/",    "search_type": "axisgis", "platform_config": {"municipality_id": "kennebunkportme"},  "active": True},
    {"state": "ME", "county": "York",      "municipality": "sanford",        "municipality_display": "Sanford",        "search_url": "https://www.axisgis.com/sanfordme/",          "search_type": "axisgis", "platform_config": {"municipality_id": "sanfordme"},        "active": True},
    {"state": "ME", "county": "York",      "municipality": "south berwick",  "municipality_display": "South Berwick",  "search_url": "https://www.axisgis.com/south_berwickme/",    "search_type": "axisgis", "platform_config": {"municipality_id": "south_berwickme"},  "active": True},
    {"state": "ME", "county": "York",      "municipality": "waterboro",      "municipality_display": "Waterboro",      "search_url": "https://www.axisgis.com/WaterboroME/",        "search_type": "axisgis", "platform_config": {"municipality_id": "WaterboroME"},      "active": True},

    # ── Maine / O'Donnell & Associates ───────────────────────────────────────
    # Androscoggin County
    {"state": "ME", "county": "Androscoggin", "municipality": "livermore",       "municipality_display": "Livermore",       "search_url": "https://jeodonnell.com/cama/livermore/",       "search_type": "odonnell", "platform_config": {"slug": "livermore"},       "active": True},
    {"state": "ME", "county": "Androscoggin", "municipality": "livermore falls",  "municipality_display": "Livermore Falls",  "search_url": "https://jeodonnell.com/cama/livermore-falls/", "search_type": "odonnell", "platform_config": {"slug": "livermore-falls"}, "active": True},
    {"state": "ME", "county": "Androscoggin", "municipality": "mechanic falls",   "municipality_display": "Mechanic Falls",   "search_url": "https://jeodonnell.com/cama/mechanic-falls/", "search_type": "odonnell", "platform_config": {"slug": "mechanic-falls"}, "active": True},
    {"state": "ME", "county": "Androscoggin", "municipality": "minot",            "municipality_display": "Minot",            "search_url": "https://jeodonnell.com/cama/minot/",           "search_type": "odonnell", "platform_config": {"slug": "minot"},           "active": True},
    {"state": "ME", "county": "Androscoggin", "municipality": "turner",           "municipality_display": "Turner",           "search_url": "https://jeodonnell.com/cama/turner/",          "search_type": "odonnell", "platform_config": {"slug": "turner"},          "active": True},
    {"state": "ME", "county": "Androscoggin", "municipality": "wales",            "municipality_display": "Wales",            "search_url": "https://jeodonnell.com/cama/wales/",           "search_type": "odonnell", "platform_config": {"slug": "wales"},           "active": True},
    # Cumberland County
    {"state": "ME", "county": "Cumberland",   "municipality": "bridgton",         "municipality_display": "Bridgton",         "search_url": "https://jeodonnell.com/cama/bridgton/",        "search_type": "odonnell", "platform_config": {"slug": "bridgton"},        "active": True},
    {"state": "ME", "county": "Cumberland",   "municipality": "naples",           "municipality_display": "Naples",           "search_url": "https://jeodonnell.com/cama/naples/",          "search_type": "odonnell", "platform_config": {"slug": "naples"},          "active": True},
    {"state": "ME", "county": "Cumberland",   "municipality": "new gloucester",   "municipality_display": "New Gloucester",   "search_url": "https://jeodonnell.com/cama/new-gloucester/", "search_type": "odonnell", "platform_config": {"slug": "new-gloucester"}, "active": True},
    {"state": "ME", "county": "Cumberland",   "municipality": "sebago",           "municipality_display": "Sebago",           "search_url": "https://jeodonnell.com/cama/sebago/",          "search_type": "odonnell", "platform_config": {"slug": "sebago"},          "active": True},
    # Franklin County
    {"state": "ME", "county": "Franklin",     "municipality": "andover",          "municipality_display": "Andover",          "search_url": "https://jeodonnell.com/cama/andover/",         "search_type": "odonnell", "platform_config": {"slug": "andover"},         "active": True},
    {"state": "ME", "county": "Franklin",     "municipality": "carthage",         "municipality_display": "Carthage",         "search_url": "https://jeodonnell.com/cama/carthage/",        "search_type": "odonnell", "platform_config": {"slug": "carthage"},        "active": True},
    {"state": "ME", "county": "Franklin",     "municipality": "jay",              "municipality_display": "Jay",              "search_url": "https://jeodonnell.com/cama/jay/",             "search_type": "odonnell", "platform_config": {"slug": "jay"},             "active": True},
    {"state": "ME", "county": "Franklin",     "municipality": "temple",           "municipality_display": "Temple",           "search_url": "https://jeodonnell.com/cama/temple/",          "search_type": "odonnell", "platform_config": {"slug": "temple"},          "active": True},
    {"state": "ME", "county": "Franklin",     "municipality": "weld",             "municipality_display": "Weld",             "search_url": "https://jeodonnell.com/cama/weld/",            "search_type": "odonnell", "platform_config": {"slug": "weld"},            "active": True},
    {"state": "ME", "county": "Franklin",     "municipality": "wilton",           "municipality_display": "Wilton",           "search_url": "https://jeodonnell.com/cama/wilton/",          "search_type": "odonnell", "platform_config": {"slug": "wilton"},          "active": True},
    # Lincoln County
    {"state": "ME", "county": "Lincoln",      "municipality": "alna",             "municipality_display": "Alna",             "search_url": "https://jeodonnell.com/cama/alna/",            "search_type": "odonnell", "platform_config": {"slug": "alna"},            "active": True},
    {"state": "ME", "county": "Lincoln",      "municipality": "boothbay",         "municipality_display": "Boothbay",         "search_url": "https://jeodonnell.com/cama/boothbay/",        "search_type": "odonnell", "platform_config": {"slug": "boothbay"},        "active": True},
    {"state": "ME", "county": "Lincoln",      "municipality": "edgecomb",         "municipality_display": "Edgecomb",         "search_url": "https://jeodonnell.com/cama/edgecomb/",        "search_type": "odonnell", "platform_config": {"slug": "edgecomb"},        "active": True},
    # Oxford County
    {"state": "ME", "county": "Oxford",       "municipality": "canton",           "municipality_display": "Canton",           "search_url": "https://jeodonnell.com/cama/canton/",          "search_type": "odonnell", "platform_config": {"slug": "canton"},          "active": True},
    {"state": "ME", "county": "Oxford",       "municipality": "dixfield",         "municipality_display": "Dixfield",         "search_url": "https://jeodonnell.com/cama/dixfield/",        "search_type": "odonnell", "platform_config": {"slug": "dixfield"},        "active": True},
    {"state": "ME", "county": "Oxford",       "municipality": "gilead",           "municipality_display": "Gilead",           "search_url": "https://jeodonnell.com/cama/gilead/",          "search_type": "odonnell", "platform_config": {"slug": "gilead"},          "active": True},
    {"state": "ME", "county": "Oxford",       "municipality": "greenwood",        "municipality_display": "Greenwood",        "search_url": "https://jeodonnell.com/cama/greenwood/",       "search_type": "odonnell", "platform_config": {"slug": "greenwood"},       "active": True},
    {"state": "ME", "county": "Oxford",       "municipality": "hanover",          "municipality_display": "Hanover",          "search_url": "https://jeodonnell.com/cama/hanover/",         "search_type": "odonnell", "platform_config": {"slug": "hanover"},         "active": True},
    {"state": "ME", "county": "Oxford",       "municipality": "hartford",         "municipality_display": "Hartford",         "search_url": "https://jeodonnell.com/cama/hartford/",        "search_type": "odonnell", "platform_config": {"slug": "hartford"},        "active": True},
    {"state": "ME", "county": "Oxford",       "municipality": "hebron",           "municipality_display": "Hebron",           "search_url": "https://jeodonnell.com/cama/hebron/",          "search_type": "odonnell", "platform_config": {"slug": "hebron"},          "active": True},
    {"state": "ME", "county": "Oxford",       "municipality": "otisfield",        "municipality_display": "Otisfield",        "search_url": "https://jeodonnell.com/cama/otisfield/",       "search_type": "odonnell", "platform_config": {"slug": "otisfield"},       "active": True},
    {"state": "ME", "county": "Oxford",       "municipality": "stow",             "municipality_display": "Stow",             "search_url": "https://jeodonnell.com/cama/stow-me/",         "search_type": "odonnell", "platform_config": {"slug": "stow-me"},         "active": True},
    {"state": "ME", "county": "Oxford",       "municipality": "sumner",           "municipality_display": "Sumner",           "search_url": "https://jeodonnell.com/cama/sumner/",          "search_type": "odonnell", "platform_config": {"slug": "sumner"},          "active": True},
    {"state": "ME", "county": "Oxford",       "municipality": "sweden",           "municipality_display": "Sweden",           "search_url": "https://jeodonnell.com/cama/sweden/",          "search_type": "odonnell", "platform_config": {"slug": "sweden"},          "active": True},
    {"state": "ME", "county": "Oxford",       "municipality": "woodstock",        "municipality_display": "Woodstock",        "search_url": "https://jeodonnell.com/cama/woodstock/",       "search_type": "odonnell", "platform_config": {"slug": "woodstock"},       "active": True},
    # York County
    {"state": "ME", "county": "York",         "municipality": "acton",            "municipality_display": "Acton",            "search_url": "https://jeodonnell.com/cama/acton/",           "search_type": "odonnell", "platform_config": {"slug": "acton"},           "active": True},
    {"state": "ME", "county": "York",         "municipality": "alfred",           "municipality_display": "Alfred",           "search_url": "https://jeodonnell.com/cama/alfred/",          "search_type": "odonnell", "platform_config": {"slug": "alfred"},          "active": True},
    {"state": "ME", "county": "York",         "municipality": "lebanon",          "municipality_display": "Lebanon",          "search_url": "https://jeodonnell.com/cama/lebanon/",         "search_type": "odonnell", "platform_config": {"slug": "lebanon"},         "active": True},
    {"state": "ME", "county": "York",         "municipality": "limerick",         "municipality_display": "Limerick",         "search_url": "https://jeodonnell.com/cama/limerick/",        "search_type": "odonnell", "platform_config": {"slug": "limerick"},        "active": True},
    {"state": "ME", "county": "York",         "municipality": "shapleigh",        "municipality_display": "Shapleigh",        "search_url": "https://jeodonnell.com/cama/shapleigh/",       "search_type": "odonnell", "platform_config": {"slug": "shapleigh"},       "active": True},
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
    """Upsert seed municipalities by (state, municipality) key.

    Runs on every startup so platform corrections in SEED_MUNICIPALITIES
    (e.g. search_type / search_url / platform_config changes) propagate to
    existing databases without requiring a collection drop.

    ``platform_config`` is written via ``$set`` so that corrections to seed
    values (e.g. switching Camden from vgsi to axisgis) propagate on restart.
    Admin-enriched sub-keys (e.g. qPublic ``search_page_url``) are preserved
    via ``$set`` on the specific seed keys using dot-notation merge rather than
    replacing the whole dict, so extra keys added by admin tooling survive.
    """
    now = datetime.now(timezone.utc)
    for m in SEED_MUNICIPALITIES:
        seed_config = m.get("platform_config", {})
        # Build dot-notation $set entries for each platform_config key so we
        # overwrite only the keys present in seed, leaving any extra admin-added
        # keys (e.g. search_page_url) untouched.
        config_set = {f"platform_config.{k}": v for k, v in seed_config.items()}
        await municipalities().update_one(
            {"state": m["state"], "municipality": m["municipality"]},
            {
                "$set": {
                    "county": m.get("county", ""),
                    "municipality_display": m["municipality_display"],
                    "search_url": m["search_url"],
                    "search_type": m["search_type"],
                    "active": m.get("active", True),
                    "added_by": "seed",
                    **config_set,
                },
                "$setOnInsert": {
                    "date_added": now,
                },
            },
            upsert=True,
        )

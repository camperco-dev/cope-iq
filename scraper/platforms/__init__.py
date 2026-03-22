from .vgsi import VGSIPlatform
from .qpublic import QPublicPlatform
from .odonnell import OdonnellPlatform
from .patriot import PatriotPlatform
from .tyler import TylerPlatform
from .harris import HarrisPlatform
from .base import PropertyPlatform

PLATFORM_REGISTRY: dict[str, PropertyPlatform] = {
    "vgsi":     VGSIPlatform(),
    "qpublic":  QPublicPlatform(),
    "odonnell": OdonnellPlatform(),
    "patriot":  PatriotPlatform(),
    "tyler":    TylerPlatform(),
    "harris":   HarrisPlatform(),
}

__all__ = ["PLATFORM_REGISTRY", "PropertyPlatform"]

from .vgsi import VGSIPlatform
from .qpublic import QPublicPlatform
from .base import PropertyPlatform

PLATFORM_REGISTRY: dict[str, PropertyPlatform] = {
    "vgsi":    VGSIPlatform(),
    "qpublic": QPublicPlatform(),
}

__all__ = ["PLATFORM_REGISTRY", "PropertyPlatform"]

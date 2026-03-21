from abc import ABC, abstractmethod
import httpx


class PropertyPlatform(ABC):
    """
    Abstract base for all property card scraper platforms.

    Each concrete subclass handles one vendor's HTTP interface
    (search API, form POST, etc.) and URL patterns for media assets.

    The httpx.AsyncClient is provided by the dispatcher so connection
    pooling and SSL settings are owned in one place.
    """

    @abstractmethod
    async def fetch(
        self,
        base_url: str,
        address: str,
        street: str | None,
        platform_config: dict,
        client: httpx.AsyncClient,
    ) -> tuple[str, str, str, str]:
        """
        Locate and retrieve a property card.

        Args:
            base_url:        Root URL of the municipality's assessor site.
            address:         Full geocoded address (city/state included).
            street:          Street-only portion from geocoder; use for search
                             queries when the platform is sensitive to city/state noise.
            platform_config: Arbitrary dict from the municipality document;
                             holds platform-specific params (app IDs, county codes, etc.).
            client:          Shared httpx.AsyncClient — do not create your own.

        Returns:
            (pid, matched_address, html, parcel_url)
            - pid:             Platform's unique parcel/property identifier string.
            - matched_address: The address string as the platform returned it.
            - html:            Raw HTML of the property detail page.
            - parcel_url:      Canonical URL of the property detail page.

        Raises:
            ValueError:       Address not found or ambiguous (no results).
            httpx.HTTPError:  Network or HTTP-level failure.
        """

    @abstractmethod
    def extract_photo_url(self, html: str, base_url: str) -> str | None:
        """
        Extract the property photo URL from raw HTML before tag-stripping.
        Return None if no photo is present.
        """

    @abstractmethod
    def extract_sketch_url(self, html: str, base_url: str) -> str | None:
        """
        Extract the building sketch/floorplan URL from raw HTML before tag-stripping.
        Return None if no sketch is present.
        """

    def extraction_hints(self) -> str:
        """
        Optional platform-specific guidance injected into the Claude system prompt.
        Override when this platform uses field names or layouts that deviate from
        the VGSI baseline the prompt was written against.
        Default: empty string (no injection).
        """
        return ""

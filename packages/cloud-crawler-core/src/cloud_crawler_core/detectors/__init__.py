"""The detector registry. Detector ids are only ever added, never renamed (README, "Rules that do not bend")."""

from cloud_crawler_core.detectors.base import ANY_TYPE, Detector, Reading, compare
from cloud_crawler_core.detectors.governance import REGION_ALLOWED, SKU_ALLOWED, TAG_REQUIRED
from cloud_crawler_core.detectors.identity import MANAGED_IDENTITY
from cloud_crawler_core.detectors.network_access import PRIVATE_ENDPOINT_PRESENT, PUBLIC_ACCESS_DISABLED
from cloud_crawler_core.detectors.zone_redundancy import ZONE_REDUNDANCY

DETECTORS: dict[str, Detector] = {
    detector.detector_id: detector
    for detector in (
        ZONE_REDUNDANCY,
        PUBLIC_ACCESS_DISABLED,
        PRIVATE_ENDPOINT_PRESENT,
        MANAGED_IDENTITY,
        TAG_REQUIRED,
        SKU_ALLOWED,
        REGION_ALLOWED,
    )
}


def get_detector(detector_id: str) -> Detector:
    try:
        return DETECTORS[detector_id]
    except KeyError:
        raise KeyError(f"unknown detector {detector_id!r}; known: {sorted(DETECTORS)}") from None


__all__ = ["ANY_TYPE", "DETECTORS", "Detector", "Reading", "compare", "get_detector"]

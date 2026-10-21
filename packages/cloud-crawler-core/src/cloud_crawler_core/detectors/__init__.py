"""The detector registry. Detector ids are only ever added, never renamed (README, "Rules that do not bend").

Two shapes share the registry: `Detector` reads normalised resource rows (one reading per resource), `EvidenceDetector`
reads normalised Azure MCP observations (one answer per claim). The drift engine dispatches on the shape."""

from cloud_crawler_core.detectors.azure_observations import (
    ADVISOR_FINDINGS,
    POLICY_ASSIGNMENT_PRESENT,
    RETIREMENT_EXPOSURE,
)
from cloud_crawler_core.detectors.base import ANY_TYPE, Detector, EvidenceDetector, Reading, compare
from cloud_crawler_core.detectors.governance import REGION_ALLOWED, SKU_ALLOWED, TAG_REQUIRED
from cloud_crawler_core.detectors.identity import MANAGED_IDENTITY
from cloud_crawler_core.detectors.network_access import PRIVATE_ENDPOINT_PRESENT, PUBLIC_ACCESS_DISABLED
from cloud_crawler_core.detectors.zone_redundancy import ZONE_REDUNDANCY

DETECTORS: dict[str, Detector | EvidenceDetector] = {
    detector.detector_id: detector
    for detector in (
        ZONE_REDUNDANCY,
        PUBLIC_ACCESS_DISABLED,
        PRIVATE_ENDPOINT_PRESENT,
        MANAGED_IDENTITY,
        TAG_REQUIRED,
        SKU_ALLOWED,
        REGION_ALLOWED,
        ADVISOR_FINDINGS,
        RETIREMENT_EXPOSURE,
        POLICY_ASSIGNMENT_PRESENT,
    )
}


def get_detector(detector_id: str) -> Detector | EvidenceDetector:
    try:
        return DETECTORS[detector_id]
    except KeyError:
        raise KeyError(f"unknown detector {detector_id!r}; known: {sorted(DETECTORS)}") from None


__all__ = ["ANY_TYPE", "DETECTORS", "Detector", "EvidenceDetector", "Reading", "compare", "get_detector"]

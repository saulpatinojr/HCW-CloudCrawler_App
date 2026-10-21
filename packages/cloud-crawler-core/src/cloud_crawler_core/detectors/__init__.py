"""The detector registry. Detector ids are only ever added, never renamed (README, "Rules that do not bend")."""

from cloud_crawler_core.detectors.base import Detector, Reading
from cloud_crawler_core.detectors.zone_redundancy import ZONE_REDUNDANCY

DETECTORS: dict[str, Detector] = {
    ZONE_REDUNDANCY.detector_id: ZONE_REDUNDANCY,
}


def get_detector(detector_id: str) -> Detector:
    try:
        return DETECTORS[detector_id]
    except KeyError:
        raise KeyError(f"unknown detector {detector_id!r}; known: {sorted(DETECTORS)}") from None


__all__ = ["DETECTORS", "Detector", "Reading", "get_detector"]

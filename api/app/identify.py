"""STUB. Owner: identify agent.

photo(): MODEL_VISION structured output constrained to catalog bikes -> candidates.
vin(): OCR not needed here (client sends text); NHTSA vPIC DecodeVinValues -> catalog bike.
part(): classify a part photo into the 30 labels of AswinG5/moto-parts-30cls.
"""

from .models import IdentifyResponse, PartClass


def photo(image: bytes, mime: str) -> IdentifyResponse:
    raise NotImplementedError


def vin(vin: str) -> IdentifyResponse:
    raise NotImplementedError


def part(image: bytes, mime: str) -> list[PartClass]:
    raise NotImplementedError

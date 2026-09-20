"""STUB. Owner: parts-backend agent.

Live retailer offers for one part of one manual, fetched on first click and cached in the store.
  offers(manual_id, part_id, bike) -> OffersResult
Search: OpenAI Responses API with the built-in web_search tool (settings.model_offers), query built from the
part's OEM number when printed, else the spec string + make/model/year (fitment-exact), constrained to real
retailer product pages (RevZilla, Partzilla, Amazon, eBay, FC-Moto, Louis, Polo, the OEM's own shop);
structured output -> offers[{retailer, title, price, currency, url, variant, condition, shipping, inStock}].
Never invent a price: every offer must carry the URL it came from; drop offers without a price or URL.
Cache: store.put_offers(manual_id, part_id, result) with fetchedAt; serve cached when < 24 h old.
"""

from pydantic import BaseModel

from .models import Bike


class Offer(BaseModel):
    retailer: str
    title: str
    price: float
    currency: str
    url: str
    variant: str | None = None
    condition: str | None = None
    shipping: str | None = None
    inStock: bool | None = None


class OffersResult(BaseModel):
    manualId: str
    partId: str
    query: str
    offers: list[Offer]
    fetchedAt: float
    usd: float = 0.0


def offers(manual_id: str, part_id: str, bike: Bike | None) -> OffersResult:
    raise NotImplementedError

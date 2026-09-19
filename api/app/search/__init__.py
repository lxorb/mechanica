"""Search index over manual sections. ElasticSearchIndex (search/elastic.py) when ES_URL is set, else LocalIndex (search/local.py)."""

from typing import Protocol

from pydantic import BaseModel

from ..config import settings
from ..models import Manual, Page, Spec


class Hit(BaseModel):
    sectionId: str
    score: float


class SpecHit(BaseModel):
    spec: Spec
    score: float


class Index(Protocol):
    def index(self, manual: Manual, pages: list[Page], specs: list[Spec]) -> None: ...
    def remove(self, manual_id: str) -> None: ...
    def query(self, manual_id: str, queries: list[str], components: list[str] | None = None, k: int = 8) -> list[Hit]: ...
    def spec(self, manual_id: str, name: str, kind: str | None = None, k: int = 5) -> list[SpecHit]: ...


_index: Index | None = None


def get_index() -> Index:
    global _index
    if _index is None:
        if settings.es_url:
            from .elastic import ElasticIndex

            _index = ElasticIndex(settings.es_url, settings.es_api_key)
        else:
            from .local import LocalIndex

            _index = LocalIndex()
    return _index

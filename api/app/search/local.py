"""STUB. Owner: search agent. BM25 over section text + keywords, in memory, rebuilt from the store on first use."""

from ..models import Manual, Page, Spec
from . import Hit, SpecHit


class LocalIndex:
    def index(self, manual: Manual, pages: list[Page], specs: list[Spec]) -> None:
        raise NotImplementedError

    def remove(self, manual_id: str) -> None:
        raise NotImplementedError

    def query(self, manual_id: str, queries: list[str], components: list[str] | None = None, k: int = 8) -> list[Hit]:
        raise NotImplementedError

    def spec(self, manual_id: str, name: str, kind: str | None = None, k: int = 5) -> list[SpecHit]:
        raise NotImplementedError

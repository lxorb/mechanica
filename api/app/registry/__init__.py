"""STUB. Owner: registry agent.

One adapter per OEM portal returning RegistryEntry rows (where the official manual lives, free or not).
crawl() stores them; bikes_from_registry() derives catalog Bikes; free_owner_manuals() lists ingestable PDFs.
"""

from collections.abc import Callable, Iterable

from ..models import Bike, RegistryEntry

ADAPTERS: dict[str, Callable[[], Iterable[RegistryEntry]]] = {}


def crawl(brands: list[str] | None = None) -> int:
    raise NotImplementedError


def bikes_from_registry() -> list[Bike]:
    raise NotImplementedError


def free_owner_manuals(make: str | None = None, limit: int = 20) -> list[RegistryEntry]:
    raise NotImplementedError

"""What kind of document a row actually points at, decided from its url and title alone.

OEM portals hand out brochures, warranty inserts, quick-reference cards and infotainment guides from
the same listings as the handbook - the Gold Wing brochure at /goldwing/brochure_pdf_files/ is filed
next to the owner's manual - so a row that says "owner" is not one. Nothing here opens a PDF: the
path and the title carry the answer, and guessing from bytes would cost a download per row.

Order matters. The url is read first because it is the publisher's own filing, and within it the
narrow kinds win over the broad ones: "customer-service/owners-manual" is an owner's manual, not a
service manual, because `owner` is checked before `service`."""

from __future__ import annotations

import re

# docKind -> the word prefixes that name it. Matched per word, so "brochure_pdf_files" -> brochure
# and "accessories" -> accessor, while "inspection" never reaches "spec".
KINDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("brochure", ("brochure", "catalog", "catalogue", "accessor", "prospekt", "lineup")),
    ("warranty", ("warranty", "warrant", "wrty", "guarantee")),
    ("quickstart", ("quickstart", "quickguide", "quickreference", "quick", "qrg", "qsg", "gettingstarted")),
    ("infotainment", ("infotainment", "infotain", "navi", "navigation", "connectivity", "multimedia")),
    ("supplement", ("supplement", "addendum", "addend", "insert")),
    ("spec", ("spec", "specification", "specs")),
    ("owner", ("owner", "owners", "rider", "riders", "handbook", "bedienungsanleitung", "instruction")),
    # no "maintenance" here: "use and maintenance booklet" is what Piaggio and MV Agusta call the
    # owner's manual, and the word would drag every one of them into the service bucket.
    ("service", ("service", "shop", "repair", "workshop", "wiring")),
)
WORDS = re.compile(r"[^a-z0-9]+")


def _words(text: str) -> list[str]:
    return [w for w in WORDS.split((text or "").lower()) if w]


def _match(text: str) -> str | None:
    words = _words(text)
    if not words:
        return None
    for kind, prefixes in KINDS:
        if any(w.startswith(p) for w in words for p in prefixes):
            return kind
    return None


def classify_doc(url: str, title: str | None = None) -> str:
    """owner | service | quickstart | brochure | warranty | supplement | infotainment | spec.

    A row nothing identifies is an owner's manual: that is what these portals mostly publish, and
    the ranking in _pick() puts a real owner row ahead of it anyway."""
    path = url.split("://", 1)[-1].split("?", 1)[0]
    return _match(path) or _match(title or "") or "owner"

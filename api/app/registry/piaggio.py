"""Piaggio group - Aprilia, Moto Guzzi, Vespa, Piaggio. A dead end, written down so it stays closed.

All four `manuals.<brand>.com` hosts run the same ASP.NET app (`DigitalLUMApp`, `controllers/
default.js?v5.6`, identical reCAPTCHA site key `6Ld7JggkAAAAAK7zXXMRXocxl0OLN3EBPUVTui-5`). It is not
a manual portal; it is a lead form. Checked 2026-09-20, in a real browser, on all four:

* The only page is one form: `lingua, nome, cognome, email, nazione, cap, telaio` (frame number),
  two privacy checkboxes, SEND. There is no model list, no year list and no document list anywhere -
  `GetFormLingue` returns the 13 UI languages, `GetNazioni` the countries, and that is the whole API
  surface a guest can reach (`GetCollegamenti` and `VerificaSistema` need the page's own state).
* Submitting runs `grecaptcha.execute(...)` -> `POST default.aspx/ValidateReCaptcha` -> `POST
  default.aspx/InsertForm`, and `InsertForm` answers `{errore, msg}` - a status, never a URL. The
  manual is **emailed** to the address on the form. There is no response path that carries a PDF, so
  there is nothing for `dynamic.RESOLVERS` to return and no `resolve(bike, vin)` is registered.
* httpx gets 403 from Akamai on all four hosts with any User-Agent; a headful browser gets in. That
  does not matter here, because what is behind the wall is the form and nothing else.

The rest of the group's estate was checked too: `www.{piaggio,vespa,aprilia,motoguzzi}.com/…/app/
manual/` render nothing without the phone app, and `wlassets.piaggio.com` (which *does* serve PDFs
to plain httpx - brochures, warranty letters) carries no owner's manuals.

So the four rows below are all this module can honestly claim: where the manual is, and the fact
that a frame number and an email address are the price of it. They are deliberately not PDFs, so
`free_owner_manuals()` will never queue them for unattended ingest.
"""

from __future__ import annotations

from collections.abc import Iterable

from ..models import RegistryEntry
from ._http import keep_lang, slug

PORTALS = (
    ("Aprilia", "manuals.aprilia.com"),
    ("Moto Guzzi", "manuals.motoguzzi.com"),
    ("Vespa", "manuals.vespa.com"),
    ("Piaggio", "manuals.piaggio.com"),
)
ALL = "All models"
NOTE = "Owner's manual request form - frame number plus e-mail, the PDF arrives by e-mail"


def rows() -> Iterable[RegistryEntry]:
    if not keep_lang("en"):
        return
    for make, site in PORTALS:
        yield RegistryEntry(
            id=slug(site, make, "ww", "en", "owner"),
            make=make,
            model=ALL,
            years=[],
            market="WW",
            type="owner",
            lang="en",
            url=f"https://{site}/",
            access="free",
            site=site,
            title=f"{make} {NOTE}",
            needsUa="browser",
        )

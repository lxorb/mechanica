"""Where the workshop manual lives when it is not free. One static row per brand and market, so the
registry can answer "can I even get this?" without a crawl. Prices checked 2026-09-19."""

from __future__ import annotations

from collections.abc import Iterable

from ..models import RegistryEntry
from ._http import slug

ALL = "All models"

ROWS = [
    ("Honda", "US", "helminc.com", "https://www.helminc.com/helm/Result.asp?session=&style=helm&Company=hon", "paid", "print $50-125"),
    ("Yamaha", "US", "yamahapubs.com", "https://www.yamahapubs.com/", "paid", "eBook $14.99 / 30 days, print $99"),
    ("Kawasaki", "US", "kawasaki.com", "https://www.kawasaki.com/en-us/owner-center/service-manuals", "paid", "print ~$90"),
    ("Suzuki", "US", "genuinesuzukimanuals.com", "https://www.genuinesuzukimanuals.com/", "paid", "~$90"),
    ("KTM", "EU", "print.ktm.com", "https://print.ktm.com/", "paid", "PDF ~EUR 25-31"),
    ("Husqvarna", "EU", "print.ktm.com", "https://print.ktm.com/", "paid", "PDF ~EUR 25-31"),
    ("GasGas", "EU", "print.ktm.com", "https://print.ktm.com/", "paid", "PDF ~EUR 25-31"),
    ("Harley-Davidson", "US", "serviceinfo.harley-davidson.com", "https://serviceinfo.harley-davidson.com/", "subscription", "subscription"),
    ("BMW", "EU", "aos.bmwgroup.com", "https://aos.bmwgroup.com/", "subscription", "EUR 9 / hour"),
    ("Triumph", "GB", "triumphtechnicalinformation.com", "https://www.triumphtechnicalinformation.com/", "subscription", "GBP 5.99 / month per bike"),
    ("Ducati", "EU", "rmi.ducati.com", "https://rmi.ducati.com/", "dealer", "professionals only"),
    ("Piaggio", "EU", "rmiportal.piaggiogroup.com", "https://rmiportal.piaggiogroup.com/", "dealer", "professionals only"),
    ("Moto Guzzi", "EU", "rmiportal.piaggiogroup.com", "https://rmiportal.piaggiogroup.com/", "dealer", "professionals only"),
    ("Aprilia", "EU", "rmiportal.piaggiogroup.com", "https://rmiportal.piaggiogroup.com/", "dealer", "professionals only"),
    ("Royal Enfield", "IN", "royalenfield.com", "https://www.royalenfield.com/in/en/dealers/", "dealer", "dealer only"),
]


def service_manuals() -> Iterable[RegistryEntry]:
    for make, market, site, url, access, price in ROWS:
        yield RegistryEntry(
            id=slug(site, make, market, "en", "service"),
            make=make,
            model=ALL,
            years=[],
            market=market,
            type="service",
            lang="en",
            url=url,
            access=access,
            price=price,
            site=site,
            title=f"{make} service manuals ({market})",
        )

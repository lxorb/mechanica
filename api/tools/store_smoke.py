"""Round-trip every Store method against MongoDB. UNVERIFIED: no Mongo was reachable when this was written.

    MONGODB_URI="mongodb+srv://..." api/.venv/Scripts/python -m tools.store_smoke        # run from api/
    MONGODB_URI=... python -m tools.store_smoke --keep                                    # leave the db behind

Writes into db `ttm_smoke` (override with SMOKE_DB) and drops it at the end unless --keep.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models import (  # noqa: E402
    Bike,
    CostEvent,
    Highlight,
    IngestJob,
    Link,
    Manual,
    OutlineNode,
    Page,
    Part,
    RegistryEntry,
    Section,
    Spec,
)
from app.store_mongo import MongoStore  # noqa: E402

MID = "smoke-390-duke-2024-om"
BID = "smoke-390-duke-2024"

BIKE = Bike(id=BID, make="KTM", model="390 Duke", year=2024, market="EU", manualId=MID, vins=["VBKJ"], cues=["orange"])
MANUAL = Manual(
    id=MID,
    bikeIds=[BID],
    file=f"/manuals/{MID}/file",
    pages=143,
    title="390 DUKE Owner's Manual 2024",
    source="https://example.invalid/om.pdf",
    outline=[OutlineNode(title="Maintenance", page=90, children=[OutlineNode(title="Chain", page=92)])],
    sections=[
        Section(
            id=f"{MID}-chain",
            title="Checking the chain tension",
            chapter="Maintenance",
            pageStart=92,
            pageEnd=93,
            keywords=["chain", "tension"],
            highlights=[Highlight(page=92, x=0.1, y=0.2, w=0.7, h=0.05)],
            partIds=[f"{MID}-chain-lube"],
            related=[],
        )
    ],
    parts=[
        Part(
            id=f"{MID}-chain-lube",
            name="Chain lubricant",
            spec="Chain spray",
            page=92,
            oem="00062030051",
            links=[Link(shop="Example", url="https://example.invalid/p/1")],
        )
    ],
)
PAGES = [Page(manualId=MID, page=92, width=595.0, height=842.0, text="Chain tension 5 mm", blocks=[])]
SPECS = [
    Spec(
        sectionId=f"{MID}-chain",
        name="Chain tension",
        kind="clearance",
        value="5",
        unit="mm",
        page=92,
        quote="Chain tension 5 mm",
    )
]
REG = [
    RegistryEntry(
        id="smoke-reg-1",
        make="KTM",
        model="390 Duke",
        years=[2024, 2025],
        market="EU",
        type="owner",
        lang="en",
        url="https://example.invalid/om.pdf",
        access="free",
        site="example.invalid",
        title="390 DUKE Owner's Manual",
    )
]
JOB = IngestJob(id="smoke-job-1", manualId=MID, status="running", pages=143, done=12)
COST = CostEvent(ts=time.time(), route="ask", model="gpt-5.6-luna", inputTokens=900, cachedTokens=700, outputTokens=40, usd=0.0012)

ok = 0
bad: list[str] = []


def check(name: str, got, want) -> None:
    global ok
    if got == want:
        ok += 1
        print(f"  ok   {name}")
    else:
        bad.append(name)
        print(f"  FAIL {name}\n       got  {got!r}\n       want {want!r}")


def main() -> int:
    uri = os.getenv("MONGODB_URI")
    if not uri:
        print("MONGODB_URI not set - nothing to smoke.")
        return 2
    db = os.getenv("SMOKE_DB", "ttm_smoke")
    store = MongoStore(uri, db=db)
    store.client.admin.command("ping")
    print(f"connected, db={db}")

    for c in (store.c_bikes, store.c_manuals, store.c_pages, store.c_specs, store.c_registry, store.c_jobs, store.c_costs):
        c.delete_many({})

    check("bikes() empty", store.bikes(), [])
    check("bike() missing", store.bike(BID), None)
    store.put_bikes([BIKE])
    check("bike()", store.bike(BID), BIKE)
    check("bikes()", store.bikes(), [BIKE])
    store.put_bikes([BIKE.model_copy(update={"market": "US"})])
    check("put_bikes upserts", store.bike(BID).market if store.bike(BID) else None, "US")
    check("put_bikes keeps one row", len(store.bikes()), 1)
    store.put_bikes([BIKE])

    check("manuals() empty", store.manuals(), [])
    check("manual() missing", store.manual(MID), None)
    store.put_manual(MANUAL)
    check("manual()", store.manual(MID), MANUAL)
    check("manuals()", store.manuals(), [MANUAL])
    store.put_manual(MANUAL)
    check("put_manual upserts", len(store.manuals()), 1)

    check("pages() empty", store.pages(MID), [])
    store.put_pages(MID, PAGES)
    check("pages()", store.pages(MID), PAGES)
    store.put_pages(MID, PAGES)
    check("put_pages replaces", len(store.pages(MID)), 1)

    check("specs() empty", store.specs(MID), [])
    store.put_specs(MID, SPECS)
    check("specs()", store.specs(MID), SPECS)
    store.put_specs(MID, SPECS)
    check("put_specs replaces", len(store.specs(MID)), 1)

    check("registry() empty", store.registry(), [])
    store.put_registry(REG)
    check("registry()", store.registry(), REG)
    check("registry(make)", store.registry(make="ktm"), REG)
    check("registry(make,model)", store.registry(make="KTM", model="390 duke"), REG)
    check("registry(year hit)", store.registry(year=2025), REG)
    check("registry(year miss)", store.registry(year=1999), [])
    check("registry(make miss)", store.registry(make="BMW"), [])
    store.put_registry(REG)
    check("put_registry upserts", len(store.registry()), 1)

    check("job() missing", store.job(JOB.id), None)
    store.put_job(JOB)
    check("job()", store.job(JOB.id), JOB)
    store.put_job(JOB.model_copy(update={"status": "done", "done": 143}))
    j = store.job(JOB.id)
    check("put_job upserts", (j.status, j.done) if j else None, ("done", 143))

    check("costs() empty", store.costs(), [])
    store.log_cost(COST)
    store.log_cost(COST.model_copy(update={"ts": COST.ts + 1, "route": "identify"}))
    check("costs() appends", [c.route for c in store.costs()], ["ask", "identify"])
    check("costs() round-trip", store.costs()[0], COST)

    if "--keep" not in sys.argv:
        store.client.drop_database(db)
        print(f"dropped {db}")

    print(f"\n{ok} ok, {len(bad)} failed" + (": " + ", ".join(bad) if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())

import json
from app.store import get_store
s=get_store()
for site in ("ownerinfo.jaguar.com","ownerinfo.landrover.com","tesla.com","kawasaki.com","motorrad.suzuki.de","qjmotor.es","suzukimotorcycles.com.au","suzukimotorcycle.co.in"):
    rows=[e for e in s.registry() if e.site==site]
    print(f"--- {site} ({len(rows)}) ---")
    for e in rows[:4]:
        print("   ", e.make, "|", e.model, "|", e.years[:3], "|", e.lang, "|", e.url[:150])

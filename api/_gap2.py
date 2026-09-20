import collections, re
from app.store import get_store
from app.registry import pdf_index, kind_of
s=get_store()
idx=pdf_index()
bikes=s.bikes()
# registry model names that HAVE a pdf, per make
have_models=collections.defaultdict(set)
have_years=collections.defaultdict(set)
for bid, rows in idx.items():
    for e in rows:
        have_models[e.make.lower()].add(e.model.lower())
        for y in e.years: have_years[e.make.lower()].add(y)
for mk in ("yamaha","kawasaki","suzuki","honda","ducati","ktm","husqvarna","gasgas","bmw","triumph","royal enfield","aprilia","moto guzzi","harley-davidson"):
    miss=[b for b in bikes if b.make.lower()==mk and not b.manualUrl]
    if not miss: continue
    yrs=collections.Counter(b.year for b in miss)
    band=collections.Counter()
    for b in miss: band[f"{(b.year//5)*5}s"]+=1
    print(f"--- {mk}: {len(miss)} missing; pdf years {min(have_years[mk]) if have_years[mk] else '-'}..{max(have_years[mk]) if have_years[mk] else '-'}")
    print("    by 5y band:", dict(sorted(band.items())))
    print("    sample:", [f"{b.model} {b.year}" for b in miss[:6]])

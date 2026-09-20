import collections, re
from app.store import get_store
from app.registry import pdf_index, kind_of
from app.registry._http import slug
s=get_store(); bikes=s.bikes(); idx=pdf_index()
# (make, model) -> years that have a pdf
mm=collections.defaultdict(set)
for bid,rows in idx.items():
    for e in rows:
        mm[(e.make.lower(), e.model.lower())] |= set(e.years)
def norm(x): return re.sub(r"[^a-z0-9]","",x.lower())
nm=collections.defaultdict(set)
for (mk,md),ys in mm.items(): nm[(mk,norm(md))] |= ys
for make in ("Yamaha","Kawasaki","Suzuki","Honda","Ducati","KTM","BMW","Triumph","Husqvarna","GasGas","Royal Enfield","Harley-Davidson"):
    miss=[b for b in bikes if b.make==make and not b.manualUrl and kind_of(b)=="motorcycle"]
    same_model_other_year=0; norm_hit=0; nothing=0
    ex=[]
    for b in miss:
        k=(make.lower(), b.model.lower()); kn=(make.lower(), norm(b.model))
        if k in mm: same_model_other_year+=1
        elif kn in nm:
            norm_hit+=1
            if len(ex)<3: ex.append(b.model)
        else: nothing+=1
    print(f"{make:<17}{len(miss):>5} missing | same model, other year {same_model_other_year:>5} | only after normalising {norm_hit:>4} {ex} | model unknown {nothing:>5}")

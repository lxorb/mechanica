import collections
from app.store import get_store
from app.registry import kind_of
s=get_store(); bikes=s.bikes(); rows=s.registry()
miss=collections.Counter(); have=collections.Counter(); yrs=collections.defaultdict(list)
for b in bikes:
    k=(kind_of(b), b.make)
    (have if b.manualUrl else miss)[k]+=1
    if not b.manualUrl: yrs[k].append(b.year)
for kind in ("motorcycle","car"):
    print(f"=== {kind}s without manualUrl ===")
    for (k,m),n in miss.most_common(400):
        if k!=kind: continue
        y=sorted(yrs[(k,m)])
        print(f"  {m:<20}{n:>6} missing {have[(k,m)]:>6} have   years {y[0]}-{y[-1]}")

import json, collections
from app.store import get_store
from app.registry import kind_of
s = get_store()
bikes = s.bikes()
miss = collections.Counter()
have = collections.Counter()
for b in bikes:
    k = (kind_of(b), b.make)
    if b.manualUrl: have[k]+=1
    else: miss[k]+=1
print("=== motorcycles without manualUrl, by make ===")
for (k,m),n in miss.most_common(60):
    if k=="motorcycle": print(f"  {m:<22}{n:>6} missing, {have[(k,m)]:>6} have")
print("=== cars without manualUrl, by make ===")
for (k,m),n in miss.most_common(200):
    if k=="car": print(f"  {m:<22}{n:>6} missing, {have[(k,m)]:>6} have")

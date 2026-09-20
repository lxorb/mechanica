import collections
from app.store import get_store
from app.registry import pdf_index, alias_index, foreign_index, alias_key, kind_of, _pick
s = get_store()
manuals, aliases, foreign = pdf_index(), alias_index(), foreign_index()
exact = alias_hits = foreign_hits = none = 0
by_make = collections.Counter(); pairs = collections.Counter(); langs = collections.Counter()
fm = collections.Counter()
for b in s.bikes():
    key = alias_key(b.make, b.model, b.year)
    if manuals.get(b.id): exact += 1; continue
    rows = aliases.get(key) if key else None
    if rows:
        alias_hits += 1; by_make[b.make] += 1
        best = _pick(rows, b.market, kind_of(b))
        if best.model.lower() != b.model.lower(): pairs[(b.make, b.model, best.model)] += 1
        continue
    rows = foreign.get(b.id) or (foreign.get(key) if key else None)
    if rows:
        foreign_hits += 1
        best = _pick(rows, b.market, kind_of(b))
        langs[best.lang] += 1; fm[b.make] += 1
        continue
    none += 1
print(f"exact {exact}  alias +{alias_hits}  foreign +{foreign_hits}  still none {none}")
print("\nalias by make:", dict(by_make.most_common()))
print(f"\ndistinct alias pairings: {len(pairs)}")
for (mk, a, bb), n in pairs.most_common(60): print(f"  {mk:<16}{a[:34]:<34} -> {bb[:34]:<34} x{n}")
print("\nforeign by lang:", dict(langs.most_common()))
print("foreign by make:", dict(fm.most_common()))

"""Run one adapter with REGISTRY_LANGS='*' and dump it to a fragment. Usage: _langs.py <module:attr>"""
import collections, importlib, json, os, sys

os.environ["REGISTRY_LANGS"] = "*"
name = sys.argv[1]
module, attrs = name.split(":", 1)
mod = importlib.import_module(f"app.registry.{module}")
from app.registry import merge_ua

rows = []
for attr in attrs.split(","):
    got = [e for e in getattr(mod, attr)() if e.url]
    print(f"  {module}.{attr}: {len(got)}", flush=True)
    rows += got
rows = merge_ua(rows)
langs = collections.Counter(e.lang for e in rows)
print(f"{module}: {len(rows)} rows, {len({e.url for e in rows})} distinct urls, "
      f"{len(langs)} langs {dict(langs.most_common(10))}")
out = f"data/registry-fragments/langs-{module.replace('_','-')}.json"
open(out, "w", encoding="utf-8").write(json.dumps([e.model_dump(exclude_none=True) for e in rows], ensure_ascii=False))
print("wrote", out)

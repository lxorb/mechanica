"""python -m tools.ingest <pdf|url> --make KTM --model "390 Duke" --year 2024 [--market EU] [--id <manual id>]"""

import argparse
import re
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import ingest  # noqa: E402
from app.models import Bike  # noqa: E402
from app.store import get_store  # noqa: E402


def slug(*parts) -> str:
    return re.sub(r"[^a-z0-9]+", "-", " ".join(str(p) for p in parts).lower()).strip("-")


def main() -> int:
    ap = argparse.ArgumentParser(prog="tools.ingest")
    ap.add_argument("source", help="local PDF path or http(s) URL")
    ap.add_argument("--make", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--year", required=True, type=int)
    ap.add_argument("--market", default="EU")
    ap.add_argument("--id", dest="manual_id", default=None)
    ap.add_argument("--lang", default="en")
    args = ap.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")
    store = get_store()
    bike_id = slug(args.make, args.model, args.year)
    manual_id = args.manual_id or f"{bike_id}-om-{args.lang}"
    bike = store.bike(bike_id) or Bike(id=bike_id, make=args.make, model=args.model, year=args.year, market=args.market)
    store.put_bikes([bike.model_copy(update={"manualId": manual_id})])

    job_id = uuid.uuid4().hex[:12]
    before = len(store.costs())
    started = time.time()
    manual = ingest.run(job_id, args.source, manual_id, [bike_id], args.make, args.model, args.year)
    elapsed = time.time() - started
    events = store.costs()[before:]
    usd = sum(e.usd for e in events)

    highlights = sum(len(s.highlights) for s in manual.sections)
    print(f"{manual.id}  {manual.title}")
    print(f"pages     {manual.pages}")
    print(f"sections  {len(manual.sections)}")
    print(f"highlights{highlights:>4}")
    print(f"specs     {len(store.specs(manual_id))}")
    print(f"parts     {len(manual.parts)}")
    print(f"calls     {len(events)}")
    print(f"cost      ${usd:.4f}")
    print(f"time      {elapsed:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""MongoStore: the Store protocol on MongoDB. Enabled by setting MONGODB_URI (see config.py).

db `ttm`; collections bikes, manuals, pages, specs, registry, jobs, costs.
`_id` is the model id; pages and specs are one doc per manual: {_id: manualId, items: [...]}.
"""

from pymongo import ASCENDING, MongoClient
from pymongo.collation import Collation

from .models import Bike, CostEvent, IngestJob, Manual, Page, RegistryEntry, Spec

DB = "ttm"
CI = Collation(locale="en", strength=2)


class MongoStore:
    def __init__(self, uri: str, db: str = DB):
        self.client: MongoClient = MongoClient(uri, appname="ttm-api", tz_aware=False)
        self.db = self.client[db]
        self.c_bikes = self.db["bikes"]
        self.c_manuals = self.db["manuals"]
        self.c_pages = self.db["pages"]
        self.c_specs = self.db["specs"]
        self.c_registry = self.db["registry"]
        self.c_jobs = self.db["jobs"]
        self.c_costs = self.db["costs"]
        self._ensure_indexes()

    def _ensure_indexes(self) -> None:
        self.c_bikes.create_index([("manualId", ASCENDING)])
        self.c_manuals.create_index([("bikeIds", ASCENDING)])
        self.c_registry.create_index(
            [("make", ASCENDING), ("model", ASCENDING)], name="make_model_ci", collation=CI
        )
        self.c_registry.create_index([("years", ASCENDING)])
        self.c_costs.create_index([("ts", ASCENDING)])
        self.c_costs.create_index([("route", ASCENDING)])

    @staticmethod
    def _doc(model, key: str) -> dict:
        data = model.model_dump(exclude_none=True)
        data["_id"] = getattr(model, key)
        return data

    def _put(self, coll, model, key: str = "id") -> None:
        doc = self._doc(model, key)
        coll.replace_one({"_id": doc["_id"]}, doc, upsert=True)

    def bikes(self) -> list[Bike]:
        return [Bike.model_validate(d) for d in self.c_bikes.find().sort("_id", ASCENDING)]

    def bike(self, bike_id: str) -> Bike | None:
        doc = self.c_bikes.find_one({"_id": bike_id})
        return Bike.model_validate(doc) if doc else None

    def put_bikes(self, bikes: list[Bike]) -> None:
        for b in bikes:
            self._put(self.c_bikes, b)

    def manuals(self) -> list[Manual]:
        return [Manual.model_validate(d) for d in self.c_manuals.find().sort("_id", ASCENDING)]

    def manual(self, manual_id: str) -> Manual | None:
        doc = self.c_manuals.find_one({"_id": manual_id})
        return Manual.model_validate(doc) if doc else None

    def put_manual(self, manual: Manual) -> None:
        self._put(self.c_manuals, manual)

    def pages(self, manual_id: str) -> list[Page]:
        doc = self.c_pages.find_one({"_id": manual_id})
        return [Page.model_validate(p) for p in (doc or {}).get("items", [])]

    def put_pages(self, manual_id: str, pages: list[Page]) -> None:
        items = [p.model_dump() for p in pages]
        self.c_pages.replace_one({"_id": manual_id}, {"_id": manual_id, "items": items}, upsert=True)

    def specs(self, manual_id: str) -> list[Spec]:
        doc = self.c_specs.find_one({"_id": manual_id})
        return [Spec.model_validate(s) for s in (doc or {}).get("items", [])]

    def put_specs(self, manual_id: str, specs: list[Spec]) -> None:
        items = [s.model_dump(exclude_none=True) for s in specs]
        self.c_specs.replace_one({"_id": manual_id}, {"_id": manual_id, "items": items}, upsert=True)

    def registry(self, make: str | None = None, model: str | None = None, year: int | None = None) -> list[RegistryEntry]:
        query: dict = {}
        if make:
            query["make"] = make
        if model:
            query["model"] = model
        if year:
            query["years"] = year
        cursor = self.c_registry.find(query).collation(CI).sort("_id", ASCENDING)
        return [RegistryEntry.model_validate(d) for d in cursor]

    def put_registry(self, entries: list[RegistryEntry]) -> None:
        for e in entries:
            self._put(self.c_registry, e)

    def job(self, job_id: str) -> IngestJob | None:
        doc = self.c_jobs.find_one({"_id": job_id})
        return IngestJob.model_validate(doc) if doc else None

    def put_job(self, job: IngestJob) -> None:
        self._put(self.c_jobs, job)

    def log_cost(self, event: CostEvent) -> None:
        self.c_costs.insert_one(event.model_dump())

    def costs(self) -> list[CostEvent]:
        return [CostEvent.model_validate(d) for d in self.c_costs.find().sort("ts", ASCENDING)]

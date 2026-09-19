"""Elasticsearch 9 backend for the section index. UNVERIFIED: written against the 9.x docs, never run against a
live cluster (no instance available). LocalIndex is the reference implementation; this mirrors its contract.

Hybrid retrieval: `retriever.rrf` fuses a BM25 bool query (title^3, keywords^2, text, components terms) with a
`semantic` query over a `semantic_text` field backed by the `.elser-2-elastic` inference endpoint.
"""

from typing import Any

from elasticsearch import Elasticsearch, NotFoundError, helpers

from ..models import Manual, Page, Spec
from . import Hit, SpecHit
from .local import canon

INDEX = "ttm_sections"
INFERENCE_ID = ".elser-2-elastic"

MAPPING: dict[str, Any] = {
    "properties": {
        "manual_id": {"type": "keyword"},
        "section_id": {"type": "keyword"},
        "title": {"type": "search_as_you_type"},
        "chapter": {"type": "keyword"},
        "page_start": {"type": "integer"},
        "page_end": {"type": "integer"},
        "text": {"type": "text", "copy_to": "text_sem"},
        "text_sem": {"type": "semantic_text", "inference_id": INFERENCE_ID},
        "keywords": {"type": "keyword"},
        "components": {"type": "keyword"},
        "specs": {
            "type": "nested",
            "properties": {
                "name": {"type": "text"},
                "kind": {"type": "keyword"},
                "value": {"type": "keyword"},
                "unit": {"type": "keyword"},
                "page": {"type": "integer"},
                "quote": {"type": "keyword"},
            },
        },
    }
}


class ElasticIndex:
    def __init__(self, url: str, api_key: str | None = None, index: str = INDEX):
        self.es = Elasticsearch(url, api_key=api_key) if api_key else Elasticsearch(url)
        self.name = index
        self._ready = False

    def ensure(self) -> None:
        if self._ready:
            return
        if not self.es.indices.exists(index=self.name):
            self.es.indices.create(index=self.name, mappings=MAPPING)
        self._ready = True

    def index(self, manual: Manual, pages: list[Page], specs: list[Spec]) -> None:
        self.ensure()
        by_page = {p.page: p.text for p in pages}
        by_section: dict[str, list[Spec]] = {}
        for spec in specs:
            by_section.setdefault(spec.sectionId, []).append(spec)

        actions = []
        for section in manual.sections:
            body = " ".join(by_page.get(p, "") for p in range(section.pageStart, section.pageEnd + 1))
            actions.append(
                {
                    "_op_type": "update",
                    "_index": self.name,
                    "_id": f"{manual.id}:{section.id}",
                    "doc_as_upsert": True,
                    "doc": {
                        "manual_id": manual.id,
                        "section_id": section.id,
                        "title": section.title,
                        "chapter": section.chapter,
                        "page_start": section.pageStart,
                        "page_end": section.pageEnd,
                        "text": " ".join(body.split()),
                        "keywords": section.keywords,
                        "components": sorted(set(canon(section.title)) | set(canon(section.chapter))),
                        "specs": [
                            {
                                "name": s.name,
                                "kind": s.kind,
                                "value": s.value,
                                "unit": s.unit,
                                "page": s.page,
                                "quote": s.quote,
                            }
                            for s in by_section.get(section.id, [])
                        ],
                    },
                }
            )
        if actions:
            helpers.bulk(self.es, actions, refresh=True)

    def remove(self, manual_id: str) -> None:
        self.ensure()
        try:
            self.es.delete_by_query(
                index=self.name, query={"term": {"manual_id": manual_id}}, refresh=True, conflicts="proceed"
            )
        except NotFoundError:
            pass

    def query(self, manual_id: str, queries: list[str], components: list[str] | None = None, k: int = 8) -> list[Hit]:
        self.ensure()
        clean = [q.strip() for q in queries if q and q.strip()]
        if not clean:
            return []
        joined = " ".join(clean)

        should: list[dict[str, Any]] = [
            {"multi_match": {"query": q, "fields": ["title^3", "keywords^2", "text"], "type": "best_fields"}}
            for q in clean
        ]
        if components:
            should.append({"terms": {"components": [c.lower() for c in components], "boost": 1.5}})

        retriever = {
            "rrf": {
                "retrievers": [
                    {
                        "standard": {
                            "query": {
                                "bool": {
                                    "filter": [{"term": {"manual_id": manual_id}}],
                                    "should": should,
                                    "minimum_should_match": 1,
                                }
                            }
                        }
                    },
                    {
                        "standard": {
                            "query": {
                                "bool": {
                                    "filter": [{"term": {"manual_id": manual_id}}],
                                    "must": [{"semantic": {"field": "text_sem", "query": joined}}],
                                }
                            }
                        }
                    },
                ],
                "rank_window_size": max(k * 4, 50),
                "rank_constant": 20,
            }
        }

        response = self.es.search(
            index=self.name, retriever=retriever, size=k, source_includes=["section_id"], track_total_hits=False
        )
        hits = response.get("hits", {}).get("hits", [])
        if not hits:
            return []
        top = max((h.get("_score") or 0.0) for h in hits) or 1.0
        out = []
        for h in hits:
            section_id = (h.get("_source") or {}).get("section_id")
            if section_id:
                out.append(Hit(sectionId=section_id, score=min(1.0, (h.get("_score") or 0.0) / top)))
        return out

    def spec(self, manual_id: str, name: str, kind: str | None = None, k: int = 5) -> list[SpecHit]:
        self.ensure()
        must: list[dict[str, Any]] = [{"match": {"specs.name": {"query": name}}}]
        inner: dict[str, Any] = {"bool": {"must": must}}
        if kind:
            inner["bool"]["should"] = [{"term": {"specs.kind": {"value": kind, "boost": 2.0}}}]

        response = self.es.search(
            index=self.name,
            query={
                "bool": {
                    "filter": [{"term": {"manual_id": manual_id}}],
                    "must": [
                        {
                            "nested": {
                                "path": "specs",
                                "query": inner,
                                "score_mode": "max",
                                "inner_hits": {"size": k, "name": "specs"},
                            }
                        }
                    ],
                }
            },
            size=k,
            source_includes=["section_id"],
            track_total_hits=False,
        )

        rows: list[tuple[float, Spec]] = []
        for h in response.get("hits", {}).get("hits", []):
            section_id = (h.get("_source") or {}).get("section_id")
            for ih in h.get("inner_hits", {}).get("specs", {}).get("hits", {}).get("hits", []):
                src = ih.get("_source") or {}
                rows.append(
                    (
                        float(ih.get("_score") or 0.0),
                        Spec(
                            sectionId=section_id or "",
                            name=src.get("name", ""),
                            kind=src.get("kind", "other"),
                            value=src.get("value", ""),
                            unit=src.get("unit"),
                            page=int(src.get("page") or 0),
                            quote=src.get("quote", ""),
                        ),
                    )
                )
        if not rows:
            return []
        top = max(score for score, _ in rows) or 1.0
        rows.sort(key=lambda r: -r[0])
        return [SpecHit(spec=spec, score=min(1.0, score / top)) for score, spec in rows[:k]]

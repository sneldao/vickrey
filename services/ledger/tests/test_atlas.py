"""Tests for the Atlas observation store.

No cluster is required: ``FakeCollection`` implements the handful of pymongo
methods the store uses, including a real cosine ranking for ``$vectorSearch``.
That keeps the query shapes honest and the similarity math verifiable, and it
is the closest we can get to Atlas without credentials.
"""

from __future__ import annotations

import copy
import math
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.atlas import (
    EMBED_DIMS,
    VECTOR_INDEX_NAME,
    ObservationStore,
    connect,
    coarse_location,
    label_text,
    local_embedding,
    normalize_block_id,
    observation_document,
    vector_index_definition,
)
from app.main import create_app
from tests.support import BLOCK_ID, TAG, matching_fetch

ANCHOR = {
    "schema": "vickrey.observation/1",
    "observed_at": "2026-10-11T08:00:00.000Z",
    "model_id": "gemma3:4b",
    "commitment": "a" * 64,
    "signature": "c2ln",
    "public_key": "cHVi",
    "prev": None,
    "location": {"lat": 51.507351, "lon": -0.127758},
    "summary": {"kind": "bird", "species": "Common blackbird", "confidence": 0.82},
    "detail": "sensitive: exact nest in the old oak",
}


class FakeCollection:
    """The pymongo surface the store touches, with real cosine ranking."""

    def __init__(self) -> None:
        self.docs: dict[str, dict] = {}
        self.indexes: list[tuple[str, Any]] = []
        self.aggregations: list[list[dict]] = []

    # -- index management -------------------------------------------------
    def create_index(self, keys, name=None, unique=False):  # noqa: ANN001
        label = name or str(keys)
        self.indexes.append((label, {"keys": keys, "unique": unique}))
        return label

    # -- writes -----------------------------------------------------------
    def replace_one(self, query, document, upsert=False):  # noqa: ANN001
        key = query["block_id_norm"]
        self.docs[key] = copy.deepcopy(document)
        return {"upserted_id": key if upsert else None}

    # -- reads ------------------------------------------------------------
    def _strip(self, document: dict) -> dict:
        cleaned = copy.deepcopy(document)
        cleaned.pop("_id", None)
        return cleaned

    def find_one(self, query, projection=None):  # noqa: ANN001
        document = self.docs.get(query["block_id_norm"])
        return None if document is None else self._strip(document)

    def find(self, query, projection=None):  # noqa: ANN001, ARG002
        matches = []
        for document in self.docs.values():
            if all(document.get(k) == v for k, v in query.items()):
                matches.append(self._strip(document))
        return FakeCursor(matches)

    def count_documents(self, query):  # noqa: ANN001
        return sum(
            1
            for document in self.docs.values()
            if all(document.get(k) == v for k, v in query.items())
        )

    def aggregate(self, pipeline):  # noqa: ANN001
        self.aggregations.append(copy.deepcopy(pipeline))
        stage = pipeline[0]["$vectorSearch"]
        query_vector = stage["queryVector"]
        scored = []
        for document in self.docs.values():
            embedding = document.get("embedding")
            if not embedding:
                continue
            score = sum(a * b for a, b in zip(query_vector, embedding))
            scored.append((score, self._strip(document)))
        scored.sort(key=lambda item: item[0], reverse=True)
        limit = int(stage["limit"])
        projection = pipeline[1]["$project"] if len(pipeline) > 1 else None
        rows = [
            {**document, "score": round(score, 6)} for score, document in scored[:limit]
        ]
        if projection is None:
            return rows
        keep = [key for key, value in projection.items() if value and key != "_id"]
        return [{key: row[key] for key in keep if key in row} for row in rows]


class FakeCursor:
    def __init__(self, documents: list[dict]) -> None:
        self.documents = documents

    def sort(self, field, direction):  # noqa: ANN001
        self.documents.sort(
            key=lambda document: document.get(field) or "", reverse=direction < 0
        )
        return self

    def limit(self, count):  # noqa: ANN001
        self.documents = self.documents[:count]
        return self

    def __iter__(self):
        return iter(self.documents)


@pytest.fixture
def collection() -> FakeCollection:
    return FakeCollection()


@pytest.fixture
def store(collection: FakeCollection) -> ObservationStore:
    return ObservationStore(collection)


# --------------------------------------------------------------------------
# local_embedding
# --------------------------------------------------------------------------


def test_local_embedding_is_deterministic_and_normalised():
    first = local_embedding("bird Common blackbird")
    second = local_embedding("bird Common blackbird")
    assert first == second
    assert len(first) == EMBED_DIMS
    norm = math.sqrt(sum(value * value for value in first))
    assert norm == pytest.approx(1.0)
    assert any(value != 0.0 for value in first)


def test_local_embedding_of_empty_text_is_a_zero_vector():
    vector = local_embedding("")
    assert vector == [0.0] * EMBED_DIMS


def test_local_embedding_scores_shared_words_above_unrelated_text():
    query = local_embedding("bird Common blackbird")
    near = local_embedding("bird Common blackbird")
    far = local_embedding("hazard fallen tree")
    dot = lambda a, b: sum(x * y for x, y in zip(a, b))  # noqa: E731
    assert dot(query, near) > dot(query, far)


# --------------------------------------------------------------------------
# document shaping
# --------------------------------------------------------------------------


def test_normalize_block_id_strips_prefix_and_case():
    assert normalize_block_id("0xAbC123") == "abc123"


def test_coarse_location_rounds_and_rejects_partial_input():
    assert coarse_location({"lat": 51.507351, "lon": -0.127758}) == {
        "lat": 51.51,
        "lon": -0.13,
    }
    assert coarse_location({"lat": 51.5}) is None
    assert coarse_location("not a place") is None


def test_label_text_uses_the_coarse_label_only():
    assert label_text(ANCHOR) == "bird Common blackbird"


def test_observation_document_keeps_the_seal_and_drops_the_detail():
    document = observation_document(
        block_id="0xAbC123", tag="vickrey.observation", flow_id="walk-1", message=ANCHOR
    )
    assert document["block_id_norm"] == "abc123"
    assert document["flow_id"] == "walk-1"
    assert document["commitment"] == "a" * 64
    assert document["signature"] == "c2ln"
    assert document["public_key"] == "cHVi"
    assert document["kind"] == "bird"
    assert document["species"] == "Common blackbird"
    assert document["confidence"] == 0.82
    assert document["label"] == "bird Common blackbird"
    assert document["location"] == {"lat": 51.51, "lon": -0.13}
    # The raw description never reaches the searchable store.
    assert "detail" not in document
    assert "sensitive" not in repr(document)


def test_observation_document_tolerates_a_non_object_message():
    document = observation_document(block_id="0x1", tag="t", message="raw text")
    assert document["block_id_norm"] == "1"
    assert document["label"] == ""
    assert document["commitment"] is None


def test_vector_index_definition_declares_the_dimension_and_filter_fields():
    definition = vector_index_definition()
    assert definition["name"] == VECTOR_INDEX_NAME
    assert definition["type"] == "vectorSearch"
    vector = definition["fields"][0]
    assert vector["numDimensions"] == EMBED_DIMS
    assert vector["path"] == "embedding"
    assert vector["similarity"] == "cosine"
    assert {"type": "filter", "path": "tag"} in definition["fields"]


# --------------------------------------------------------------------------
# store behaviour
# --------------------------------------------------------------------------


def test_put_upserts_idempotently_and_embeds_the_label(store, collection):
    first = store.put(block_id="0xAbC123", tag="t", flow_id="walk-1", message=ANCHOR)
    assert len(first["embedding"]) == EMBED_DIMS
    assert len(collection.docs) == 1

    again = store.put(block_id="0xabc123", tag="t", flow_id="walk-1", message=ANCHOR)
    assert again["block_id_norm"] == "abc123"
    assert len(collection.docs) == 1


def test_get_and_count(store):
    store.put(block_id="0x1", tag="t", flow_id="f", message=ANCHOR)
    assert store.get("0x1")["species"] == "Common blackbird"
    assert store.get("missing") is None
    assert store.count() == 1
    assert store.count(flow_id="f") == 1
    assert store.count(flow_id="other") == 0


def test_recent_sorts_newest_first_and_filters_by_flow(store):
    older = {**ANCHOR, "observed_at": "2026-10-10T08:00:00.000Z"}
    newer = {**ANCHOR, "observed_at": "2026-10-11T08:00:00.000Z"}
    store.put(block_id="0x1", tag="t", flow_id="walk-1", message=older)
    store.put(block_id="0x2", tag="t", flow_id="walk-2", message=newer)
    recent = store.recent(limit=10)
    assert [row["block_id"] for row in recent] == ["0x2", "0x1"]
    only_walk = store.recent(limit=10, flow_id="walk-1")
    assert [row["block_id"] for row in only_walk] == ["0x1"]


def test_similar_ranks_the_matching_anchor_first(store, collection):
    store.put(block_id="0x1", tag="t", flow_id="f", message=ANCHOR)
    store.put(
        block_id="0x2",
        tag="t",
        flow_id="f",
        message={**ANCHOR, "summary": {"kind": "hazard", "species": "fallen tree"}},
    )
    hits = store.similar_to_text("blackbird", limit=2)
    assert [hit["block_id"] for hit in hits] == ["0x1", "0x2"]
    assert hits[0]["score"] > hits[1]["score"]
    assert hits[0]["commitment"] == "a" * 64
    # The raw detail is never projected back out of the index.
    assert "detail" not in hits[0]
    assert "embedding" not in hits[0]
    stage = collection.aggregations[0][0]["$vectorSearch"]
    assert stage["index"] == VECTOR_INDEX_NAME
    assert stage["numCandidates"] == 100


def test_similar_pushes_filters_into_the_vector_search_stage(store, collection):
    store.similar_to_text("blackbird", limit=3, tag="t", flow_id="walk-1")
    stage = collection.aggregations[0][0]["$vectorSearch"]
    assert stage["filter"] == {
        "$and": [{"tag": {"$eq": "t"}}, {"flow_id": {"$eq": "walk-1"}}]
    }


def test_similar_rejects_an_empty_vector(store):
    with pytest.raises(ValueError, match="needs an embedding"):
        store.similar([])


def test_ensure_indexes_is_idempotent_and_named(collection, store):
    names = store.ensure_indexes()
    assert "block_id_norm" in names
    assert collection.indexes[0][1]["unique"] is True
    store.ensure_indexes()
    assert len(collection.indexes) == 6


def test_connect_fails_clearly_without_pymongo(monkeypatch):
    """The driver is lazily imported, so a missing pymongo is a clear error."""
    import builtins

    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name == "pymongo":
            raise ImportError("blocked for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    with pytest.raises(RuntimeError, match="pymongo is required"):
        connect("mongodb://example.invalid")


# --------------------------------------------------------------------------
# ledger wiring
# --------------------------------------------------------------------------

ANCHOR_MESSAGE = {
    "flow_id": "walk-1",
    "schema": "vickrey.observation/1",
    "observed_at": "2026-10-11T08:00:00.000Z",
    "model_id": "gemma3:4b",
    "commitment": "b" * 64,
    "signature": "c2ln",
    "public_key": "cHVi",
    "prev": None,
    "location": {"lat": 48.856614, "lon": 2.352222},
    "summary": {"kind": "plant", "species": "Foxglove", "confidence": 0.7},
}


class StubHornet:
    def __init__(self) -> None:
        self.default = matching_fetch(tag=TAG, message=ANCHOR_MESSAGE)

    def fetch(self, block_id: str):  # noqa: ANN201
        return self.default

    def close(self) -> None:
        return None


def wired_client(tmp_path, store):
    app = create_app(
        database_path=str(tmp_path / "ledger.db"),
        hornet=StubHornet(),
        observation_store=store,
    )
    return TestClient(app)


def test_ingest_mirrors_the_anchor_into_the_store(tmp_path, store):
    with wired_client(tmp_path, store) as http:
        response = http.post(
            "/ingest",
            json={"blockId": BLOCK_ID, "tag": TAG, "message": ANCHOR_MESSAGE},
        )
        assert response.status_code == 201
        assert response.json()["status"] == "VERIFIED"

    stored = store.get(BLOCK_ID)
    assert stored["flow_id"] == "walk-1"
    assert stored["commitment"] == "b" * 64
    assert stored["label"] == "plant Foxglove"
    assert stored["location"] == {"lat": 48.86, "lon": 2.35}
    assert "detail" not in stored


def test_similar_and_recent_routes_expose_anchors_only(tmp_path, store):
    with wired_client(tmp_path, store) as http:
        assert http.get("/health").json()["observations"] is True
        http.post(
            "/ingest",
            json={"blockId": BLOCK_ID, "tag": TAG, "message": ANCHOR_MESSAGE},
        )

        similar = http.get("/observations/similar", params={"q": "foxglove"})
        assert similar.status_code == 200
        body = similar.json()
        assert body["store"] == "mongodb-atlas"
        assert body["count"] == 1
        hit = body["observations"][0]
        assert hit["block_id"] == BLOCK_ID
        assert hit["commitment"] == "b" * 64
        assert "detail" not in hit
        assert "embedding" not in hit

        recent = http.get("/observations/recent").json()
        assert recent["count"] == 1
        filtered = http.get("/observations/recent", params={"flowId": "walk-1"}).json()
        assert filtered["count"] == 1
        empty = http.get("/observations/recent", params={"flowId": "nope"}).json()
        assert empty["count"] == 0


def test_observation_routes_are_503_without_a_store(tmp_path):
    app = create_app(database_path=str(tmp_path / "ledger.db"), hornet=StubHornet())
    with TestClient(app) as http:
        assert http.get("/health").json()["observations"] is False
        assert app.state.observations is None
        for path in ("/observations/similar?q=bird", "/observations/recent"):
            response = http.get(path)
            assert response.status_code == 503
            assert "MONGODB_URI" in response.json()["detail"]


def test_a_broken_mirror_never_fails_ingest(tmp_path):
    class Exploding:
        def put(self, **kwargs):  # noqa: ANN003
            raise RuntimeError("cluster unreachable")

    app = create_app(
        database_path=str(tmp_path / "ledger.db"),
        hornet=StubHornet(),
        observation_store=Exploding(),
    )
    with TestClient(app) as http:
        response = http.post(
            "/ingest",
            json={"blockId": BLOCK_ID, "tag": TAG, "message": ANCHOR_MESSAGE},
        )
    assert response.status_code == 201
    assert response.json()["status"] == "VERIFIED"


def test_shipped_vector_index_file_matches_the_code():
    """The JSON handed to the Atlas CLI must not drift from the code."""
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "atlas-vector-index.json"
    assert json.loads(path.read_text()) == vector_index_definition()


def test_connect_builds_a_store_over_the_real_driver():
    """The pymongo path is exercised: the client is lazy, so no cluster needed."""
    pytest.importorskip("pymongo")
    store = connect(
        "mongodb://127.0.0.1:1/vickrey", database="vickrey", collection="obs"
    )
    assert isinstance(store, ObservationStore)
    assert store.collection.name == "obs"

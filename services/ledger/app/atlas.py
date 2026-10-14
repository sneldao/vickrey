"""MongoDB Atlas observation store.

The commons data layer. Observations are anchored on the ledger as a
commitment (the seal); this store keeps the searchable index of *anchors* so a
field device can ask "who else saw this, near here?" without ever holding the
raw record. Atlas Vector Search does the similarity work.

Two design rules, both deliberate:

- **Anchors, not observations.** The document stored here is the same
  commitment that was anchored to the ledger -- hash, signature, public key,
  coarse location, model id, and a coarse label. The photo and the notes never
  reach this store, so an endangered-species sighting cannot be scraped out of
  the similarity index.
- **Embeddings are pluggable.** ``local_embedding`` is a deterministic
  feature-hashing embedder so the whole loop works with no network and no
  second API key. Swap ``embed`` for a real model when quality matters; the
  store and its queries do not change.

``pymongo`` is imported lazily in :func:`connect` so the ledger runs, and its
tests pass, without the driver installed.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any, Callable

# Dimensions of the local feature-hashing embedder. Atlas Vector Search indexes
# are declared with a fixed dimension, so this must match the index definition.
EMBED_DIMS = 256
VECTOR_INDEX_NAME = "observation_vectors"

# Fields an anchored message may carry, from the field client's sealed entry.
ANCHOR_FIELDS = (
    "observed_at",
    "model_id",
    "commitment",
    "signature",
    "public_key",
    "prev",
)

_TOKEN = re.compile(r"[a-z0-9]+")


def local_embedding(text: str | None, dims: int = EMBED_DIMS) -> list[float]:
    """Deterministic, dependency-free embedding for offline similarity search.

    Each lowercase term maps to a signed feature. The resulting vector is
    scaled to unit length for cosine distance. It is a placeholder for a real model, not a claim of
    semantic quality: it matches shared words, nothing more.
    """
    vector = [0.0] * dims
    for token in _TOKEN.findall((text or "").lower()):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dims
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        return vector
    return [value / norm for value in vector]


def normalize_block_id(block_id: str) -> str:
    text = str(block_id).strip()
    if text.lower().startswith("0x"):
        text = text[2:]
    return text.lower()


def coarsen(value: Any, decimals: int = 2) -> Any:
    """Coarsen a coordinate so the index never carries a precise location."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    factor = 10**decimals
    return round(float(value) * factor) / factor


def coarse_location(location: Any, decimals: int = 2) -> dict | None:
    if not isinstance(location, dict):
        return None
    lat = coarsen(location.get("lat"), decimals)
    lon = coarsen(location.get("lon"), decimals)
    if lat is None or lon is None:
        return None
    return {"lat": lat, "lon": lon}


def label_text(message: Any) -> str:
    """The text that gets embedded: the coarse label only.

    ``detail`` and any free note are intentionally excluded -- they are the
    parts most likely to contain a sensitive description.
    """
    if not isinstance(message, dict):
        return ""
    kind = ""
    species = ""
    summary = message.get("summary")
    for source in (message, summary):
        if not isinstance(source, dict):
            continue
        if not kind and isinstance(source.get("kind"), str):
            kind = source["kind"]
        if not species and isinstance(source.get("species"), str):
            species = source["species"]
    return " ".join(part for part in (kind, species) if part).strip()


def observation_document(
    *,
    block_id: str,
    tag: str,
    flow_id: str | None = None,
    message: Any = None,
    embedding: list[float] | None = None,
    embed: Callable[[str], list[float]] | None = None,
    decimals: int = 2,
) -> dict:
    """Normalise an anchored message into the stored document."""
    body = message if isinstance(message, dict) else {}
    document: dict[str, Any] = {
        "block_id": block_id,
        "block_id_norm": normalize_block_id(block_id),
        "tag": tag,
        "flow_id": flow_id,
        "schema": body.get("schema") or "veles.observation/1",
        "observed_at": body.get("observed_at"),
        "model_id": body.get("model_id"),
        "commitment": body.get("commitment"),
        "signature": body.get("signature"),
        "public_key": body.get("public_key"),
        "prev": body.get("prev"),
        "location": coarse_location(body.get("location"), decimals),
        "label": label_text(body),
    }
    for key in ("kind", "species"):
        source = body.get(key)
        if source is None and isinstance(body.get("summary"), dict):
            source = body["summary"].get(key)
        document[key] = source if isinstance(source, str) else None
    confidence = body.get("confidence")
    if confidence is None and isinstance(body.get("summary"), dict):
        confidence = body["summary"].get("confidence")
    document["confidence"] = (
        confidence if isinstance(confidence, (int, float)) else None
    )

    if embedding is not None:
        document["embedding"] = list(embedding)
    elif embed is not None:
        document["embedding"] = list(embed(document["label"]))
    return document


def vector_index_definition(
    *, path: str = "embedding", dims: int = EMBED_DIMS, similarity: str = "cosine"
) -> dict:
    """The Atlas Search index body for vector similarity over observations.

    Create it with the Atlas CLI once a cluster exists::

        atlas clusters search indexes create \\
          --clusterName <cluster> --file atlas-vector-index.json
    """
    return {
        "name": VECTOR_INDEX_NAME,
        "type": "vectorSearch",
        "fields": [
            {
                "type": "vector",
                "path": path,
                "numDimensions": dims,
                "similarity": similarity,
            },
            {"type": "filter", "path": "tag"},
            {"type": "filter", "path": "flow_id"},
            {"type": "filter", "path": "model_id"},
        ],
    }


# Fields projected out of every read; ``_id`` is Mongo's, not ours.
_PROJECTION = {"_id": 0}


class ObservationStore:
    """Query surface over a pymongo collection of observation anchors.

    ``collection`` is duck-typed: tests pass a fake that records calls, and
    :func:`connect` passes a real ``pymongo.collection.Collection``.
    """

    def __init__(
        self,
        collection: Any,
        *,
        index_name: str = VECTOR_INDEX_NAME,
        embed: Callable[[str], list[float]] | None = None,
        dims: int = EMBED_DIMS,
    ) -> None:
        self.collection = collection
        self.index_name = index_name
        self.embed = embed or (lambda text: local_embedding(text, dims))
        self.dims = dims

    def ensure_indexes(self) -> list[str]:
        """Idempotent b-tree indexes so the non-vector queries stay fast.

        The vector index is *not* created here: Atlas Search indexes are built
        through the Atlas control plane, not the driver. See
        :func:`vector_index_definition`.
        """
        created = [
            self.collection.create_index(
                [("block_id_norm", 1)], name="block_id_norm", unique=True
            ),
            self.collection.create_index(
                [("tag", 1), ("observed_at", -1)], name="tag_time"
            ),
            self.collection.create_index(
                [("flow_id", 1), ("observed_at", -1)], name="flow_time"
            ),
        ]
        return created

    def put(
        self,
        *,
        block_id: str,
        tag: str,
        flow_id: str | None = None,
        message: Any = None,
        embedding: list[float] | None = None,
    ) -> dict:
        """Upsert one anchor. Re-ingesting the same block is idempotent."""
        document = observation_document(
            block_id=block_id,
            tag=tag,
            flow_id=flow_id,
            message=message,
            embedding=embedding,
            embed=None if embedding is not None else self.embed,
        )
        self.collection.replace_one(
            {"block_id_norm": document["block_id_norm"]}, document, upsert=True
        )
        return document

    def get(self, block_id: str) -> dict | None:
        return self.collection.find_one(
            {"block_id_norm": normalize_block_id(block_id)}, _PROJECTION
        )

    def recent(
        self, *, limit: int = 20, flow_id: str | None = None, tag: str | None = None
    ) -> list[dict]:
        query: dict[str, Any] = {}
        if flow_id is not None:
            query["flow_id"] = flow_id
        if tag is not None:
            query["tag"] = tag
        cursor = (
            self.collection.find(query, _PROJECTION)
            .sort("observed_at", -1)
            .limit(limit)
        )
        return list(cursor)

    def count(self, **filters: Any) -> int:
        query = {key: value for key, value in filters.items() if value is not None}
        return int(self.collection.count_documents(query))

    def similar(
        self,
        embedding: list[float],
        *,
        limit: int = 5,
        num_candidates: int | None = None,
        tag: str | None = None,
        flow_id: str | None = None,
    ) -> list[dict]:
        """Atlas Vector Search over the anchors, nearest first.

        Filters are pushed into ``$vectorSearch`` so Atlas applies them before
        ranking (the index declares them as filter fields).
        """
        if not embedding:
            raise ValueError("similar needs an embedding vector")
        stage: dict[str, Any] = {
            "index": self.index_name,
            "path": "embedding",
            "queryVector": list(embedding),
            "numCandidates": int(num_candidates or max(limit * 20, 100)),
            "limit": int(limit),
        }
        filters = [
            {"tag": {"$eq": tag}} if tag is not None else None,
            {"flow_id": {"$eq": flow_id}} if flow_id is not None else None,
        ]
        present = [item for item in filters if item is not None]
        if present:
            stage["filter"] = present[0] if len(present) == 1 else {"$and": present}
        pipeline = [
            {"$vectorSearch": stage},
            {
                "$project": {
                    "_id": 0,
                    "block_id": 1,
                    "tag": 1,
                    "flow_id": 1,
                    "label": 1,
                    "kind": 1,
                    "species": 1,
                    "observed_at": 1,
                    "model_id": 1,
                    "commitment": 1,
                    "location": 1,
                    "score": {"$meta": "vectorSearchScore"},
                }
            },
        ]
        return list(self.collection.aggregate(pipeline))

    def similar_to_text(self, text: str, **kwargs: Any) -> list[dict]:
        return self.similar(self.embed(text), **kwargs)


def _ca_bundle() -> str | None:
    """Point the driver at a CA bundle we can vouch for.

    Atlas serves a public certificate, so verification should succeed against
    any sane trust store. It does not always: ``python:3.12-slim`` -- the image
    this ledger ships in -- has no ``ca-certificates``, and ``pymongo`` does not
    pull in ``certifi`` the way ``httpx`` does. The result is
    ``CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate``, which
    reads like an Atlas outage but is not.

    ``None`` falls back to the system store, so a host with a working trust
    store is unaffected.
    """
    try:
        import certifi

        return certifi.where()
    except Exception:  # pragma: no cover - certifi is a hard requirement now
        return None


def connect(
    uri: str,
    *,
    database: str = "vickrey",
    collection: str = "observations",
    index_name: str = VECTOR_INDEX_NAME,
    embed: Callable[[str], list[float]] | None = None,
    dims: int = EMBED_DIMS,
    **client_options: Any,
) -> ObservationStore:
    """Build a store against a real Atlas cluster.

    ``uri`` is a standard MongoDB connection string. The driver import is
    deferred so the rest of the ledger never depends on it being installed.
    """
    try:
        from pymongo import MongoClient
    except ImportError as exc:  # pragma: no cover - exercised only without pymongo
        raise RuntimeError(
            "pymongo is required for the Atlas observation store: "
            "pip install -r services/ledger/requirements.txt"
        ) from exc
    client_options.setdefault("serverSelectionTimeoutMS", 5000)
    client_options.setdefault("appname", "vickrey-ledger")
    if "tlsCAFile" not in client_options:
        bundle = _ca_bundle()
        if bundle:
            client_options["tlsCAFile"] = bundle
    client = MongoClient(uri, **client_options)
    return ObservationStore(
        client[database][collection],
        index_name=index_name,
        embed=embed,
        dims=dims,
    )

"""The embedded block store, and the single-container ingest path it enables."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.embedded import EMBEDDED_URL, EmbeddedHornet, embedded_from_env
from app.main import create_app
from app.verify import verify_record

ANCHOR = {
    "blockId": "a" * 64,
    "tag": "veles.observation",
    "message": {
        "schema": "veles.observation/1",
        "observed_at": "2026-10-14T10:00:00.000Z",
        "commitment": "a" * 64,
        "signature": "sig",
        "summary": {"kind": "bird", "species": "European robin"},
    },
}


@pytest.fixture
def store() -> EmbeddedHornet:
    return EmbeddedHornet()


def test_an_unregistered_block_reads_as_a_404_with_no_body(store):
    fetch = store.fetch("f" * 64)
    assert fetch.block is None
    assert fetch.metadata is None
    assert fetch.block_status == 404
    assert fetch.error is None, "a missing block is not a transport error"


def test_a_registered_block_round_trips_through_the_hornet_read(store):
    store.register(
        block_id=ANCHOR["blockId"], tag=ANCHOR["tag"], message=ANCHOR["message"]
    )
    fetch = store.fetch(ANCHOR["blockId"])
    assert fetch.block is not None
    assert fetch.metadata is not None
    assert fetch.metadata["isSolid"] is True
    assert fetch.metadata["referencedByMilestoneIndex"] == 42
    # the payload is hex-encoded tagged data, exactly as a real Hornet returns it
    assert fetch.block["payload"]["type"] == 5


def test_the_stored_block_verifies_against_the_anchor_it_came_from(store):
    store.register(
        block_id=ANCHOR["blockId"], tag=ANCHOR["tag"], message=ANCHOR["message"]
    )
    result = verify_record(
        ANCHOR["tag"], ANCHOR["message"], store.fetch(ANCHOR["blockId"])
    )
    assert result.status == "VERIFIED", result.detail


def test_an_edited_application_copy_is_still_caught_in_embedded_mode(store):
    """The property the two-source check exists to protect.

    The block store is in the same process now, but it is still a *separate
    store*. Editing only the application copy must still mismatch.
    """
    store.register(
        block_id=ANCHOR["blockId"], tag=ANCHOR["tag"], message=ANCHOR["message"]
    )
    edited = dict(ANCHOR["message"])
    edited["summary"] = {"kind": "bird", "species": "Misidentified magpie"}
    result = verify_record(ANCHOR["tag"], edited, store.fetch(ANCHOR["blockId"]))
    assert result.status == "PAYLOAD_MISMATCH"
    assert result.content_match is False


def test_block_ids_are_normalised_the_same_way_the_ledger_stores_them(store):
    store.register(block_id="0x" + "B" * 64, tag="t", message={"a": 1})
    for candidate in ("B" * 64, "0x" + "b" * 64, "  " + "b" * 64 + " "):
        assert store.fetch(candidate).block is not None


def test_registering_the_same_block_twice_is_idempotent(store):
    store.register(block_id="c" * 64, tag="t", message={"a": 1})
    store.register(block_id="c" * 64, tag="t", message={"a": 2})
    assert store.registered == 1


def test_a_non_solid_block_with_no_milestone_is_not_verified(store):
    store.register(
        block_id="d" * 64,
        tag="t",
        message={"a": 1},
        is_solid=False,
        milestone_index=None,
    )
    result = verify_record("t", {"a": 1}, store.fetch("d" * 64))
    assert result.status == "NOT_SOLID"


def test_a_milestone_pending_block_is_pending_not_verified(store):
    store.register(block_id="e" * 64, tag="t", message={"a": 1}, milestone_index=None)
    result = verify_record("t", {"a": 1}, store.fetch("e" * 64))
    assert result.status == "PENDING"


@pytest.mark.parametrize(
    "flag,expected",
    [
        ("1", True),
        ("true", True),
        ("TRUE", True),
        ("yes", True),
        ("on", True),
        ("0", False),
        ("false", False),
        ("", False),
        ("maybe", False),
    ],
)
def test_the_env_flag_is_read_conservatively(flag, expected):
    got = embedded_from_env(flag)
    assert (got is not None) is expected


def test_a_client_in_embedded_mode_needs_no_relay(tmp_path):
    """One container, one POST, VERIFIED -- the whole deploy story."""
    app = create_app(database_path=str(tmp_path / "l.db"), embedded=True)
    with TestClient(app) as client:
        assert client.get("/health").json()["anchoring"] == "embedded"
        response = client.post("/ingest", json=ANCHOR)
        assert response.status_code == 201
        assert response.json()["status"] == "VERIFIED"


def test_the_health_endpoint_names_its_own_anchoring_mode(tmp_path):
    with TestClient(
        create_app(database_path=str(tmp_path / "a.db"), embedded=True)
    ) as c:
        assert c.get("/health").json()["blocks_registered"] == 0
        c.post("/ingest", json=ANCHOR)
        body = c.get("/health").json()
        assert body["hornet_url"] == EMBEDDED_URL
        assert body["blocks_registered"] == 1
    with TestClient(
        create_app(database_path=str(tmp_path / "b.db"), embedded=False)
    ) as c:
        assert c.get("/health").json()["anchoring"] == "messages-api"


def test_without_embedded_mode_ingest_does_not_write_a_block(tmp_path):
    """Off by default: an unconfigured ledger must not invent its own blocks."""
    with TestClient(
        create_app(database_path=str(tmp_path / "c.db"), embedded=False)
    ) as c:
        assert c.post("/ingest", json=ANCHOR).json()["status"] == "PENDING"
        assert c.get("/health").json()["blocks_registered"] is None


def test_embedded_mode_survives_a_tampered_copy_end_to_end(tmp_path):
    """The ledger's own demo route still works with the store in-process.

    Reverify, not re-ingest: ingesting the anchor again would legitimately
    restore the application copy, which is the point of an upsert.
    """
    with TestClient(
        create_app(database_path=str(tmp_path / "d.db"), embedded=True)
    ) as c:
        assert c.post("/ingest", json=ANCHOR).json()["status"] == "VERIFIED"
        assert (
            c.post(f"/messages/{ANCHOR['blockId']}/tamper", json={}).status_code == 200
        )
        reverified = c.post(f"/messages/{ANCHOR['blockId']}/reverify").json()
        assert reverified["status"] == "PAYLOAD_MISMATCH"
        # the block never changed -- only the copy did
        assert c.get("/health").json()["blocks_registered"] == 1

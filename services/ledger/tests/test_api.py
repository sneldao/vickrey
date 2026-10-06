from __future__ import annotations

from fastapi.testclient import TestClient

from app.hornet import HornetFetch
from app.main import create_app
from app.tamper import mutate_application_payload
from tests.support import BLOCK_ID, MESSAGE, TAG, matching_fetch


def ingest(client, **extra):
    body = {"blockId": BLOCK_ID, "tag": TAG, "message": MESSAGE, "hornetStatus": 201}
    body.update(extra)
    return client.post("/ingest", json=body)


def test_ingest_verified_and_get_round_trip(client):
    http, hornet = client
    response = ingest(http)
    assert response.status_code == 201
    row = response.json()
    assert row["status"] == "VERIFIED"
    assert row["solid"] is True
    assert row["content_match"] is True
    assert row["milestone_index"] == 8
    assert row["payload_json"] == MESSAGE
    assert row["ledger_payload_json"] == MESSAGE
    assert row["ledger_tag"] == TAG
    assert row["flow_id"] == "flow-1"
    assert row["hornet_status"] == 201
    assert row["raw_block"]["payload"]["type"] == 5
    assert hornet.calls == [BLOCK_ID]

    fetched = http.get(f"/messages/{BLOCK_ID.lower()}").json()
    assert fetched["block_id"] == BLOCK_ID
    assert fetched["status"] == "VERIFIED"

    again = ingest(http)
    assert again.status_code == 200
    assert again.json()["inserted_at"] == row["inserted_at"]


def test_tamper_keeps_ledger_payload_and_flips_match(client):
    http, hornet = client
    ingest(http)
    calls_before = len(hornet.calls)

    tampered = http.post(f"/messages/{BLOCK_ID}/tamper", json={"temperature": 999.9})
    assert tampered.status_code == 200
    body = tampered.json()
    assert body["demo_only"] is True
    assert body["previous_payload_json"]["temperature"] == 21.5
    message = body["message"]
    assert message["status"] == "PAYLOAD_MISMATCH"
    assert message["content_match"] is False
    assert message["solid"] is True
    assert message["payload_json"]["temperature"] == 999.9
    assert message["ledger_payload_json"] == MESSAGE
    assert message["ledger_payload_json"]["temperature"] == 21.5
    assert len(hornet.calls) == calls_before + 1

    reverified = http.post(f"/messages/{BLOCK_ID}/reverify")
    assert reverified.json()["status"] == "PAYLOAD_MISMATCH"
    assert reverified.json()["ledger_payload_json"]["temperature"] == 21.5

    restored = ingest(http)
    assert restored.json()["status"] == "VERIFIED"
    assert restored.json()["payload_json"]["temperature"] == 21.5


def test_default_tamper_and_full_payload_replacement(client):
    http, _hornet = client
    ingest(http)
    default = http.post(f"/messages/{BLOCK_ID}/tamper", json={})
    assert default.status_code == 200
    payload = default.json()["message"]["payload_json"]
    assert payload["temperature"] == 999.9
    assert payload["_demo_tampered"] is True
    assert default.json()["message"]["status"] == "PAYLOAD_MISMATCH"

    replaced = http.post(
        f"/messages/{BLOCK_ID}/tamper",
        json={"payload": {"flow_id": "flow-1", "temperature": 0, "sensor": "edge-a"}},
    )
    assert replaced.json()["message"]["payload_json"]["temperature"] == 0
    assert replaced.json()["message"]["content_match"] is False


def test_temperature_tamper_rejects_non_object(client):
    http, hornet = client
    hornet.default = matching_fetch(message="plain")
    created = http.post(
        "/ingest",
        json={"blockId": BLOCK_ID, "tag": TAG, "message": "plain"},
    )
    assert created.status_code == 201
    assert created.json()["status"] == "VERIFIED"
    rejected = http.post(f"/messages/{BLOCK_ID}/tamper", json={"temperature": 50})
    assert rejected.status_code == 400
    assert http.get(f"/messages/{BLOCK_ID}").json()["payload_json"] == "plain"


def test_pending_when_hornet_is_down_then_reverify(client):
    http, hornet = client
    hornet.default = HornetFetch(None, None, None, None, error="connection refused")
    response = ingest(http)
    assert response.status_code == 201
    assert response.json()["status"] == "PENDING"
    assert response.json()["content_match"] is None
    assert response.json()["solid"] is None

    hornet.default = matching_fetch()
    reverified = http.post(f"/messages/{BLOCK_ID}/reverify")
    assert reverified.status_code == 200
    assert reverified.json()["status"] == "VERIFIED"
    assert reverified.json()["content_match"] is True


def test_not_solid_status(client):
    http, hornet = client
    hornet.default = matching_fetch(solid=False, milestone=None)
    response = ingest(http)
    assert response.json()["status"] == "NOT_SOLID"
    assert response.json()["content_match"] is True
    assert response.json()["solid"] is False


def test_filters_and_unknown_status(client):
    http, hornet = client
    ingest(http)
    hornet.default = matching_fetch(
        tag="other.tag",
        message={"flow_id": "flow-2", "temperature": 1},
    )
    other = http.post(
        "/ingest",
        json={
            "block_id": "0xdef456",
            "tag": "other.tag",
            "message": {"flow_id": "flow-2", "temperature": 1},
            "flowId": "explicit-flow",
        },
    )
    assert other.status_code == 201
    assert other.json()["flow_id"] == "explicit-flow"

    by_flow = http.get("/messages", params={"flowId": "flow-1", "status": "verified"})
    assert by_flow.status_code == 200
    body = by_flow.json()
    assert body["total"] == 1
    assert body["count"] == 1
    assert body["messages"][0]["block_id"] == BLOCK_ID

    by_tag = http.get("/messages", params={"tag": "other.tag"})
    assert by_tag.json()["total"] == 1
    assert by_tag.json()["messages"][0]["flow_id"] == "explicit-flow"

    future = http.get("/messages", params={"from": "2099-01-01", "to": "2099-01-02"})
    assert future.json()["total"] == 0
    past = http.get("/messages", params={"from": "2000-01-01", "to": "2099-01-01"})
    assert past.json()["total"] == 2

    bad = http.get("/messages", params={"status": "nope"})
    assert bad.status_code == 400
    bad_time = http.get("/messages", params={"from": "yesterday"})
    assert bad_time.status_code == 400


def test_missing_message_is_404(client):
    http, _hornet = client
    assert http.get("/messages/0xmissing").status_code == 404
    assert http.post("/messages/0xmissing/reverify").status_code == 404
    assert http.post("/messages/0xmissing/tamper", json={}).status_code == 404


def test_health(client):
    http, _hornet = client
    health = http.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["hornet_url"]


def test_default_cors_allows_explorer_origin(client):
    http, _hornet = client
    response = http.get("/health", headers={"Origin": "http://localhost:8090"})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"


def test_cors_can_be_limited_to_the_explorer(tmp_path, hornet):
    app = create_app(
        database_path=str(tmp_path / "ledger.db"),
        hornet=hornet,
        cors_origins="http://localhost:8090",
    )
    with TestClient(app) as http:
        response = http.get("/messages", headers={"Origin": "http://localhost:8090"})
        assert (
            response.headers["access-control-allow-origin"] == "http://localhost:8090"
        )
        preflight = http.options(
            f"/messages/{BLOCK_ID}/tamper",
            headers={
                "Origin": "http://localhost:8090",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert preflight.status_code == 200
        allow = preflight.headers["access-control-allow-methods"]
        assert "POST" in allow
        assert (
            preflight.headers["access-control-allow-origin"] == "http://localhost:8090"
        )


def test_default_mutate_wraps_scalar():
    wrapped = mutate_application_payload(
        "plain", replacement_set=False, temperature=None
    )
    assert wrapped["temperature"] == 999.9
    assert wrapped["_previous"] == "plain"
    assert wrapped["_demo_tampered"] is True

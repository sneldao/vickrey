"""The service must not overstate its own guarantees.

A ledger whose whole point is provable integrity cannot describe itself with a
claim it does not honour. In embedded mode the ledger *writes* the block before
reading it back, so "independently reads the Hornet block" is false -- and that
string was in the public API until this test existed.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app

FALSE_CLAIMS = ("independent", "only ever gets", "reads the block independently")


def test_embedded_mode_does_not_claim_an_independent_source(tmp_path):
    with TestClient(
        create_app(database_path=str(tmp_path / "a.db"), embedded=True)
    ) as c:
        root = c.get("/").json()
        assert root["service"] == "vickrey-evidence-ledger"
        assert root["anchoring"] == "embedded"
        assert root["guarantee"]["independent_source"] is False
        # the reason has to be visible, not just the boolean
        assert "separate store" in root["guarantee"]["note"]
        assert "separate process" in root["guarantee"]["note"]
        assert c.get("/health").json()["independent_source"] is False


def test_messages_api_mode_can_claim_independence(tmp_path):
    with TestClient(
        create_app(database_path=str(tmp_path / "b.db"), embedded=False)
    ) as c:
        root = c.get("/").json()
        assert root["anchoring"] == "messages-api"
        assert root["guarantee"]["independent_source"] is True
        assert "only ever reads" in root["guarantee"]["note"]
        assert c.get("/health").json()["independent_source"] is True


def test_no_endpoint_claims_independence_while_embedded(tmp_path):
    """A blanket sweep, so a future edit cannot quietly reintroduce the claim.

    The `independent_source` key name is stripped first: that field is the
    honest one, and it is false here. What must not appear is a *prose* claim.
    """
    with TestClient(
        create_app(database_path=str(tmp_path / "c.db"), embedded=True)
    ) as c:
        for path in ("/", "/health"):
            body = c.get(path).json()
            text = str(body).lower().replace("independent_source", "")
            assert "veles" not in text, path
            for claim in FALSE_CLAIMS:
                assert claim not in text, f"{path} claims {claim!r} while embedded"


def test_the_health_endpoint_still_reports_what_the_client_probes(tmp_path):
    """The field client gates its UI on these keys, so they must not move."""
    with TestClient(
        create_app(database_path=str(tmp_path / "d.db"), embedded=True)
    ) as c:
        body = c.get("/health").json()
        assert set(body) >= {
            "status",
            "service",
            "hornet_url",
            "anchoring",
            "context",
            "blocks_registered",
            "observations",
        }
        assert body["context"] is False
        assert body["observations"] is False


def test_the_openapi_document_is_named_for_the_project(tmp_path):
    with TestClient(
        create_app(database_path=str(tmp_path / "e.db"), embedded=True)
    ) as c:
        doc = c.get("/openapi.json").json()
        assert doc["info"]["title"] == "Vickrey evidence ledger"
        assert "VELES" not in str(doc).upper()


def test_context_and_observations_are_advertised_only_when_present(tmp_path):
    with TestClient(
        create_app(database_path=str(tmp_path / "f.db"), embedded=True)
    ) as c:
        root = c.get("/").json()
        assert root["context"] is None
        assert root["observations"] is None

"""Web context: a third-party lookup that must never touch a sealed record."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app.context import ContextError, TavilyContext, build_query, context_from_env
from app.main import create_app
from app.verify import canonical_json

SEEN: list[dict] = []


def handler(payload: dict) -> httpx.MockTransport:
    """A fake Tavily. Records the request so tests can assert on the query."""

    def respond(request: httpx.Request) -> httpx.Response:
        import json

        SEEN.append(
            {
                "body": json.loads(request.content),
                "auth": request.headers.get("authorization"),
                "url": str(request.url),
            }
        )
        return httpx.Response(
            200,
            json={
                "query": payload.get("query", "q"),
                "answer": "  Three recent reports.  ",
                "results": [
                    {
                        "title": "RSPB robin page",
                        "url": "https://example.org/robin",
                        "content": "  A   robin was  seen . ",
                        "score": 0.91,
                    },
                    {
                        "title": "Forum thread",
                        "url": "https://example.net/t",
                        "content": "saw one by the canal",
                        "score": 0.42,
                    },
                ],
                "response_time": 1.4,
                "usage": {"credits": 1},
            },
        )

    return httpx.MockTransport(respond)


def status_transport(code: int) -> httpx.MockTransport:
    return httpx.MockTransport(
        lambda request: httpx.Response(code, json={"detail": {"error": "nope"}})
    )


@pytest.fixture(autouse=True)
def clear_seen():
    SEEN.clear()
    yield
    SEEN.clear()


# --------------------------------------------------------------- queries


def test_the_species_is_quoted_so_a_synonym_cannot_replace_it():
    assert build_query("European robin").startswith('"European robin"')


def test_a_bare_robin_is_not_left_to_the_search_engines_symonyms():
    # "robin" unqualified returns the American bird most often, which would be
    # a confidently wrong answer on a UK field record.
    assert '"European robin"' in build_query("European robin")
    assert '"robin"' in build_query("robin")


def test_the_kind_is_never_in_the_query():
    """Measured against the live API: including it diluted results badly.

    "European robin" bird sightings reported Hackney returned a birding PDF, a
    Wikipedia biography and a restaurant guide. The kind is redundant with a
    species name and costs more than it disambiguates.
    """
    from app.context import build_query as q

    assert q("European robin", place="Hackney") == '"European robin" Hackney sightings'
    assert "bird" not in q("European robin")
    assert "plant" not in q("Common ivy")


def test_a_place_is_included_only_when_given():
    assert build_query("Common ivy", place="Hackney, London") == (
        '"Common ivy" Hackney, London sightings'
    )
    assert build_query("Common ivy") == '"Common ivy" sightings'


def test_no_time_filter_is_sent_by_default():
    """A sighting is not a news event; recency filters returned junk results."""
    client = TavilyContext("tvly-test", transport=handler({}))
    client.search(species="European robin", place="Hackney")
    assert "time_range" not in SEEN[0]["body"]
    client.close()


def test_a_caller_can_still_ask_for_recency():
    client = TavilyContext("tvly-test", transport=handler({}))
    client.search(species="European robin", time_range="week")
    assert SEEN[0]["body"]["time_range"] == "week"
    client.close()


def test_whitespace_in_a_pasted_name_is_collapsed():
    assert build_query("  Common   ivy \n") == '"Common ivy" sightings'


def test_a_species_is_required():
    with pytest.raises(ContextError, match="species is needed"):
        build_query("   ")


def test_no_query_can_carry_a_coordinate():
    """The anchoring rule is not relaxed because a search engine wants a place."""
    query = build_query("Common ivy", place="51.54,-0.08")
    # whatever the observer passed is echoed once, never combined with lat/lon
    # fields of its own
    assert "lat" not in query.lower()
    assert "longitude" not in query.lower()


# --------------------------------------------------------------- client


def test_a_search_returns_tidied_results_and_credits():
    client = TavilyContext("tvly-test", transport=handler({}))
    body = client.search(species="European robin", place="Hackney")
    assert body["provider"] == "tavily"
    assert body["answer"] == "Three recent reports."
    assert body["credits"] == 1
    assert body["results"][0]["title"] == "RSPB robin page"
    assert body["results"][0]["content"] == "A robin was seen ."
    client.close()


def test_the_key_travels_in_the_bearer_header_not_the_body():
    client = TavilyContext("tvly-secret", transport=handler({}))
    client.search(species="Common ivy")
    assert SEEN[0]["auth"] == "Bearer tvly-secret"
    assert "tvly-secret" not in canonical_json(SEEN[0]["body"])
    client.close()


def test_the_request_asks_for_recent_results_cheaply():
    client = TavilyContext("tvly-test", transport=handler({}))
    client.search(species="Common ivy", limit=3)
    body = SEEN[0]["body"]
    assert body["search_depth"] == "basic", "one credit is enough for this query"
    assert body["max_results"] == 3
    client.close()


def test_the_limit_is_clamped_to_what_the_api_accepts():
    client = TavilyContext("tvly-test", transport=handler({}))
    client.search(species="Common ivy", limit=99)
    assert SEEN[0]["body"]["max_results"] == 20
    client.close()


@pytest.mark.parametrize(
    "code,fragment",
    [
        (401, "rejected the API key"),
        (429, "rate limit"),
        (432, "plan limit"),
        (500, "500"),
    ],
)
def test_upstream_problems_become_a_readable_message(code, fragment):
    client = TavilyContext("tvly-test", transport=status_transport(code))
    with pytest.raises(ContextError, match=fragment):
        client.search(species="Common ivy")
    client.close()


def test_a_transport_failure_is_reported_not_raised_raw():
    def boom(request):
        raise httpx.ConnectError("no route to host")

    client = TavilyContext("tvly-test", transport=httpx.MockTransport(boom))
    with pytest.raises(ContextError, match="could not reach Tavily"):
        client.search(species="Common ivy")
    client.close()


def test_a_non_json_body_is_reported():
    client = TavilyContext(
        "tvly-test",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html>")),
    )
    with pytest.raises(ContextError, match="non-JSON"):
        client.search(species="Common ivy")
    client.close()


def test_a_blank_key_configures_nothing():
    assert context_from_env("") is None
    assert context_from_env("   ") is None
    assert context_from_env("tvly-x") is not None


def test_a_client_cannot_be_built_without_a_key():
    with pytest.raises(ValueError):
        TavilyContext("")


# -------------------------------------------------------------- endpoint


def test_the_route_returns_context_without_a_key(tmp_path):
    with TestClient(
        create_app(database_path=str(tmp_path / "a.db"), context=None)
    ) as c:
        response = c.post("/context", json={"species": "Common ivy"})
        assert response.status_code == 503
        assert "TAVILY_API_KEY" in response.json()["detail"]


def test_the_route_serves_a_context(tmp_path):
    web = TavilyContext("tvly-test", transport=handler({}))
    with TestClient(create_app(database_path=str(tmp_path / "b.db"), context=web)) as c:
        body = c.post(
            "/context",
            json={
                "species": "European robin",
                "kind": "bird",
                "place": "Hackney, London",
            },
        ).json()
        assert body["answer"] == "Three recent reports."
        assert len(body["results"]) == 2
        assert c.get("/health").json()["context"] is True
        assert c.get("/").json()["context"] == "/context"


def test_a_context_failure_is_shown_on_the_page_not_raised(tmp_path):
    """A third-party outage must not turn into a 500 for the field client."""
    web = TavilyContext("tvly-test", transport=status_transport(429))
    with TestClient(create_app(database_path=str(tmp_path / "c.db"), context=web)) as c:
        response = c.post("/context", json={"species": "Common ivy"})
        assert response.status_code == 200
        body = response.json()
        assert "rate limit" in body["error"]
        assert body["results"] == []


def test_an_empty_species_is_rejected(tmp_path):
    web = TavilyContext("tvly-test", transport=handler({}))
    with TestClient(create_app(database_path=str(tmp_path / "d.db"), context=web)) as c:
        assert c.post("/context", json={"species": ""}).status_code == 422


# ----------------------------------------------------------- the guarantee


def test_context_cannot_change_a_status_or_touch_the_record(tmp_path):
    """The point of the whole module.

    Anchoring, sealing and verification are unaffected by web context: a failed
    lookup must not move a record off VERIFIED, and nothing a search returns may
    appear in the stored application copy.
    """
    web = TavilyContext("tvly-test", transport=status_transport(500))
    anchor = {
        "blockId": "a" * 64,
        "tag": "vickrey.observation",
        "message": {
            "commitment": "a" * 64,
            "signature": "sig",
            "summary": {"kind": "bird", "species": "European robin"},
        },
    }
    with TestClient(
        create_app(database_path=str(tmp_path / "e.db"), embedded=True, context=web)
    ) as c:
        assert c.post("/ingest", json=anchor).json()["status"] == "VERIFIED"
        assert c.post("/context", json={"species": "European robin"}).json()["error"]
        # the record is untouched by a successful lookup too
        assert c.post("/context", json={"species": "Common ivy"}).status_code == 200
        row = c.get(f"/messages/{anchor['blockId']}").json()
        assert row["status"] == "VERIFIED"
        assert "results" not in row["payload_json"]
        assert "tavily" not in canonical_json(row).lower()

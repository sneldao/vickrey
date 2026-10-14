"""Web context for a sealed sighting, via Tavily.

A field identifier that says "European robin" and stops is half a product. What
is missing is context: is this species expected here, is it notable, is it in
bloom, when did others last report it nearby? That is public, slow-changing
knowledge, and a web search is the right tool for it.

Three rules, all deliberate:

**Context is never sealed.** Nothing from this module is written into the record
or the anchor. The seal is the observer's own observation; a search result
fetched later, from a third party, cannot be part of a commitment someone is
expected to reproduce. The field client renders this beside the record, never
inside it.

**The ledger stays the source of truth.** A Tavily outage, a quota error or a
missing key degrades to a plain message on the page. It never fails an ingest
and never changes a status.

**Only coarse geography leaves the device.** The query carries the species and
an optional place *name* the observer already chose to record. It never carries a
coordinate, and certainly not the precise one -- the anchoring rule is not
waived for convenience.

The API key lives server-side. The browser never sees it, so the enrichment is
a route on this service rather than a fetch from the field client.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

TAVILY_ENDPOINT = "https://api.tavily.com/search"

# 'basic' is one credit. 'advanced' doubles it for very little gain on a short
# "is this species found around here" query.
SEARCH_DEPTH = "basic"
DEFAULT_LIMIT = 5

# No default time filter, and that is a deliberate, measured choice.
#
# A sighting is not a news event. Almost nothing on the web is *published this
# month* about robins in Hackney, so time_range=month left Tavily matching any
# recent page containing the words: a robin query returned a Wikipedia
# biography and a restaurant guide. Dropping it and asking simply "where is this
# species found around here" returns actual field checklists and a usable
# answer. Callers may still pass `time_range` if they want recency.
DEFAULT_TIME_RANGE: str | None = None


class ContextError(RuntimeError):
    """An upstream failure, phrased for a human reading the field client."""


def build_query(species: str, place: str | None = None) -> str:
    """A short, quoted query for "is this species found around here".

    The species is quoted so Tavily cannot silently substitute a synonym --
    "robin" would otherwise return the American bird far more often than the one
    actually observed.

    The kind ("bird", "plant") is deliberately *not* included. Measured against
    the live API it diluted the query badly: `"European robin" bird sightings
    reported Hackney` returned a birding PDF, a Wikipedia biography and a
    restaurant guide, while `"European robin" Hackney sightings` returned
    Victoria Park checklists and the River Lea. Redundant words cost more here
    than they disambiguate.
    """
    name = " ".join(str(species or "").split())
    if not name:
        raise ContextError("a species is needed before looking up context")
    parts = [f'"{name}"']
    cleaned = " ".join(str(place).split()) if place else ""
    if cleaned:
        parts.append(cleaned)
    parts.append("sightings")
    return " ".join(parts)


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


class TavilyContext:
    """A thin, injectable client for Tavily Search.

    ``transport`` is duck-typed the same way :class:`app.hornet.HornetClient`
    is, so tests pass a fake and never touch the network.
    """

    def __init__(
        self,
        api_key: str,
        *,
        endpoint: str = TAVILY_ENDPOINT,
        timeout: float = 12.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("a Tavily API key is required")
        self.api_key = api_key
        self.endpoint = endpoint
        kwargs: dict[str, Any] = {"timeout": timeout}
        if transport is not None:
            kwargs["transport"] = transport
        self._client = httpx.Client(**kwargs)

    def close(self) -> None:
        self._client.close()

    def search(
        self,
        *,
        species: str,
        place: str | None = None,
        limit: int = DEFAULT_LIMIT,
        time_range: str | None = DEFAULT_TIME_RANGE,
        search_depth: str = SEARCH_DEPTH,
    ) -> dict[str, Any]:
        query = build_query(species, place)
        payload = {
            "query": query,
            "search_depth": search_depth,
            "max_results": max(1, min(int(limit), 20)),
            "topic": "general",
            # A short synthesis reads well on a phone and saves the judge
            # scrolling four snippets.
            "include_answer": "basic",
            # Shown on the page: what the lookup cost.
            "include_usage": True,
        }
        if time_range:
            payload["time_range"] = time_range
        try:
            response = self._client.post(
                self.endpoint,
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
        except httpx.HTTPError as exc:
            raise ContextError(f"could not reach Tavily: {exc}") from exc

        if response.status_code in (401, 403):
            raise ContextError("Tavily rejected the API key")
        if response.status_code == 429:
            raise ContextError("Tavily rate limit reached — try again shortly")
        if response.status_code in (432, 433):
            raise ContextError("Tavily plan limit reached")
        if response.status_code >= 400:
            raise ContextError(f"Tavily returned {response.status_code}")

        try:
            body = response.json()
        except ValueError as exc:
            raise ContextError("Tavily returned a non-JSON body") from exc
        if not isinstance(body, dict):
            raise ContextError("Tavily returned an unexpected body")

        return {
            "provider": "tavily",
            "query": body.get("query") or query,
            "answer": _text(body.get("answer")) or None,
            "credits": (body.get("usage") or {}).get("credits"),
            "elapsed": body.get("response_time"),
            "results": [
                {
                    "title": _text(item.get("title")) or None,
                    "url": item.get("url") or "",
                    "content": _text(item.get("content")),
                    "score": item.get("score"),
                    "published": _text(item.get("published_date")) or None,
                }
                for item in (body.get("results") or [])
                if isinstance(item, dict)
            ][: max(1, min(int(limit), 20))],
        }


def context_from_env(key: str | None = None) -> TavilyContext | None:
    """Build the client when TAVILY_API_KEY is set, otherwise None.

    Unset means "this deployment has no web context", which is a supported
    configuration rather than an error.

    ``TAVILY_ENDPOINT`` overrides the API host, which is what
    ``scripts/fake_tavily.py`` and any egress proxy use.
    """
    raw = os.environ.get("TAVILY_API_KEY", "") if key is None else key
    if not raw or not str(raw).strip():
        return None
    endpoint = os.environ.get("TAVILY_ENDPOINT", "").strip() or TAVILY_ENDPOINT
    return TavilyContext(str(raw).strip(), endpoint=endpoint)

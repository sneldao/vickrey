"""Independent Hornet reads. This client only GETs; it never submits blocks."""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import quote

import httpx

DEFAULT_HORNET_URL = "http://127.0.0.1:14265"


@dataclass
class HornetFetch:
    block: dict | None
    metadata: dict | None
    block_status: int | None
    metadata_status: int | None
    error: str | None = None


class HornetClient:
    def __init__(
        self,
        base_url: str = DEFAULT_HORNET_URL,
        timeout: float = 5.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        kwargs: dict = {"timeout": timeout, "base_url": self.base_url}
        if transport is not None:
            kwargs["transport"] = transport
        self._client = httpx.Client(**kwargs)

    def close(self) -> None:
        self._client.close()

    def fetch(self, block_id: str) -> HornetFetch:
        path_id = quote(block_id, safe="")
        block_status, block, block_err = self._get(f"/api/core/v2/blocks/{path_id}")
        if block_status is None:
            return HornetFetch(
                block=None,
                metadata=None,
                block_status=None,
                metadata_status=None,
                error=block_err or "Hornet unreachable",
            )
        meta_status, meta, _meta_err = self._get(
            f"/api/core/v2/blocks/{path_id}/metadata"
        )
        if meta_status is None:
            meta = None
        return HornetFetch(
            block=block,
            metadata=meta,
            block_status=block_status,
            metadata_status=meta_status,
            error=None,
        )

    def _get(self, path: str) -> tuple[int | None, dict | None, str | None]:
        try:
            response = self._client.get(path)
        except httpx.HTTPError as exc:
            return None, None, str(exc)
        if response.status_code != 200:
            return response.status_code, None, f"HTTP {response.status_code}"
        try:
            body = response.json()
        except json.JSONDecodeError:
            return response.status_code, None, "response was not JSON"
        if not isinstance(body, dict):
            return response.status_code, None, "response was not a JSON object"
        return response.status_code, body, None

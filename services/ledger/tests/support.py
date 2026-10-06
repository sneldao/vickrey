from __future__ import annotations

import json
from typing import Any

from app.hornet import HornetFetch

TAG = "veles.evidence.temperature"
MESSAGE = {"flow_id": "flow-1", "sensor": "edge-a", "temperature": 21.5, "unit": "C"}
BLOCK_ID = "0xAbC123"


def tagged_block(tag: str, message: Any, *, encoded: str | None = None) -> dict:
    data = json.dumps(message) if encoded is None else encoded
    return {
        "protocolVersion": 2,
        "parents": ["0x" + "11" * 32],
        "payload": {
            "type": 5,
            "tag": "0x" + tag.encode("utf-8").hex(),
            "data": "0x" + data.encode("utf-8").hex(),
        },
        "nonce": "1",
    }


def matching_fetch(
    tag: str = TAG,
    message: Any = None,
    *,
    solid: bool = True,
    milestone: int | None = 8,
    include_metadata: bool = True,
    encoded: str | None = None,
) -> HornetFetch:
    if message is None:
        message = MESSAGE
    metadata = None
    meta_status = None
    if include_metadata:
        metadata = {"isSolid": solid}
        if milestone is not None:
            metadata["referencedByMilestoneIndex"] = milestone
        meta_status = 200
    return HornetFetch(
        block=tagged_block(tag, message, encoded=encoded),
        metadata=metadata,
        block_status=200,
        metadata_status=meta_status,
    )


class FakeHornet:
    def __init__(self) -> None:
        self.default = matching_fetch()
        self.calls: list[str] = []

    def fetch(self, block_id: str) -> HornetFetch:
        self.calls.append(block_id)
        return self.default

    def close(self) -> None:
        return None

"""In-process Hornet, so the ledger can be one container.

The local demo runs three processes: the field client posts to the anchor relay,
the relay registers a block with ``scripts/mock_hornet.py`` over HTTP, and the
ledger reads that block back with its own GET. The separation is real, and it is
the separation that makes the two-source check mean anything -- the ledger's
copy and the block it reads are written by different processes.

``scripts/mock_hornet.py`` keeps its blocks in a module-level dict, so it cannot
be split across serverless invocations, which share no memory. On a single
always-on host, though, one process is enough, and this module supplies the
block store in-process.

**What this changes.** The block store moves into the ledger's own process, so
the ledger no longer only ever GETs -- in embedded mode it writes the block
before reading it back. The two-source property survives at the data layer,
which is what the check actually tests: the application copy lives in SQLite and
the block lives here, in a separate structure, so editing the application copy
alone still produces ``PAYLOAD_MISMATCH``. What is lost is the guarantee that a
*different process* holds the block.

**When to use it.** Single-container hosting, and demos where one deploy is
worth more than process separation. Point ``HORNET_URL`` at a real node and this
is not used at all -- the ledger only ever GETs, as it does today.

**Operational constraint.** The block store is in memory, so an app using it
must run exactly one instance. Scale to zero and a restart loses every
registered block, which strands its records at ``PENDING``. Fly: ``fly scale
count 1``, no auto-stop.
"""

from __future__ import annotations

import json
import threading
from typing import Any

from app.db import normalize_block_id
from app.hornet import HornetFetch

EMBEDDED_URL = "embedded://in-process"


def hex_utf8(text: Any) -> str:
    return "0x" + str(text).encode("utf-8").hex()


class EmbeddedHornet:
    """The subset of the Hornet surface the ledger reads, plus a register call.

    ``fetch`` returns the same :class:`HornetFetch` shape as
    :class:`app.hornet.HornetClient`, so ``app.verify`` needs no changes. A block
    that was never registered comes back as a 404 with no body, which
    ``verify_record`` already handles as ``PENDING``.
    """

    def __init__(self, *, url: str = EMBEDDED_URL) -> None:
        self._url = url
        self._blocks: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    @property
    def url(self) -> str:
        return self._url

    @property
    def registered(self) -> int:
        with self._lock:
            return len(self._blocks)

    def register(
        self,
        *,
        block_id: str,
        tag: str,
        message: Any,
        is_solid: bool = True,
        milestone_index: int | None = 42,
    ) -> dict[str, Any]:
        """Write one tagged-data block, the way the Messages API would.

        Idempotent by block id, so re-anchoring the same commitment does not
        duplicate the block. The payload shape matches what a real Hornet
        returns, hex-encoded, because ``decode_tagged`` parses exactly that.
        """
        metadata: dict[str, Any] = {
            "blockId": str(block_id),
            "isSolid": bool(is_solid),
        }
        if milestone_index is not None:
            metadata["referencedByMilestoneIndex"] = int(milestone_index)
        record = {
            "block": {
                "protocolVersion": 2,
                "parents": [],
                "payload": {
                    "type": 5,
                    "tag": hex_utf8(tag),
                    "data": hex_utf8(json.dumps(message)),
                },
                "nonce": "1",
            },
            "metadata": metadata,
        }
        with self._lock:
            self._blocks[normalize_block_id(block_id)] = record
        return record

    def fetch(self, block_id: str) -> HornetFetch:
        with self._lock:
            record = self._blocks.get(normalize_block_id(block_id))
        if record is None:
            return HornetFetch(
                block=None,
                metadata=None,
                block_status=404,
                metadata_status=404,
                error=None,
            )
        return HornetFetch(
            block=record["block"],
            metadata=record["metadata"],
            block_status=200,
            metadata_status=200,
            error=None,
        )

    def close(self) -> None:
        """Present for symmetry with HornetClient; there is no connection."""


def embedded_from_env(flag: Any = None) -> EmbeddedHornet | None:
    """Build the store when ``HORNET_EMBEDDED`` is set to something true.

    Accepts ``1``, ``true``, ``yes`` and ``on``, case-insensitively. Anything
    else, including unset, means "use ``HORNET_URL``" -- the real path.
    """
    import os

    raw = os.environ.get("HORNET_EMBEDDED", "") if flag is None else flag
    if raw is None:
        return None
    text = str(raw).strip().lower()
    if text in ("1", "true", "yes", "on"):
        return EmbeddedHornet()
    return None

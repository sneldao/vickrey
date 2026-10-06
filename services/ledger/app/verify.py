"""Two-source check: application payload versus one Hornet block.

Truth table (last verification attempt):

| Hornet body | content | isSolid | milestone | status            |
|-------------|---------|---------|-----------|-------------------|
| unreachable | unknown | unknown | unknown   | PENDING           |
| missing     | unknown | no      | *         | NOT_SOLID         |
| missing     | unknown | *       | *         | PENDING           |
| decoded     | differ  | *       | *         | PAYLOAD_MISMATCH  |
| decoded     | match   | unknown | *         | PENDING           |
| decoded     | match   | no      | *         | NOT_SOLID         |
| decoded     | match   | yes     | missing   | PENDING           |
| decoded     | match   | yes     | set       | VERIFIED          |

PAYLOAD_MISMATCH wins over solidity so a Day 3 tamper of the application
copy flips content_match even when the original block is already solid.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any

from app.hornet import HornetFetch


class Status(str, Enum):
    VERIFIED = "VERIFIED"
    PENDING = "PENDING"
    PAYLOAD_MISMATCH = "PAYLOAD_MISMATCH"
    NOT_SOLID = "NOT_SOLID"


STATUS_VALUES = tuple(item.value for item in Status)


@dataclass
class VerifyResult:
    solid: bool | None
    content_match: bool | None
    milestone_index: int | None
    raw_block: dict | None
    ledger_payload: Any
    ledger_tag: str | None
    status: str
    detail: str


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def payloads_match(app_payload: Any, ledger_payload: Any) -> bool:
    """Semantic JSON equality. Key order and insignificant whitespace do not count."""
    try:
        return canonical_json(app_payload) == canonical_json(ledger_payload)
    except (TypeError, ValueError):
        return False


def decode_hex_utf8(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text[:2].lower() == "0x":
        text = text[2:]
    if text == "":
        return ""
    try:
        raw = bytes.fromhex(text)
    except ValueError:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def as_milestone(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _unwrap_block(block: dict) -> dict:
    if "payload" not in block and isinstance(block.get("block"), dict):
        return block["block"]
    return block


def decode_tagged(block: dict) -> tuple[str | None, Any, str, bool]:
    """Return (tag, payload, detail, comparable).

    comparable is false when the block is not tagged data or the hex cannot
    be decoded. A non-JSON data field is comparable so the mismatch detail
    can name it, and payloads_match will fail against a JSON application copy.
    """
    body = _unwrap_block(block)
    payload = body.get("payload")
    if not isinstance(payload, dict):
        return None, None, "block has no payload", False
    if payload.get("type") != 5:
        kind = payload.get("type")
        return None, None, f"payload type {kind!r} is not tagged data (5)", False

    if payload.get("tag") is None:
        tag = ""
    else:
        tag = decode_hex_utf8(payload.get("tag"))
        if tag is None:
            return None, None, "tag hex could not be decoded", False

    if payload.get("data") is None:
        data_text = ""
    else:
        data_text = decode_hex_utf8(payload.get("data"))
        if data_text is None:
            return tag, None, "data hex could not be decoded", False

    if data_text == "":
        return tag, "", "", True
    try:
        parsed = json.loads(data_text)
    except json.JSONDecodeError:
        return tag, data_text, "ledger data is not JSON", True
    return tag, parsed, "", True


def _base(
    *,
    solid: bool | None,
    content_match: bool | None,
    milestone_index: int | None,
    raw_block: dict | None,
    ledger_payload: Any,
    ledger_tag: str | None,
    status: Status,
    detail: str,
) -> VerifyResult:
    return VerifyResult(
        solid=solid,
        content_match=content_match,
        milestone_index=milestone_index,
        raw_block=raw_block,
        ledger_payload=ledger_payload,
        ledger_tag=ledger_tag,
        status=status.value,
        detail=detail,
    )


def verify_record(tag: str, payload: Any, fetch: HornetFetch) -> VerifyResult:
    if fetch.error:
        return _base(
            solid=None,
            content_match=None,
            milestone_index=None,
            raw_block=None,
            ledger_payload=None,
            ledger_tag=None,
            status=Status.PENDING,
            detail=f"Hornet unreachable: {fetch.error}",
        )

    solid: bool | None = None
    milestone: int | None = None
    if fetch.metadata is not None:
        solid = bool(fetch.metadata.get("isSolid"))
        milestone = as_milestone(fetch.metadata.get("referencedByMilestoneIndex"))

    if fetch.block is None:
        if fetch.metadata is not None and solid is False:
            return _base(
                solid=False,
                content_match=None,
                milestone_index=milestone,
                raw_block=None,
                ledger_payload=None,
                ledger_tag=None,
                status=Status.NOT_SOLID,
                detail="block is not solid and the block body is unavailable",
            )
        if fetch.block_status == 404:
            detail = "block not found on Hornet"
        else:
            detail = "Hornet block body unavailable"
        return _base(
            solid=solid,
            content_match=None,
            milestone_index=milestone,
            raw_block=None,
            ledger_payload=None,
            ledger_tag=None,
            status=Status.PENDING,
            detail=detail,
        )

    decoded_tag, decoded_payload, decode_detail, comparable = decode_tagged(fetch.block)
    if not comparable:
        return _base(
            solid=solid,
            content_match=False,
            milestone_index=milestone,
            raw_block=fetch.block,
            ledger_payload=decoded_payload,
            ledger_tag=decoded_tag,
            status=Status.PAYLOAD_MISMATCH,
            detail=decode_detail,
        )

    tag_ok = decoded_tag == tag
    payload_ok = payloads_match(payload, decoded_payload)
    if not (tag_ok and payload_ok):
        if decode_detail:
            why = decode_detail
        elif not tag_ok and not payload_ok:
            why = "tag and payload do not match the Hornet tagged data"
        elif not tag_ok:
            why = "tag does not match the Hornet tagged data"
        else:
            why = "application payload does not match the Hornet tagged data"
        return _base(
            solid=solid,
            content_match=False,
            milestone_index=milestone,
            raw_block=fetch.block,
            ledger_payload=decoded_payload,
            ledger_tag=decoded_tag,
            status=Status.PAYLOAD_MISMATCH,
            detail=why,
        )

    if fetch.metadata is None:
        return _base(
            solid=None,
            content_match=True,
            milestone_index=None,
            raw_block=fetch.block,
            ledger_payload=decoded_payload,
            ledger_tag=decoded_tag,
            status=Status.PENDING,
            detail="tagged data matches, but block metadata is unavailable",
        )
    if solid is not True:
        return _base(
            solid=False,
            content_match=True,
            milestone_index=milestone,
            raw_block=fetch.block,
            ledger_payload=decoded_payload,
            ledger_tag=decoded_tag,
            status=Status.NOT_SOLID,
            detail="tagged data matches, but the block is not solid",
        )
    if milestone is None:
        return _base(
            solid=True,
            content_match=True,
            milestone_index=None,
            raw_block=fetch.block,
            ledger_payload=decoded_payload,
            ledger_tag=decoded_tag,
            status=Status.PENDING,
            detail="tagged data matches and the block is solid, but no milestone references it yet",
        )
    return _base(
        solid=True,
        content_match=True,
        milestone_index=milestone,
        raw_block=fetch.block,
        ledger_payload=decoded_payload,
        ledger_tag=decoded_tag,
        status=Status.VERIFIED,
        detail="solid, milestone-referenced, tag and payload match",
    )

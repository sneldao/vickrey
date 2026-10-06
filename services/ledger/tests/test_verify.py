from __future__ import annotations

import json

from app.hornet import HornetFetch
from app.verify import decode_hex_utf8, payloads_match, verify_record
from tests.support import MESSAGE, TAG, matching_fetch, tagged_block


def test_semantic_json_ignores_key_order():
    left = {"temperature": 21.5, "flow_id": "flow-1"}
    right = {"flow_id": "flow-1", "temperature": 21.5}
    assert payloads_match(left, right)
    assert not payloads_match(left, {**left, "temperature": 999.9})


def test_hex_round_trip_and_prefix():
    encoded = "0x" + b"sensor".hex()
    assert decode_hex_utf8(encoded) == "sensor"
    assert decode_hex_utf8(encoded.upper().replace("0X", "0x", 1)) == "sensor"
    assert decode_hex_utf8("0x") == ""
    assert decode_hex_utf8("zz") is None


def test_verified_when_solid_and_milestone_match():
    result = verify_record(TAG, MESSAGE, matching_fetch())
    assert result.status == "VERIFIED"
    assert result.solid is True
    assert result.content_match is True
    assert result.milestone_index == 8
    assert result.ledger_tag == TAG
    assert result.ledger_payload == MESSAGE


def test_key_order_on_the_ledger_still_matches():
    encoded = json.dumps(
        {"unit": "C", "temperature": 21.5, "sensor": "edge-a", "flow_id": "flow-1"}
    )
    fetch = matching_fetch(encoded=encoded)
    result = verify_record(TAG, MESSAGE, fetch)
    assert result.status == "VERIFIED"
    assert result.content_match is True


def test_payload_mismatch_wins_over_solid():
    mutated = {**MESSAGE, "temperature": 999.9}
    result = verify_record(TAG, mutated, matching_fetch())
    assert result.status == "PAYLOAD_MISMATCH"
    assert result.content_match is False
    assert result.solid is True
    assert result.ledger_payload == MESSAGE


def test_tag_mismatch():
    result = verify_record("other.tag", MESSAGE, matching_fetch())
    assert result.status == "PAYLOAD_MISMATCH"
    assert result.content_match is False
    assert "tag" in result.detail


def test_not_solid():
    result = verify_record(TAG, MESSAGE, matching_fetch(solid=False, milestone=None))
    assert result.status == "NOT_SOLID"
    assert result.solid is False
    assert result.content_match is True


def test_solid_without_milestone_stays_pending():
    result = verify_record(TAG, MESSAGE, matching_fetch(milestone=None))
    assert result.status == "PENDING"
    assert result.solid is True
    assert result.content_match is True
    assert result.milestone_index is None


def test_milestone_zero_counts_as_referenced():
    result = verify_record(TAG, MESSAGE, matching_fetch(milestone=0))
    assert result.status == "VERIFIED"
    assert result.milestone_index == 0


def test_unreachable_and_not_found_are_pending():
    down = verify_record(
        TAG,
        MESSAGE,
        HornetFetch(None, None, None, None, error="connection refused"),
    )
    assert down.status == "PENDING"
    assert down.solid is None
    assert down.content_match is None

    missing = verify_record(TAG, MESSAGE, HornetFetch(None, None, 404, 404, error=None))
    assert missing.status == "PENDING"
    assert missing.content_match is None


def test_metadata_missing_does_not_claim_verified():
    result = verify_record(TAG, MESSAGE, matching_fetch(include_metadata=False))
    assert result.status == "PENDING"
    assert result.content_match is True
    assert result.solid is None


def test_wrong_payload_type_and_bad_hex():
    block = tagged_block(TAG, MESSAGE)
    block["payload"]["type"] = 6
    wrong = verify_record(TAG, MESSAGE, HornetFetch(block, {"isSolid": True}, 200, 200))
    assert wrong.status == "PAYLOAD_MISMATCH"
    assert wrong.content_match is False

    block = tagged_block(TAG, MESSAGE)
    block["payload"]["data"] = "0xzz"
    bad = verify_record(TAG, MESSAGE, HornetFetch(block, {"isSolid": True}, 200, 200))
    assert bad.status == "PAYLOAD_MISMATCH"
    assert "hex" in bad.detail


def test_non_json_ledger_data_mismatches():
    block = tagged_block(TAG, MESSAGE, encoded="not-json")
    result = verify_record(
        TAG,
        MESSAGE,
        HornetFetch(
            block, {"isSolid": True, "referencedByMilestoneIndex": 3}, 200, 200
        ),
    )
    assert result.status == "PAYLOAD_MISMATCH"
    assert result.ledger_payload == "not-json"
    assert result.content_match is False

"""The sample-commons seeder: labels, chaining, and honest signatures.

These records exist so the commons panel has rows in it, which means the tests
care most about the two ways seeded demo data goes wrong: being accidentally
indistinguishable from a real sighting, and being cryptographically hollow.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SEEDER = REPO / "scripts" / "seed_commons.py"


@pytest.fixture(scope="module")
def seed():
    spec = importlib.util.spec_from_file_location("seed_commons", SEEDER)
    module = importlib.util.module_from_spec(spec)
    sys.modules["seed_commons"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def anchors(seed, tmp_path_factory):
    original = seed.KEY_PATH
    seed.KEY_PATH = tmp_path_factory.mktemp("vickrey-key") / "sample_observer_key.json"
    try:
        keys = {
            o["flow"]: seed.load_or_create_key(o["flow"])[0] for o in seed.OBSERVERS
        }
        built = seed.build_anchors(keys)
    finally:
        seed.KEY_PATH = original
    return built


def test_every_seeded_record_is_labelled_as_a_sample_observer(anchors):
    """The label is the whole safety mechanism, so it is asserted first."""
    built = anchors
    assert built
    for anchor in built:
        flow = anchor["flow_id"]
        assert flow.startswith("sample-observer-"), flow
        # and this is exactly what apps/field/app.js sampleMark() tests for
        import re

        assert re.match(r"^sample-observer-", flow)


def test_seed_data_spans_several_observers_so_the_commons_is_not_one_walk(anchors):
    built = anchors
    flows = {a["flow_id"] for a in built}
    assert len(flows) >= 3
    assert len(built) >= 6


def test_every_sample_anchor_recomputes_and_verifies(anchors, seed):
    """Signatures are real, not placeholders that merely look right."""
    built = anchors
    bad = [a["block_id"] for a in built if not seed.verify_seeded(a)]
    assert bad == [], f"anchors failed self-check: {bad}"


def test_an_edited_sample_record_does_not_verify(anchors, seed):
    built = anchors
    edited = json.loads(json.dumps(built[0]))
    edited["_payload"]["species"] = "Misidentified starling"
    assert not seed.verify_seeded(edited)


def test_a_tampered_commitment_does_not_verify(anchors, seed):
    built = anchors
    edited = json.loads(json.dumps(built[0]))
    edited["message"]["commitment"] = "f" + edited["message"]["commitment"][1:]
    assert not seed.verify_seeded(edited)


def one_per_observer(anchors):
    """Anchors are grouped by flow, so consecutive items are not distinct."""
    seen: dict[str, dict] = {}
    for anchor in anchors:
        seen.setdefault(anchor["flow_id"], anchor)
    return list(seen.values())


def test_each_observer_has_its_own_device_key(anchors):
    """Attribution in the commons is per-key, so synthetic observers must not
    share one, or the sample data misrepresents how the real thing works."""
    keys = {a["flow_id"]: a["message"]["public_key"] for a in anchors}
    assert len(set(keys.values())) == len(keys), keys


def test_another_observers_signature_is_rejected(anchors, seed):
    first, second = one_per_observer(anchors)[:2]
    assert first["flow_id"] != second["flow_id"]
    assert not seed.verify_signature(
        first["message"]["commitment"],
        second["message"]["signature"],
        first["message"]["public_key"],
    )


def test_the_stored_signature_alone_verifies_from_a_commons_document(anchors, seed):
    """What --verify does: the commons holds enough to check the signature.

    It cannot recompute the commitment, because the record body is deliberately
    not stored -- that is the anchoring rule, not a gap in the seeder.
    """
    first, second = one_per_observer(anchors)[:2]
    message = first["message"]
    stored = {
        "commitment": message["commitment"],
        "signature": message["signature"],
        "public_key": message["public_key"],
    }
    assert seed.verify_signature(
        stored["commitment"], stored["signature"], stored["public_key"]
    )
    # the wrong observer's key does not check it
    assert not seed.verify_signature(
        stored["commitment"], stored["signature"], second["message"]["public_key"]
    )
    # and neither does a different commitment under the right key
    assert not seed.verify_signature(
        second["message"]["commitment"], stored["signature"], stored["public_key"]
    )


def test_a_corrected_sample_keeps_the_model_score_off_the_final_name(anchors):
    """Same rule the field client follows: a correction is the observer's call."""
    built = anchors
    corrected = [a for a in built if a["message"]["summary"]["review"] == "corrected"]
    assert corrected, "the sample data should exercise the correction path"
    for anchor in corrected:
        assert anchor["message"]["summary"]["confidence"] is None
        assert (
            anchor["_payload"]["review"]["suggested_species"]
            != anchor["message"]["summary"]["species"]
        )


def test_each_observers_records_form_a_chain(anchors):
    built = anchors
    by_flow: dict[str, list] = {}
    for anchor in built:
        by_flow.setdefault(anchor["flow_id"], []).append(anchor)
    for flow, items in by_flow.items():
        assert items[0]["message"]["prev"] is None, flow
        for previous, current in zip(items, items[1:]):
            assert current["message"]["prev"] == previous["message"]["commitment"], flow


def test_sample_locations_are_coarse(anchors):
    built = anchors
    for anchor in built:
        location = anchor["message"]["location"]
        assert location["lat"] == round(location["lat"], 2)
        assert location["lon"] == round(location["lon"], 2)


def test_the_record_body_is_never_sent_to_the_commons(anchors, seed):
    """observation_document drops unknown fields; make sure we rely on flow_id."""
    from app.atlas import observation_document

    built = anchors
    document = observation_document(
        block_id=built[0]["block_id"],
        tag=built[0]["tag"],
        flow_id=built[0]["flow_id"],
        message=built[0]["message"],
    )
    assert document["flow_id"].startswith("sample-observer-")
    assert "_payload" not in document
    assert "detail" not in document
    assert document["public_key"] == built[0]["message"]["public_key"]

import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);
const api = require("./app.js");

const verified = {
  block_id: "0xda720001",
  tag: "incident.critical",
  flow_id: "line-7",
  payload_json: {
    flowId: "line-7",
    kind: "alarm",
    sensorId: "temp-12",
    temperature: 21.5,
  },
  ledger_payload_json: {
    temperature: 21.5,
    sensorId: "temp-12",
    kind: "alarm",
    flowId: "line-7",
  },
  ledger_tag: "incident.critical",
  solid: true,
  content_match: true,
  milestone_index: 42,
  status: "VERIFIED",
  inserted_at: "2026-10-06T18:02:00.000000Z",
  detail: "solid, milestone-referenced, tag and payload match",
};

function clone(row, extra) {
  return Object.assign({}, row, extra);
}

test("key order does not count as a payload mismatch", () => {
  assert.equal(
    api.payloadsDiffer(verified.payload_json, verified.ledger_payload_json),
    false,
  );
  assert.deepEqual(
    api.changedKeys(verified.payload_json, verified.ledger_payload_json),
    [],
  );
});

test("a changed temperature is a payload mismatch", () => {
  const appPayload = Object.assign({}, verified.payload_json, {
    temperature: 999.9,
  });
  assert.equal(
    api.payloadsDiffer(appPayload, verified.ledger_payload_json),
    true,
  );
  assert.deepEqual(api.changedKeys(appPayload, verified.ledger_payload_json), [
    "temperature",
  ]);
});

test("a missing Hornet payload is not shown as a diff", () => {
  assert.equal(api.payloadsDiffer(verified.payload_json, null), false);
});

test("verified checklist is payload, solid, milestone, and tag", () => {
  const checks = api.checklist(verified);
  assert.equal(checks.payload.state, "pass");
  assert.equal(checks.solid.state, "pass");
  assert.equal(checks.milestone.state, "pass");
  assert.equal(checks.milestone.label, "Milestone 42");
  assert.equal(checks.tag.state, "pass");
  assert.match(api.pitchLine(verified), /agrees/);
});

test("payload mismatch fails the payload item and keeps solid, milestone, and tag", () => {
  const row = clone(verified, {
    status: "PAYLOAD_MISMATCH",
    content_match: false,
    payload_json: Object.assign({}, verified.payload_json, {
      temperature: 999.9,
    }),
    detail: "application payload does not match the Hornet tagged data",
  });
  const checks = api.checklist(row);
  assert.equal(checks.payload.state, "fail");
  assert.equal(checks.solid.state, "pass");
  assert.equal(checks.milestone.state, "pass");
  assert.equal(checks.tag.state, "pass");
  assert.equal(api.statusLabel(row.status), "PAYLOAD MISMATCH");
  assert.match(api.pitchLine(row), /PAYLOAD MISMATCH/);
});

test("a tag-only miss stays a mismatch and fails the tag item", () => {
  const row = clone(verified, {
    status: "PAYLOAD_MISMATCH",
    content_match: false,
    tag: "incident.demo",
    ledger_tag: "shift.note",
  });
  const checks = api.checklist(row);
  assert.equal(checks.payload.state, "pass");
  assert.equal(checks.tag.state, "fail");
  assert.match(checks.tag.detail, /shift\.note/);
  assert.match(api.pitchLine(row), /tag/);
});

test("pending leaves the checks unknown", () => {
  const row = clone(verified, {
    status: "PENDING",
    solid: null,
    content_match: null,
    milestone_index: null,
    ledger_payload_json: null,
    ledger_tag: null,
  });
  const checks = api.checklist(row);
  assert.equal(checks.payload.state, "unknown");
  assert.equal(checks.solid.state, "unknown");
  assert.equal(checks.milestone.state, "unknown");
  assert.equal(checks.tag.state, "unknown");
});

test("not solid fails solidity when the payload still matches", () => {
  const row = clone(verified, {
    status: "NOT_SOLID",
    solid: false,
    milestone_index: null,
    content_match: true,
  });
  const checks = api.checklist(row);
  assert.equal(checks.payload.state, "pass");
  assert.equal(checks.solid.state, "fail");
  assert.equal(checks.tag.state, "pass");
  assert.equal(checks.milestone.state, "wait");
});

test("highlight is incident. prefix or kind alarm", () => {
  assert.equal(api.highlightLabel(verified), "alarm");
  assert.equal(api.isHighlighted(verified), true);
  assert.equal(
    api.highlightLabel({
      tag: "incident.watch",
      payload_json: { kind: "status" },
    }),
    "incident",
  );
  assert.equal(
    api.isHighlighted({
      tag: "plant.reading",
      payload_json: { kind: "reading" },
    }),
    false,
  );
  assert.equal(
    api.isHighlighted({
      tag: "plant.reading",
      payload_json: { kind: "alarm" },
    }),
    true,
  );
  assert.equal(
    api.isHighlighted({
      tag: "Incident.critical",
      payload_json: { kind: "status" },
    }),
    false,
  );
});

test("filters accept the pitch names and the ledger status", () => {
  assert.equal(api.normalizeFilter("mismatch"), "PAYLOAD_MISMATCH");
  assert.equal(api.normalizeFilter("PAYLOAD_MISMATCH"), "PAYLOAD_MISMATCH");
  assert.equal(api.normalizeFilter("NOT SOLID"), "NOT_SOLID");
  assert.equal(api.normalizeFilter("not-solid"), "NOT_SOLID");
  assert.equal(api.normalizeFilter("verified"), "VERIFIED");
  assert.equal(api.normalizeFilter("nope"), "ALL");
  const rows = [
    verified,
    clone(verified, { block_id: "0xda720002", status: "NOT_SOLID" }),
  ];
  assert.equal(api.applyFilter(rows, "PAYLOAD_MISMATCH", "").length, 0);
  assert.equal(api.applyFilter(rows, "VERIFIED", "DA720001").length, 1);
  assert.equal(api.applyFilter(rows, "ALL", "missing").length, 0);
});

test("timeline groups by flow and orders flows by first record", () => {
  const rows = [
    clone(verified, {
      block_id: "0xda720004",
      flow_id: "line-2",
      inserted_at: "2026-10-06T18:03:00.000000Z",
    }),
    clone(verified, {
      block_id: "0xda720010",
      flow_id: "line-7",
      inserted_at: "2026-10-06T18:01:00.000000Z",
    }),
    verified,
    clone(verified, {
      block_id: "0xda720099",
      flow_id: null,
      inserted_at: "2026-10-06T18:00:00.000000Z",
    }),
  ];
  const groups = api.groupByFlow(rows);
  assert.deepEqual(
    groups.map((group) => group.flowId),
    ["line-7", "line-2", null],
  );
  assert.deepEqual(
    groups[0].messages.map((row) => row.block_id),
    ["0xda720010", "0xda720001"],
  );
});

test("block links open the Stardust dashboard and the Hornet block", () => {
  assert.equal(
    api.dashboardBlockUrl("http://localhost:31011/", "0xda720001"),
    "http://localhost:31011/explorer/block/0xda720001",
  );
  assert.equal(
    api.hornetBlockUrl("http://localhost:14265", "0xda720001"),
    "http://localhost:14265/api/core/v2/blocks/0xda720001",
  );
  assert.equal(api.dashboardBlockUrl("", "0xda720001"), "");
  assert.equal(api.httpOrigin("javascript:alert(1)"), null);
  assert.equal(
    api.apiUrl("http://localhost:8088/", "/messages?limit=500"),
    "http://localhost:8088/messages?limit=500",
  );
});

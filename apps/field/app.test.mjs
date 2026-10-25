import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);
const field = require("./app.js");
const trust = require("./trust.js");
const queue = require("./queue.js");

function entry(extra = {}) {
  return {
    observed_at: "2026-10-11T08:00:00.000Z",
    location: { lat: 51.51, lon: -0.13 },
    model_id: "gemma3",
    prev: null,
    hash: "a".repeat(64),
    signature: "c2ln",
    payload: { kind: "bird", species: "Common blackbird", confidence: 0.81 },
    ...extra,
  };
}

test("anchorMessage publishes the commitment, never the record", () => {
  const anchor = field.anchorMessage(entry(), "walk-1");
  assert.equal(anchor.flow_id, "walk-1");
  assert.equal(anchor.schema, "veles.observation/1");
  assert.equal(anchor.commitment, "a".repeat(64));
  assert.equal(anchor.signature, "c2ln");
  assert.equal(anchor.prev, null);
  assert.deepEqual(anchor.summary, {
    kind: "bird",
    species: "Common blackbird",
    confidence: 0.81,
  });
  assert.deepEqual(anchor.location, { lat: 51.51, lon: -0.13 });
  // The raw payload field and any free text stay on the device.
  assert.equal("payload" in anchor, false);
  assert.equal(JSON.stringify(anchor).includes("detail"), false);
});

test("anchorMessage tolerates a sparse entry", () => {
  const anchor = field.anchorMessage({ hash: "b".repeat(64), payload: {} });
  assert.equal(anchor.commitment, "b".repeat(64));
  assert.equal(anchor.observed_at, undefined);
  assert.deepEqual(anchor.summary, {
    kind: "other",
    species: "",
    confidence: null,
  });
});

test("relayBody posts the camelCase blockId the anchor relay requires", () => {
  const body = field.relayBody(entry(), "walk-1");
  assert.equal(body.blockId, "a".repeat(64));
  assert.equal("block_id" in body, false);
  assert.equal(body.tag, "veles.observation");
  assert.equal(body.flow_id, "walk-1");
  assert.equal(body.message.commitment, "a".repeat(64));
  assert.equal(body.message.schema, "veles.observation/1");
});

test("shieldedBody carries the commitment and nothing else", () => {
  const body = field.shieldedBody(entry());
  assert.deepEqual(Object.keys(body), ["commitment"]);
  assert.equal(body.commitment, "a".repeat(64));
  const wire = JSON.stringify(body);
  for (const leak of [
    "Common blackbird",
    "species",
    "summary",
    "location",
    "observed_at",
    "signature",
    "public_key",
    "prev",
    "flow",
  ]) {
    assert.equal(wire.includes(leak), false, `shieldedBody leaked ${leak}`);
  }
});

test("the anchor word comes from the service, never from the routing", () => {
  assert.equal(field.anchorWord({ shielded: true }), "SHIELDED");
  assert.equal(field.anchorWord({ shielded: false }), "TRANSPARENT");
  // A receipt that does not say gets the neutral word: no false claim.
  assert.equal(field.anchorWord({}), "ANCHORED");
  assert.equal(field.anchorWord(null), "ANCHORED");
});

test("the transparent fallback does not repeat the shielded note", () => {
  assert.equal(
    field.statusNote("confirmed", true).includes("reveals nothing"),
    true,
    "a shielded anchor may say the chain reveals nothing",
  );
  const transparent = field.statusNote("confirmed", false);
  assert.equal(transparent.includes("reveals nothing"), false);
  assert.equal(transparent.includes("transparent"), true);
  // Public ledger statuses are unaffected by the flag.
  assert.equal(
    field.statusNote("VERIFIED"),
    field.statusNote("VERIFIED", true),
  );
});

test("the explorer handoff carries the receipt id and the anchor service", () => {
  const url = field.explorerReceiptUrl(
    "http://127.0.0.1:8080/",
    { receipt_id: "rec_01J", txid: "deadbeef" },
    "http://127.0.0.1:8092/",
  );
  assert.equal(
    url,
    "http://127.0.0.1:8080/index.html?receipt=rec_01J&zanchor=http%3A%2F%2F127.0.0.1%3A8092#deadbeef",
  );
  // No explorer configured, or no receipt yet: no link rather than a broken one.
  assert.equal(
    field.explorerReceiptUrl("", { receipt_id: "rec_01J" }, "x"),
    "",
  );
  assert.equal(field.explorerReceiptUrl("http://x", {}, "y"), "");
});

test("resolveConfig keeps numeric config values and shielded query aliases", () => {
  const merged = field.resolveConfig(
    {
      anchorMode: "shielded",
      anchorMinDelayMs: 1500,
      zanchorUrl: "http://localhost:8092",
    },
    "?anchor=public&jitter=250",
  );
  assert.equal(merged.anchorMode, "public");
  assert.equal(merged.anchorMinDelayMs, 1500);
  assert.equal(merged.anchorJitterMs, "250");
  assert.equal(merged.zanchorUrl, "http://localhost:8092");
  assert.equal(
    field.resolveConfig({}, "?explorer=http://127.0.0.1:8080").explorerUrl,
    "http://127.0.0.1:8080",
  );
});

test("drainVerified refuses a tampered queue and sends nothing", async () => {
  const pair = await trust.generateKeyPair();
  const sealed = await trust.sealObservation({
    privateKey: pair.privateKey,
    payload: { kind: "bird", species: "European robin", confidence: 0.9 },
    modelId: "gemma3",
  });
  const tampered = field.applyTamper([sealed], 0, "Misidentified magpie")[0];
  const q = queue.createQueue();
  q.enqueue(tampered);

  let posts = 0;
  const drained = await field.drainVerified(
    q,
    pair.publicKey,
    trust,
    async () => {
      posts += 1;
    },
  );

  assert.equal(posts, 0);
  assert.equal(drained.sent.length, 0);
  assert.equal(drained.verdict.ok, false);
  assert.match(drained.error.message, /verifies/);
  assert.equal(q.size(), 1);
});

test("drainVerified refuses to send without a device key", async () => {
  const pair = await trust.generateKeyPair();
  const sealed = await trust.sealObservation({
    privateKey: pair.privateKey,
    payload: { kind: "bird", species: "European robin", confidence: 0.9 },
  });
  const q = queue.createQueue();
  q.enqueue(sealed);

  let posts = 0;
  const drained = await field.drainVerified(q, null, trust, async () => {
    posts += 1;
  });

  assert.equal(posts, 0);
  assert.equal(drained.sent.length, 0);
  assert.match(drained.error.message, /device key/);
  assert.equal(q.size(), 1);
});

test("drainVerified drains an intact queue oldest first", async () => {
  const pair = await trust.generateKeyPair();
  const first = await trust.sealObservation({
    privateKey: pair.privateKey,
    payload: { kind: "bird", species: "European robin", confidence: 0.9 },
    modelId: "gemma3",
  });
  const second = await trust.sealObservation({
    privateKey: pair.privateKey,
    prev: first.hash,
    payload: { kind: "plant", species: "Male fern", confidence: 0.7 },
    modelId: "gemma3",
  });
  const q = queue.createQueue();
  q.enqueue(first);
  q.enqueue(second);

  const sent = [];
  const drained = await field.drainVerified(
    q,
    pair.publicKey,
    trust,
    async (entry) => {
      sent.push(entry);
    },
  );

  assert.equal(drained.error, null);
  assert.equal(drained.verdict.ok, true);
  assert.deepEqual(
    sent.map((e) => e.hash),
    [first.hash, second.hash],
  );
  assert.equal(q.size(), 0);
});

test("drainVerified is a no-op on an empty queue", async () => {
  const q = queue.createQueue();
  let posts = 0;
  const drained = await field.drainVerified(q, null, trust, async () => {
    posts += 1;
  });
  assert.equal(posts, 0);
  assert.equal(drained.empty, true);
  assert.equal(drained.error, null);
});

test("drainVerified sends only the entries the anchor window has opened for", async () => {
  const pair = await trust.generateKeyPair();
  const first = await trust.sealObservation({
    privateKey: pair.privateKey,
    payload: { kind: "bird", species: "European robin", confidence: 0.9 },
    modelId: "gemma3",
  });
  const second = await trust.sealObservation({
    privateKey: pair.privateKey,
    prev: first.hash,
    payload: { kind: "plant", species: "Male fern", confidence: 0.7 },
    modelId: "gemma3",
  });
  const q = queue.createQueue();
  q.enqueue(first);
  q.enqueue(second);

  const sent = [];
  const drained = await field.drainVerified(
    q,
    pair.publicKey,
    trust,
    async (entry) => {
      sent.push(entry);
    },
    (entry) => entry.hash === first.hash,
  );

  assert.equal(drained.error, null);
  assert.equal(drained.verdict.ok, true, "the held entry still chain-verifies");
  assert.deepEqual(
    sent.map((e) => e.hash),
    [first.hash],
  );
  assert.deepEqual(
    drained.remaining.map((e) => e.hash),
    [second.hash],
  );
  assert.equal(q.size(), 1);
});

test("summaryOf and entryTitle fall back sensibly", () => {
  assert.equal(field.entryTitle(entry()), "Common blackbird");
  assert.equal(
    field.entryTitle(entry({ payload: { kind: "plant" } })),
    "plant (unidentified)",
  );
  assert.equal(
    field.entryTitle(entry({ payload: {} })),
    "unidentified observation",
  );
  assert.equal(field.summaryOf(entry()).confidence, 0.81);
});

test("shortHash elides long values and passes short ones through", () => {
  assert.match(field.shortHash("a".repeat(64)), /^a{10}…a{4}$/);
  assert.equal(field.shortHash("abc"), "abc");
  assert.equal(field.shortHash(null), "—");
});

test("applyTamper changes only the payload and leaves the seal intact", () => {
  const original = [entry()];
  const edited = field.applyTamper(original, 0, "Misidentified magpie");
  assert.equal(edited[0].payload.species, "Misidentified magpie");
  assert.equal(edited[0].payload._demo_edited, true);
  // The seal is untouched — that is exactly why the edit is detectable.
  assert.equal(edited[0].hash, original[0].hash);
  assert.equal(edited[0].signature, original[0].signature);
  // The caller's array is not mutated.
  assert.equal(original[0].payload.species, "Common blackbird");
  assert.equal(original[0].payload._demo_edited, undefined);
});

test("applyTamper refuses an index that does not exist", () => {
  assert.throws(() => field.applyTamper([entry()], 3), /no entry at index 3/);
  assert.throws(() => field.applyTamper([], 0), /no entry at index 0/);
});

test("verdictText names the crack and the reason", () => {
  assert.match(field.verdictText({ ok: true }), /seal holds/);
  assert.match(
    field.verdictText({ ok: false, brokenAt: 0, reason: "hash" }),
    /entry 1[\s\S]*edited/,
  );
  assert.match(
    field.verdictText({ ok: false, brokenAt: 1, reason: "link" }),
    /entry 2[\s\S]*chain link/,
  );
  assert.match(
    field.verdictText({ ok: false, brokenAt: 2, reason: "signature" }),
    /entry 3[\s\S]*forged/,
  );
  assert.match(field.verdictText(null), /Not checked/);
});

test("statusNote explains every ledger status", () => {
  for (const status of [
    "VERIFIED",
    "PENDING",
    "NOT_SOLID",
    "PAYLOAD_MISMATCH",
  ]) {
    assert.ok(field.statusNote(status).length > 10, status);
  }
  assert.match(field.statusNote("PAYLOAD_MISMATCH"), /block never changed/);
  assert.match(field.statusNote("SOMETHING_ELSE"), /Unrecognised/);
});

test("ledgerStatus handles a missing response", () => {
  assert.equal(field.ledgerStatus(null).status, "UNKNOWN");
  assert.equal(field.ledgerStatus({ status: "VERIFIED" }).status, "VERIFIED");
});

test("sampleIdentification is clearly labelled as a sample", () => {
  const sample = field.sampleIdentification();
  assert.equal(sample.sample, true);
  assert.equal(sample.model_id, "sample");
  assert.match(sample.detail, /Sample identification/);
});

test("the whole demo: seal, tamper, and the chain stops verifying", async () => {
  const pair = await trust.generateKeyPair();
  const publicKey = pair.publicKey;

  const first = await trust.sealObservation({
    privateKey: pair.privateKey,
    payload: { kind: "bird", species: "Common blackbird", confidence: 0.81 },
    modelId: "gemma3",
  });
  const second = await trust.sealObservation({
    privateKey: pair.privateKey,
    prev: first.hash,
    payload: { kind: "plant", species: "Foxglove", confidence: 0.7 },
    modelId: "gemma3",
  });

  const sealed = [first, second];
  assert.equal((await trust.verifyChain(sealed, publicKey)).ok, true);

  // The anchor for the sealed record is commitment-only...
  const anchor = field.anchorMessage(second, "walk-1");
  assert.equal(anchor.commitment, second.hash);
  assert.equal(anchor.prev, first.hash);

  // ...and editing the record cracks the seal without touching the anchor.
  const edited = field.applyTamper(sealed, 1, "Misidentified magpie");
  const verdict = await trust.verifyChain(edited, publicKey);
  assert.equal(verdict.ok, false);
  assert.equal(verdict.brokenAt, 1);
  assert.equal(verdict.reason, "hash");
  // The anchor never moved, so the ledger still holds the original truth.
  assert.equal(anchor.commitment, second.hash);
  assert.equal(anchor.signature, second.signature);
});

test("the demo also catches a forged device key", async () => {
  const pair = await trust.generateKeyPair();
  const other = await trust.generateKeyPair();
  const sealed = await trust.sealObservation({
    privateKey: pair.privateKey,
    payload: { kind: "bird", species: "Common blackbird", confidence: 0.5 },
  });
  const verdict = await trust.verifyChain([sealed], other.publicKey);
  assert.equal(verdict.ok, false);
  assert.equal(verdict.reason, "signature");
});

test("resolveConfig merges the file config with URL overrides", () => {
  const base = { ledgerUrl: "http://localhost:8088", model: "gemma3" };
  assert.deepEqual(field.resolveConfig(base, ""), base);
  assert.deepEqual(field.resolveConfig(base, "?ledger=http://127.0.0.1:8095"), {
    ledgerUrl: "http://127.0.0.1:8095",
    model: "gemma3",
  });
  assert.deepEqual(
    field.resolveConfig(base, "?commons=http://127.0.0.1:8088&model=gemma3:4b"),
    {
      ledgerUrl: "http://localhost:8088",
      model: "gemma3:4b",
      commonsUrl: "http://127.0.0.1:8088",
    },
  );
});

test("resolveConfig ignores empty overrides and unknown keys", () => {
  const base = { ledgerUrl: "http://localhost:8088" };
  assert.deepEqual(field.resolveConfig(base, "?ledger=&nope=1"), base);
  assert.deepEqual(field.resolveConfig(base, "?ledger=   "), base);
  assert.deepEqual(field.resolveConfig(undefined, ""), {});
});

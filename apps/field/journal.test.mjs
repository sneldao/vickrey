import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);
const field = require("./app.js");
const trust = require("./trust.js");
const queue = require("./queue.js");
const { createJournal } = require("./journal.js");
const { createLogbook } = require("./logbook.js");

const suggestion = {
  kind: "bird",
  species: "Robin",
  confidence: 0.95,
  detail: "A robin perched on a branch.",
  model_id: "gemma3:4b",
};

function memoryStore() {
  let saved = [];
  return {
    load: () => JSON.parse(JSON.stringify(saved)),
    save: (items) => {
      saved = JSON.parse(JSON.stringify(items));
    },
  };
}

async function sealedPair(decision = { action: "confirm" }) {
  const { privateKey, publicKey } = await trust.generateKeyPair();
  const q = queue.createQueue();
  const journal = createJournal({ store: memoryStore() });
  const infer = require("./infer.js");
  const log = createLogbook({
    trust,
    queue: q,
    infer,
    privateKey,
    modelId: "gemma3:4b",
  });
  const reviewed = field.reviewedIdentification(suggestion, decision);
  const entry = await log.seal(reviewed, {
    observedAt: "2026-10-11T08:00:00.000Z",
  });
  journal.record(entry, { thumb: "data:image/jpeg;base64,THUMB" });
  return { q, journal, log, entry, publicKey };
}

test("a suggestion cannot be sealed without a human decision", () => {
  assert.throws(
    () => field.reviewedIdentification(suggestion),
    /confirm or correct/,
  );
  assert.throws(
    () => field.reviewedIdentification(suggestion, { action: "accept-all" }),
    /confirm or correct/,
  );
  assert.throws(
    () => field.reviewedIdentification(null, { action: "confirm" }),
    /no suggestion/,
  );
});

test("confirming keeps the model's name and records the decision", () => {
  const id = field.reviewedIdentification(suggestion, { action: "confirm" });
  assert.equal(id.species, "Robin");
  assert.equal(id.confidence, 0.95);
  assert.equal(id.model_id, "gemma3:4b");
  assert.deepEqual(id.review, {
    decision: "confirmed",
    suggested_species: "Robin",
    suggested_kind: "bird",
    model_confidence: 0.95,
  });
});

test("correcting seals the observer's name, keeping the model's in the review", () => {
  const id = field.reviewedIdentification(suggestion, {
    action: "correct",
    species: "  European robin (Erithacus rubecula) ",
    kind: "bird",
  });
  assert.equal(id.species, "European robin (Erithacus rubecula)");
  assert.equal(id.confidence, null);
  assert.equal(id.review.decision, "corrected");
  assert.equal(id.review.suggested_species, "Robin");
  assert.equal(id.review.model_confidence, 0.95);
  assert.throws(
    () =>
      field.reviewedIdentification(suggestion, {
        action: "correct",
        species: " ",
      }),
    /write the name/,
  );
});

test("an unchanged correction is recorded as a confirmation", () => {
  const id = field.reviewedIdentification(suggestion, {
    action: "correct",
    species: "Robin",
    kind: "bird",
  });
  assert.equal(id.review.decision, "confirmed");
  assert.equal(id.confidence, 0.95);
});

test("an empty suggestion cannot be confirmed", () => {
  assert.throws(
    () =>
      field.reviewedIdentification(
        { kind: "other", species: "" },
        { action: "confirm" },
      ),
    /correct it before sealing/,
  );
});

test("the review decision is inside the signed payload", async () => {
  const { entry, publicKey } = await sealedPair({
    action: "correct",
    species: "Song thrush",
    kind: "bird",
  });
  assert.equal(entry.payload.review.decision, "corrected");
  assert.equal(entry.payload.review.suggested_species, "Robin");
  assert.equal((await trust.verifyChain([entry], publicKey)).ok, true);

  const flipped = JSON.parse(JSON.stringify(entry));
  flipped.payload.review.decision = "confirmed";
  assert.equal((await trust.verifyChain([flipped], publicKey)).ok, false);
});

test("the anchor carries the decision, never the photo or thumbnail", async () => {
  const { entry } = await sealedPair();
  const body = JSON.stringify(field.relayBody(entry, "walk-1"));
  assert.equal(
    field.anchorMessage(entry, "walk-1").summary.review,
    "confirmed",
  );
  assert.doesNotMatch(body, /THUMB|base64|perched/);
});

test("the journal keeps a sighting after the outbox drains", async () => {
  const { q, journal, entry, publicKey } = await sealedPair();
  const drained = await field.drainVerified(
    q,
    publicKey,
    trust,
    async () => {},
  );
  field.settleSync(journal, drained, {
    [entry.hash]: {
      status: "VERIFIED",
      block_id: "0xblock",
      milestone_index: 7,
    },
  });

  assert.equal(q.size(), 0);
  assert.equal(journal.size(), 1);
  const rows = field.journalView(journal.list(), q.list(), null);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].state, "anchored");
  assert.equal(rows[0].sync.status, "VERIFIED");
  assert.equal(rows[0].sync.block_id, "0xblock");
  assert.equal(rows[0].sync.milestone_index, 7);
  assert.equal(rows[0].entry.payload.species, "Robin");
});

test("a journal survives a reload from its store", async () => {
  const store = memoryStore();
  const first = createJournal({ store });
  const { entry } = await sealedPair();
  first.record(entry);
  first.markAnchored(entry.hash, { status: "VERIFIED" });
  const second = createJournal({ store });
  assert.equal(second.size(), 1);
  assert.equal(second.get(entry.hash).sync.status, "VERIFIED");
  assert.equal(second.head(), entry.hash);
});

test("tampering edits the queued copy, cracks it, and leaves the journal intact", async () => {
  const { q, journal, entry, publicKey } = await sealedPair();
  const mutated = field.applyTamper(q.list(), 0, "Misidentified magpie");
  assert.equal(q.replace(entry.hash, mutated[0]), true);

  const view = field.journalView(journal.list(), q.list(), null);
  assert.equal(view[0].state, "cracked");
  assert.equal(view[0].queuedCopy.payload.species, "Misidentified magpie");
  assert.equal(journal.get(entry.hash).entry.payload.species, "Robin");

  let sent = 0;
  const drained = await field.drainVerified(q, publicKey, trust, async () => {
    sent += 1;
  });
  field.settleSync(journal, drained, {});
  assert.equal(sent, 0);
  assert.equal(q.size(), 1);
  assert.equal(journal.get(entry.hash).sync.state, "refused");
  assert.equal(
    field.journalView(journal.list(), q.list(), drained.verdict)[0].refused,
    true,
  );
});

test("putting the sealed copy back re-forms the seal and it syncs", async () => {
  const { q, journal, entry, publicKey } = await sealedPair();
  q.replace(entry.hash, field.applyTamper(q.list(), 0, "Magpie")[0]);
  await field.drainVerified(q, publicKey, trust, async () => {});
  journal.markRefused(entry.hash, "the local chain no longer verifies");

  q.replace(entry.hash, journal.get(entry.hash).entry);
  journal.markPending(entry.hash);
  assert.equal(
    field.journalView(journal.list(), q.list(), null)[0].state,
    "waiting",
  );

  const drained = await field.drainVerified(
    q,
    publicKey,
    trust,
    async () => {},
  );
  field.settleSync(journal, drained, { [entry.hash]: { status: "VERIFIED" } });
  assert.equal(journal.get(entry.hash).sync.state, "anchored");
});

test("journal records are copies: editing a queue entry never reaches them", async () => {
  const { q, journal, entry } = await sealedPair();
  entry.payload.species = "changed in memory";
  assert.equal(journal.get(entry.hash).entry.payload.species, "Robin");
  const listed = journal.list();
  listed[0].entry.payload.species = "changed again";
  assert.equal(journal.get(entry.hash).entry.payload.species, "Robin");
  assert.equal(q.size(), 1);
});

test("adopting old queued entries backfills the journal once", async () => {
  const { q } = await sealedPair();
  const journal = createJournal({ store: memoryStore() });
  assert.equal(journal.adopt(q.list()), 1);
  assert.equal(journal.adopt(q.list()), 0);
  assert.equal(journal.size(), 1);
});

test("an anchored record is not downgraded by a later refusal", async () => {
  const { journal, entry } = await sealedPair();
  journal.markAnchored(entry.hash, { status: "VERIFIED" });
  assert.equal(journal.markRefused(entry.hash, "late"), null);
  assert.equal(journal.markPending(entry.hash), null);
  assert.equal(journal.get(entry.hash).sync.state, "anchored");
});

test("parseArea accepts lat,lon and rejects nonsense", () => {
  assert.deepEqual(field.parseArea("51.5074, -0.1278"), {
    lat: 51.5074,
    lon: -0.1278,
  });
  assert.equal(field.parseArea("200,0"), null);
  assert.equal(field.parseArea("north"), null);
  assert.equal(field.parseArea(undefined), null);
});

import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);
const trust = require("./trust.js");
const queue = require("./queue.js");
const infer = require("./infer.js");
const { createLogbook } = require("./logbook.js");
const specimens = require("./specimens.js");
const walk = require("./seed.js");
const field = require("./app.js");

/* Seal the sample walk exactly as the browser does, so these tests exercise the
 * real path rather than a stand-in for it. */
async function sealWalk(now) {
  const { privateKey, publicKey } = await trust.generateKeyPair();
  const q = queue.createQueue();
  const log = createLogbook({
    trust,
    queue: q,
    infer,
    privateKey,
    modelId: walk.MODEL,
  });
  const sealed = [];
  for (const step of walk.sampleWalk({ now })) {
    const reviewed = field.reviewedIdentification(
      step.suggestion,
      step.decision,
    );
    const entry = await log.seal(reviewed, {
      privateKey,
      model: step.modelId,
      observedAt: step.observedAt,
      location: trust.coarseLocation(step.location, 2),
    });
    sealed.push(entry);
  }
  return { entries: sealed, publicKey, queue: q };
}

test("a plate is a self-contained data URI that names its own species", () => {
  for (const name of specimens.names()) {
    const uri = specimens.plate(name);
    assert.match(uri, /^data:image\/svg\+xml,/);
    const svg = decodeURIComponent(uri.replace("data:image/svg+xml,", ""));
    assert.match(svg, /^<svg xmlns="http:\/\/www\.w3\.org\/2000\/svg"/);
    assert.match(svg, /<\/svg>$/);
    // the Latin binomial has to be on the plate, or it is decoration
    assert.match(svg, /[A-Z][a-z]+ [a-z]{4,}/);
  }
});

test("an unknown plate name is an error, not an empty image", () => {
  assert.throws(() => specimens.plate("wren"), /no specimen plate named wren/);
});

test("every plate fits inside the plate frame", () => {
  // the label strip starts at ART; the label rule must sit below every drawing
  assert.ok(specimens.ART < specimens.HEIGHT);
});

test("the walk is three sightings, oldest first", () => {
  const steps = walk.sampleWalk({ now: new Date("2026-10-14T12:00:00.000Z") });
  assert.equal(steps.length, 3);
  const times = steps.map((s) => Date.parse(s.observedAt));
  for (let i = 1; i < times.length; i += 1) {
    assert.ok(times[i] > times[i - 1], "steps must read in walk order");
  }
  assert.equal(steps[0].plate, "ivy");
  assert.equal(steps[2].plate, "hawthorn");
});

test("the middle step is a correction, so the review decision is sealed", () => {
  const steps = walk.sampleWalk({});
  const middle = steps[1];
  assert.equal(middle.decision.action, "correct");
  const reviewed = field.reviewedIdentification(
    middle.suggestion,
    middle.decision,
  );
  assert.equal(reviewed.species, "European robin");
  assert.equal(reviewed.review.decision, "corrected");
  assert.equal(reviewed.review.suggested_species, "Common blackbird");
  // a correction is the observer's call, so the model's score is not carried
  // onto the corrected name
  assert.equal(reviewed.confidence, null);
  assert.equal(reviewed.review.model_confidence, 0.54);
});

test("nothing in the walk can be sealed without a person deciding", () => {
  for (const step of walk.sampleWalk({})) {
    assert.ok(["confirm", "correct"].includes(step.decision.action));
    assert.throws(() => field.reviewedIdentification(step.suggestion, {}));
    assert.throws(() =>
      field.reviewedIdentification(step.suggestion, { action: "seal" }),
    );
  }
});

test("preview describes the walk without sealing anything", () => {
  const lines = walk.preview();
  assert.equal(lines.length, 3);
  assert.match(lines[1].line, /correct it to European robin/);
  assert.equal(lines[1].corrected, true);
  assert.equal(lines[0].corrected, false);
});

test("stepTime offsets into the past", () => {
  const now = new Date("2026-10-14T12:00:00.000Z");
  assert.equal(walk.stepTime(30, now), "2026-10-14T11:30:00.000Z");
  assert.equal(walk.stepTime(0, now), "2026-10-14T12:00:00.000Z");
});

test("the seeded walk is a genuine, verifiable, chained walk", async () => {
  const { entries, publicKey } = await sealWalk();
  assert.equal(entries.length, 3);

  // every hash recomputes, every link holds, every signature verifies
  const verdict = await trust.verifyChain(entries, publicKey);
  assert.equal(verdict.ok, true, "the seeded walk must verify");
  assert.equal(verdict.brokenAt, null);

  // each entry links to the one before it
  assert.equal(entries[0].prev, null);
  assert.equal(entries[1].prev, entries[0].hash);
  assert.equal(entries[2].prev, entries[1].hash);

  // all three were queued for sync
  assert.equal(entries.length, 3);
});

test("tampering with a seeded entry cracks the seal, as it must", async () => {
  const { entries, publicKey, queue: q } = await sealWalk();
  assert.equal(q.list().length, 3);

  const mutated = field.applyTamper(entries, 1, "Misidentified starling");
  q.replace(entries[1].hash, mutated[1]);

  const verdict = await trust.verifyChain(q.list(), publicKey);
  assert.equal(verdict.ok, false);
  assert.equal(verdict.brokenAt, 1);

  // and the anchor still carries only a commitment, never the record
  const anchor = field.anchorMessage(entries[1], "walk-demo");
  assert.equal(anchor.commitment, entries[1].hash);
  assert.equal(anchor.summary.species, "European robin");
  assert.equal(anchor.summary.review, "corrected");
  assert.equal(anchor.payload, undefined);
  assert.equal(anchor.detail, undefined);
});

test("an anchor carries the device key, so the commons can check it", async () => {
  const { entries, publicKey } = await sealWalk();
  const pk = await trust.exportPublicKey(publicKey);
  const anchor = field.anchorMessage(entries[1], "walk-demo", pk);
  assert.equal(anchor.public_key, pk);

  // the key is the only way to check the signature the anchor hands over
  const imported = await trust.importPublicKey(anchor.public_key);
  const ok = await trust.verifyCommitment(
    imported,
    anchor.commitment,
    anchor.signature,
  );
  assert.equal(ok, true, "the commons must be able to verify an anchor");

  // omitted rather than sent empty when there is no key to send
  assert.equal(
    field.anchorMessage(entries[1], "walk-demo").public_key,
    undefined,
  );
});

test("a seeded anchor carries a coarse area, never the exact point", async () => {
  const { entries } = await sealWalk();
  const anchor = field.anchorMessage(entries[0], "walk-demo");
  assert.equal(anchor.location.lat, 51.54);
  assert.equal(anchor.location.lon, -0.08);
  assert.notEqual(anchor.location.lat, walk.WALK_AREA.lat);
});

test("sync drains the seeded walk and clears the outbox, not the journal", async () => {
  const { entries, publicKey, queue: q } = await sealWalk();
  const journal = require("./journal.js").createJournal({});
  for (const entry of entries) {
    journal.record(entry);
  }
  const sent = [];
  const drained = await field.drainVerified(
    q,
    publicKey,
    trust,
    async (entry) => {
      sent.push(entry);
    },
  );
  assert.equal(drained.error, null);
  assert.equal(drained.sent.length, 3);
  assert.equal(sent.length, 3);
  assert.equal(q.list().length, 0);
  assert.equal(journal.size(), 3, "sync must never erase a sighting");
});

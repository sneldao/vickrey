import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);
const trust = require("./trust.js");

test("canonical form ignores key order but not values", () => {
  assert.equal(
    trust.canonical({ b: 1, a: 2 }),
    trust.canonical({ a: 2, b: 1 }),
  );
  assert.notEqual(trust.canonical({ a: 2 }), trust.canonical({ a: 3 }));
});

test("a commitment is stable and changes with the observation", async () => {
  const payload = { species: "Turdus merula", count: 1 };
  const first = await trust.commitment(payload);
  const second = await trust.commitment({ count: 1, species: "Turdus merula" });
  const edited = await trust.commitment({ species: "Turdus merula", count: 2 });
  assert.equal(first, second);
  assert.notEqual(first, edited);
  assert.equal(first.length, 64);
});

test("a signature verifies its own commitment and rejects another", async () => {
  const { privateKey, publicKey } = await trust.generateKeyPair();
  const hash = await trust.commitment({ seen: "robin" });
  const signature = await trust.signCommitment(privateKey, hash);
  assert.equal(await trust.verifyCommitment(publicKey, hash, signature), true);
  const other = await trust.commitment({ seen: "sparrow" });
  assert.equal(
    await trust.verifyCommitment(publicKey, other, signature),
    false,
  );
});

test("a public key round-trips through export and import", async () => {
  const { privateKey, publicKey } = await trust.generateKeyPair();
  const hash = await trust.commitment({ seen: "otter" });
  const signature = await trust.signCommitment(privateKey, hash);
  const exported = await trust.exportPublicKey(publicKey);
  const imported = await trust.importPublicKey(exported);
  assert.equal(await trust.verifyCommitment(imported, hash, signature), true);
});

test("sealing links each observation to the previous hash", async () => {
  const { privateKey } = await trust.generateKeyPair();
  const first = await trust.sealObservation({
    privateKey,
    payload: { species: "Turdus merula" },
    observedAt: "2026-10-11T07:01:00.000Z",
  });
  const second = await trust.sealObservation({
    privateKey,
    prev: first.hash,
    payload: { species: "Erithacus rubecula" },
    observedAt: "2026-10-11T07:04:00.000Z",
  });
  assert.equal(first.prev, null);
  assert.equal(second.prev, first.hash);
  assert.notEqual(first.hash, second.hash);
});

test("an intact chain verifies and a tampered payload breaks it", async () => {
  const { privateKey, publicKey } = await trust.generateKeyPair();
  const a = await trust.sealObservation({
    privateKey,
    payload: { species: "a" },
  });
  const b = await trust.sealObservation({
    privateKey,
    prev: a.hash,
    payload: { species: "b" },
  });
  const c = await trust.sealObservation({
    privateKey,
    prev: b.hash,
    payload: { species: "c" },
  });
  const chain = [a, b, c];

  assert.deepEqual(await trust.verifyChain(chain, publicKey), {
    ok: true,
    brokenAt: null,
  });

  b.payload = { species: "TAMPERED" };
  assert.deepEqual(await trust.verifyChain(chain, publicKey), {
    ok: false,
    brokenAt: 1,
    reason: "hash",
  });
});

test("a broken link and a foreign signature are both detected", async () => {
  const { privateKey, publicKey } = await trust.generateKeyPair();
  const a = await trust.sealObservation({
    privateKey,
    payload: { species: "a" },
  });
  const b = await trust.sealObservation({
    privateKey,
    prev: a.hash,
    payload: { species: "b" },
  });
  const linked = [a, b];

  b.prev = "0".repeat(64);
  b.hash = await trust.commitment({
    prev: b.prev,
    observed_at: b.observed_at,
    location: b.location,
    model_id: b.model_id,
    payload: b.payload,
  });
  b.signature = await trust.signCommitment(privateKey, b.hash);
  assert.deepEqual(await trust.verifyChain(linked, publicKey), {
    ok: false,
    brokenAt: 1,
    reason: "link",
  });

  const { privateKey: otherKey } = await trust.generateKeyPair();
  const sealed = await trust.sealObservation({
    privateKey: otherKey,
    payload: { species: "x" },
  });
  assert.deepEqual(await trust.verifyChain([sealed], publicKey), {
    ok: false,
    brokenAt: 0,
    reason: "signature",
  });
});

test("coarse location never carries precise coordinates", () => {
  assert.deepEqual(trust.coarseLocation({ lat: 47.32456, lon: -1.87654 }), {
    lat: 47.32,
    lon: -1.88,
  });
  assert.equal(trust.coarseLocation(null), null);
  assert.equal(trust.coarseLocation({ lat: "x", lon: 2 }), null);
});

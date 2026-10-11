import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);
const trust = require("./trust.js");
const queue = require("./queue.js");
const infer = require("./infer.js");
const { createLogbook } = require("./logbook.js");

function reply(kind, species, confidence) {
  const content = JSON.stringify({
    kind,
    species,
    confidence,
    detail: "seen on the walk",
  });
  return async () => ({
    ok: true,
    status: 200,
    json: async () => ({ choices: [{ message: { content } }] }),
  });
}

test("observe identifies, seals, queues, and chains on the device", async () => {
  const { privateKey, publicKey } = await trust.generateKeyPair();
  const q = queue.createQueue();
  const log = createLogbook({
    trust,
    queue: q,
    infer,
    privateKey,
    modelId: "gemma3",
  });

  const first = await log.observe({
    imageBase64: "AAAA",
    fetchImpl: reply("bird", "European robin", 0.9),
    observedAt: "2026-10-11T07:00:00.000Z",
  });
  const second = await log.observe({
    imageBase64: "BBBB",
    fetchImpl: reply("plant", "Male fern", 0.8),
    observedAt: "2026-10-11T07:05:00.000Z",
  });

  assert.equal(first.payload.kind, "bird");
  assert.equal(first.payload.species, "European robin");
  assert.equal(first.prev, null);
  assert.equal(second.prev, first.hash);
  assert.equal(log.size(), 2);
  assert.equal(log.head(), second.hash);

  const check = await trust.verifyChain(log.pending(), publicKey);
  assert.equal(check.ok, true);
});

test("seal signs a precomputed identification without calling infer", async () => {
  const { privateKey, publicKey } = await trust.generateKeyPair();
  const q = queue.createQueue();
  let calls = 0;
  const spyInfer = {
    identify: async () => {
      calls += 1;
      throw new Error("infer should not run for a sealed id");
    },
  };
  const log = createLogbook({ trust, queue: q, infer: spyInfer, privateKey });

  const entry = await log.seal(
    {
      kind: "bird",
      species: "Common blackbird",
      confidence: 0.81,
      model_id: "gemma3",
    },
    { observedAt: "2026-10-11T07:00:00.000Z" },
  );

  assert.equal(calls, 0);
  assert.equal(entry.model_id, "gemma3");
  assert.equal(entry.payload.species, "Common blackbird");
  assert.equal(log.size(), 1);
  assert.equal(log.head(), entry.hash);
  assert.equal((await trust.verifyChain(log.pending(), publicKey)).ok, true);
});

test("seal signs under the device key supplied for that call", async () => {
  const device = await trust.generateKeyPair();
  const other = await trust.generateKeyPair();
  const log = createLogbook({
    trust,
    queue: queue.createQueue(),
    infer,
    privateKey: other.privateKey,
  });

  const entry = await log.seal(
    { kind: "plant", species: "Male fern", confidence: 0.8 },
    { privateKey: device.privateKey },
  );

  assert.equal(
    await trust.verifyCommitment(device.publicKey, entry.hash, entry.signature),
    true,
  );
  assert.equal(
    await trust.verifyCommitment(other.publicKey, entry.hash, entry.signature),
    false,
  );
});

test("seal keeps the sample model id", async () => {
  const { privateKey } = await trust.generateKeyPair();
  const log = createLogbook({
    trust,
    queue: queue.createQueue(),
    infer,
    privateKey,
  });

  const entry = await log.seal({
    kind: "bird",
    species: "Common blackbird",
    confidence: 0.81,
    detail: "Sample identification — no local model was reachable.",
    model_id: "sample",
    sample: true,
  });

  assert.equal(entry.model_id, "sample");
});

test("seal refuses to queue without a device key", async () => {
  const q = queue.createQueue();
  const log = createLogbook({ trust, queue: q, infer });
  await assert.rejects(
    () => log.seal({ kind: "bird", species: "Robin" }),
    /device key/,
  );
  assert.equal(q.size(), 0);
  assert.equal(log.head(), null);
});

test("a fresh logbook resumes the chain from the last queued entry", async () => {
  const { privateKey } = await trust.generateKeyPair();
  const store = queue.memoryStore();
  const first = createLogbook({
    trust,
    queue: queue.createQueue({ store }),
    infer,
    privateKey,
  });
  const sealed = await first.seal({
    kind: "bird",
    species: "European robin",
    confidence: 0.9,
  });

  const resumed = createLogbook({
    trust,
    queue: queue.createQueue({ store }),
    infer,
    privateKey,
  });
  assert.equal(resumed.head(), sealed.hash);
  const next = await resumed.seal({
    kind: "plant",
    species: "Male fern",
    confidence: 0.7,
  });
  assert.equal(next.prev, sealed.hash);
  assert.equal(resumed.head(), next.hash);
});

test("an explicit head wins over the queued tail", async () => {
  const { privateKey } = await trust.generateKeyPair();
  const store = queue.memoryStore();
  const first = createLogbook({
    trust,
    queue: queue.createQueue({ store }),
    infer,
    privateKey,
  });
  await first.seal({
    kind: "bird",
    species: "European robin",
    confidence: 0.9,
  });

  const pinned = createLogbook({
    trust,
    queue: queue.createQueue({ store }),
    infer,
    privateKey,
    head: "seeded-head",
  });
  assert.equal(pinned.head(), "seeded-head");
});

test("sync drains sealed observations once signal returns", async () => {
  const { privateKey } = await trust.generateKeyPair();
  const q = queue.createQueue();
  const log = createLogbook({ trust, queue: q, infer, privateKey });
  await log.observe({
    imageBase64: "AAAA",
    fetchImpl: reply("other", "Unclear", 0.3),
  });

  const sent = [];
  const result = await log.sync(async (entry) => {
    sent.push(entry);
  });
  assert.equal(sent.length, 1);
  assert.equal(sent[0].payload.species, "Unclear");
  assert.equal(result.error, null);
  assert.equal(log.size(), 0);
});

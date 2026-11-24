import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);
const trust = require("./trust.js");
const integrity = require("./integrity.js");
const storage = require("./storage.js");
const backup = require("./backup.js");

globalThis.VickreyQueue = require("./queue.js");
globalThis.VickreyJournal = require("./journal.js");
globalThis.VickreyTrust = trust;
globalThis.VickreyIntegrity = integrity;

async function fixture() {
  const { privateKey, publicKey } = await trust.generateKeyPair();
  const backend = storage.memoryBackend();
  const opened = await storage.openStore({ backend });
  const draws = [];
  const repo = storage.createRepository(opened, {
    privateKey: () => privateKey,
    checkpoint: integrity.sealCheckpoint,
    sealCorrection: integrity.sealCorrection,
    anchorTime(entry, plan) {
      const at = Date.now() + draws.length + 1;
      draws.push(entry.hash);
      plan[entry.hash] = at;
      return at;
    },
  });
  return { repo, backend, privateKey, publicKey, draws };
}

async function seal(repo, privateKey, species) {
  const head = repo.journal.head();
  const entry = await trust.sealObservation({
    privateKey,
    prev: head,
    observedAt: new Date().toISOString(),
    payload: { kind: "plant", species, confidence: 0.8 },
  });
  await repo.append(entry, {});
  return entry;
}

test("a record, outbox entry, schedule draw and signed head commit together", async () => {
  const { repo, privateKey, publicKey, draws } = await fixture();
  const entry = await seal(repo, privateKey, "Male fern");
  assert.equal(repo.journal.size(), 1);
  assert.equal(repo.queue.size(), 1);
  assert.equal(draws.length, 1);
  const checkpoint = repo.checkpoint();
  assert.equal(checkpoint.head, entry.hash);
  assert.equal(checkpoint.count, 1);
  assert.equal(
    (await integrity.verifyCheckpoint(checkpoint, entry.hash, 1, publicKey)).ok,
    true,
  );
});

test("a failed atomic append leaves every projection unchanged", async () => {
  const { repo, backend, privateKey } = await fixture();
  const original = backend.save;
  backend.save = async () => {
    throw new Error("disk full");
  };
  const entry = await trust.sealObservation({
    privateKey,
    payload: { species: "Fern" },
  });
  await assert.rejects(() => repo.append(entry, {}), /could not be saved/);
  backend.save = original;
  assert.equal(repo.journal.size(), 0);
  assert.equal(repo.queue.size(), 0);
  assert.equal(repo.checkpoint(), null);
  const reopened = storage.createRepository(
    await storage.openStore({ backend }),
    {},
  );
  assert.equal(reopened.journal.size(), 0);
  assert.equal(reopened.queue.size(), 0);
});

test("scalar key and flow text round-trip without double encoding", async () => {
  const { repo, backend } = await fixture();
  const saved = JSON.stringify({ pk: "saved-public-key", jwk: { kty: "OKP" } });
  await repo.setValue("vickrey.device_key", saved);
  await repo.setValue("vickrey.flow", "walk-one");
  const reopened = storage.createRepository(
    await storage.openStore({ backend }),
    {},
  );
  assert.equal(reopened.getValue("vickrey.device_key"), saved);
  assert.equal(reopened.getValue("vickrey.flow"), "walk-one");
});

test("legacy localStorage migrates without deleting its source", async () => {
  const { privateKey } = await fixture();
  const entry = await trust.sealObservation({
    privateKey,
    payload: { species: "Fern" },
  });
  const values = {
    "vickrey.device_key": null,
    "vickrey.flow": "walk-old",
    "vickrey.journal": JSON.stringify([{ entry, sync: { state: "anchored" } }]),
    "vickrey.queue": "[]",
    "vickrey.anchor_plan": JSON.stringify({ [entry.hash]: 123 }),
  };
  const localStorage = {
    getItem: (key) => values[key],
    removeItem: () => {
      throw new Error("must not delete");
    },
  };
  const opened = await storage.openStore({
    backend: storage.memoryBackend(),
    localStorage,
  });
  const repo = storage.createRepository(opened, {});
  assert.equal(repo.journal.size(), 1);
  assert.equal(repo.queue.size(), 0);
  assert.equal(repo.getValue("vickrey.flow"), "walk-old");
  assert.deepEqual(JSON.parse(opened.snapshot.values["vickrey.anchor_plan"]), {
    [entry.hash]: 123,
  });
});

test("malformed legacy storage refuses migration instead of starting empty", async () => {
  const localStorage = {
    getItem: (key) => (key === "vickrey.journal" ? "{" : null),
  };
  await assert.rejects(
    () => storage.openStore({ backend: storage.memoryBackend(), localStorage }),
    (error) => error.code === "STORAGE_CORRUPT",
  );
});

test("a truncated tail fails the signed checkpoint", async () => {
  const { repo, privateKey, publicKey } = await fixture();
  const first = await seal(repo, privateKey, "Fern");
  await seal(repo, privateKey, "Robin");
  const checkpoint = repo.checkpoint();
  assert.equal(
    (await integrity.verifyCheckpoint(checkpoint, first.hash, 1, publicKey)).ok,
    false,
  );
  assert.equal(
    (
      await integrity.verifyCheckpoint(
        { ...checkpoint, count: 1 },
        repo.journal.head(),
        1,
        publicKey,
      )
    ).ok,
    false,
  );
});

test("a retry commits the outbox and delivery state or leaves both unchanged", async () => {
  const { repo, backend, privateKey } = await fixture();
  const entry = await seal(repo, privateKey, "Fern");
  repo.queue.drain(async () => {});
  await repo.commitMemory();
  repo.journal.markFailed(entry.hash, "node rejected");
  await repo.commitMemory();

  assert.equal(await repo.requeue(entry.hash), true);
  assert.deepEqual(
    repo.queue.list().map((item) => item.hash),
    [entry.hash],
  );
  assert.equal(repo.journal.get(entry.hash).sync.state, "pending");
  const reopened = storage.createRepository(
    await storage.openStore({ backend }),
    {},
  );
  assert.deepEqual(
    reopened.queue.list().map((item) => item.hash),
    [entry.hash],
  );
  assert.equal(reopened.journal.get(entry.hash).sync.state, "pending");

  repo.journal.markFailed(entry.hash, "node rejected again");
  await repo.commitMemory();
  repo.queue.drain(async () => {});
  await repo.commitMemory();
  repo.journal.markFailed(entry.hash, "node rejected again");
  await repo.commitMemory();
  const save = backend.save;
  backend.save = async () => {
    throw new Error("disk full");
  };
  await assert.rejects(() => repo.requeue(entry.hash), /could not be saved/);
  backend.save = save;
  assert.equal(repo.queue.size(), 0);
  assert.equal(repo.journal.get(entry.hash).sync.state, "failed");
  const failed = storage.createRepository(
    await storage.openStore({ backend }),
    {},
  );
  assert.equal(failed.queue.size(), 0);
  assert.equal(failed.journal.get(entry.hash).sync.state, "failed");
});

test("corrections are signed, chained, append-only and cannot rewrite an entry", async () => {
  const { repo, privateKey, publicKey } = await fixture();
  const entry = await seal(repo, privateKey, "Fern");
  const correction = await repo.correct(
    entry.hash,
    { reason: "Wrong ID", correction: { species: "Male fern" } },
    privateKey,
  );
  assert.equal(correction.payload.supersedes, entry.hash);
  assert.equal(repo.journal.get(entry.hash).entry.payload.species, "Fern");
  const verdict = await integrity.verifyCorrections(
    repo.corrections(),
    repo.journal.list().map((r) => r.entry),
    publicKey,
  );
  assert.equal(verdict.ok, true);
  await assert.rejects(
    () => repo.correct(entry.hash, { reason: "Again" }, privateKey),
    /already has a correction/,
  );
});

test("backup v2 restores the signed head and corrections atomically", async () => {
  const { repo, backend, privateKey, publicKey } = await fixture();
  const jwk = await crypto.subtle.exportKey("jwk", privateKey);
  const pk = await trust.exportPublicKey(publicKey);
  await repo.setValue("vickrey.device_key", JSON.stringify({ jwk, pk }));
  await repo.setValue("vickrey.flow", "backup-walk");
  const first = await seal(repo, privateKey, "Fern");
  await seal(repo, privateKey, "Robin");
  await repo.correct(
    first.hash,
    { reason: "Reviewed", correction: { species: "Male fern" } },
    privateKey,
  );

  const envelope = await backup.encryptBackup(
    repo.backupStorage(),
    "correct horse battery staple",
  );
  assert.equal(envelope.schema, "vickrey.backup/2");

  const targetBackend = storage.memoryBackend();
  const target = storage.createRepository(
    await storage.openStore({ backend: targetBackend }),
    {},
  );
  const restored = await backup.restoreBackup(
    target.backupStorage(),
    envelope,
    "correct horse battery staple",
  );
  assert.deepEqual(restored.checkpoint, repo.checkpoint());
  assert.deepEqual(restored.corrections, repo.corrections());
  assert.deepEqual(target.checkpoint(), repo.checkpoint());
  assert.deepEqual(target.corrections(), repo.corrections());
  assert.equal(target.journal.size(), 2);
  assert.equal(target.queue.size(), 2);
  assert.equal(target.getValue("vickrey.flow"), "backup-walk");

  const reopened = storage.createRepository(
    await storage.openStore({ backend: targetBackend }),
    {},
  );
  assert.deepEqual(reopened.checkpoint(), repo.checkpoint());
  assert.deepEqual(reopened.corrections(), repo.corrections());
});

test("a v2 backup cannot silently drop its head into legacy storage", async () => {
  const { repo, privateKey, publicKey } = await fixture();
  const jwk = await crypto.subtle.exportKey("jwk", privateKey);
  await repo.setValue(
    "vickrey.device_key",
    JSON.stringify({ jwk, pk: await trust.exportPublicKey(publicKey) }),
  );
  await seal(repo, privateKey, "Fern");
  const envelope = await backup.encryptBackup(
    repo.backupStorage(),
    "correct horse battery staple",
  );
  const values = new Map();
  const legacy = {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
  };
  await assert.rejects(
    () =>
      backup.restoreBackup(legacy, envelope, "correct horse battery staple"),
    /cannot retain.*signed head/,
  );
  assert.equal(values.size, 0);
});

test("a legacy v1 backup restores and receives a fresh signed head", async () => {
  const { repo, privateKey, publicKey } = await fixture();
  const jwk = await crypto.subtle.exportKey("jwk", privateKey);
  await repo.setValue(
    "vickrey.device_key",
    JSON.stringify({ jwk, pk: await trust.exportPublicKey(publicKey) }),
  );
  const entry = await seal(repo, privateKey, "Fern");
  const source = repo.backupStorage();
  const legacy = { getItem: source.getItem };
  const envelope = await backup.encryptBackup(
    legacy,
    "correct horse battery staple",
  );
  assert.equal(envelope.schema, "vickrey.backup/1");

  const target = storage.createRepository(
    await storage.openStore({ backend: storage.memoryBackend() }),
    { checkpoint: integrity.sealCheckpoint },
  );
  await backup.restoreBackup(
    target.backupStorage(),
    envelope,
    "correct horse battery staple",
  );
  assert.equal(target.journal.size(), 1);
  assert.equal(target.checkpoint(), null);
  await target.ensureCheckpoint(privateKey);
  assert.equal(
    (
      await integrity.verifyCheckpoint(
        target.checkpoint(),
        entry.hash,
        1,
        publicKey,
      )
    ).ok,
    true,
  );
});

async function rewriteBackupPlaintext(envelope, mutate) {
  const passphrase = "correct horse battery staple";
  const salt = trust.base64urlToBytes(envelope.salt);
  const iv = trust.base64urlToBytes(envelope.iv);
  const base = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(passphrase),
    "PBKDF2",
    false,
    ["deriveKey"],
  );
  const key = await crypto.subtle.deriveKey(
    { name: "PBKDF2", salt, iterations: 600000, hash: "SHA-256" },
    base,
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt", "decrypt"],
  );
  const plaintext = await crypto.subtle.decrypt(
    {
      name: "AES-GCM",
      iv,
      additionalData: new TextEncoder().encode(envelope.schema),
    },
    key,
    trust.base64urlToBytes(envelope.ciphertext),
  );
  const data = JSON.parse(new TextDecoder().decode(plaintext));
  mutate(data);
  const ciphertext = await crypto.subtle.encrypt(
    {
      name: "AES-GCM",
      iv,
      additionalData: new TextEncoder().encode(envelope.schema),
    },
    key,
    new TextEncoder().encode(JSON.stringify(data)),
  );
  return {
    ...envelope,
    ciphertext: trust.bytesToBase64url(new Uint8Array(ciphertext)),
  };
}

test("a forged signed head or correction refuses restore before any write", async () => {
  const { repo, privateKey, publicKey } = await fixture();
  const jwk = await crypto.subtle.exportKey("jwk", privateKey);
  await repo.setValue(
    "vickrey.device_key",
    JSON.stringify({ jwk, pk: await trust.exportPublicKey(publicKey) }),
  );
  const first = await seal(repo, privateKey, "Fern");
  await repo.correct(
    first.hash,
    { reason: "Reviewed", correction: { species: "Male fern" } },
    privateKey,
  );
  const envelope = await backup.encryptBackup(
    repo.backupStorage(),
    "correct horse battery staple",
  );

  const truncated = await rewriteBackupPlaintext(envelope, (data) => {
    const journal = JSON.parse(data.storage["vickrey.journal"]);
    journal.pop();
    data.storage["vickrey.journal"] = JSON.stringify(journal);
    data.storage["vickrey.queue"] = "[]";
    data.storage["vickrey.anchor_plan"] = "{}";
  });
  const targetBackend = storage.memoryBackend();
  const target = storage.createRepository(
    await storage.openStore({ backend: targetBackend }),
    {},
  );
  await assert.rejects(
    () =>
      backup.restoreBackup(
        target.backupStorage(),
        truncated,
        "correct horse battery staple",
      ),
    /signed journal head|corrections/,
  );
  assert.equal(target.journal.size(), 0);
  assert.equal(target.queue.size(), 0);
  assert.equal(target.checkpoint(), null);
  assert.deepEqual(target.corrections(), []);

  const forged = await rewriteBackupPlaintext(envelope, (data) => {
    data.corrections[0].payload.correction.species = "Forged species";
  });
  await assert.rejects(
    () =>
      backup.restoreBackup(
        target.backupStorage(),
        forged,
        "correct horse battery staple",
      ),
    /corrections do not verify/,
  );
  assert.equal(target.journal.size(), 0);
  assert.equal(target.queue.size(), 0);
  assert.equal(target.checkpoint(), null);
  assert.deepEqual(target.corrections(), []);
  assert.equal(
    await targetBackend.load().then((state) => state.values["vickrey.journal"]),
    null,
  );
});

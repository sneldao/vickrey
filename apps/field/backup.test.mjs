import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);
const trust = require("./trust.js");
const backup = require("./backup.js");

const PASS = "correct horse battery staple";

function memStorage(overrides = {}) {
  const map = new Map();
  return {
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => {
      if (overrides.quota) {
        const err = new Error("quota");
        err.name = "QuotaExceededError";
        throw err;
      }
      map.set(k, String(v));
    },
    removeItem: (k) => map.delete(k),
    _map: map,
  };
}

async function seededStorage(opts = {}) {
  const storage = memStorage(opts);
  const pair = await trust.generateKeyPair();
  const jwk = await crypto.subtle.exportKey("jwk", pair.privateKey);
  const pk = await trust.exportPublicKey(pair.publicKey);
  const first = await trust.sealObservation({
    privateKey: pair.privateKey,
    payload: { kind: "bird", species: "European robin" },
    modelId: "gemma3",
  });
  const second = await trust.sealObservation({
    privateKey: pair.privateKey,
    prev: first.hash,
    payload: { kind: "plant", species: "Male fern" },
    modelId: "gemma3",
  });
  storage.setItem("vickrey.device_key", JSON.stringify({ jwk, pk }));
  storage.setItem("vickrey.flow", "walk-test");
  storage.setItem(
    "vickrey.journal",
    JSON.stringify([
      {
        entry: first,
        thumb: null,
        recorded_at: "t1",
        sync: { state: "pending" },
      },
      {
        entry: second,
        thumb: null,
        recorded_at: "t2",
        sync: { state: "pending" },
      },
    ]),
  );
  storage.setItem(
    "vickrey.queue",
    JSON.stringify(opts.queue ?? [first, second]),
  );
  storage.setItem(
    "vickrey.anchor_plan",
    JSON.stringify({ [first.hash]: 12345 }),
  );
  return { storage, pair, first, second, jwk, pk };
}

test("encrypted roundtrip restores the allowlisted keys", async () => {
  const { storage } = await seededStorage();
  const envelope = await backup.encryptBackup(storage, PASS);
  assert.equal(envelope.schema, "vickrey.backup/1");
  assert.equal(envelope.kdf, "PBKDF2-SHA256");
  assert.equal(envelope.iterations, 600000);
  assert.equal(JSON.stringify(envelope).includes("European robin"), false);

  const target = memStorage();
  const restored = await backup.restoreBackup(target, envelope, PASS);
  assert.equal(restored["vickrey.flow"], "walk-test");
  assert.equal(restored["vickrey.journal"], storage.getItem("vickrey.journal"));
  assert.equal(
    target.getItem("vickrey.device_key"),
    storage.getItem("vickrey.device_key"),
  );
  // No unrelated storage keys were touched.
  assert.equal(target.getItem("unrelated"), null);
});

test("a wrong passphrase or altered ciphertext fails before any write", async () => {
  const { storage } = await seededStorage();
  const envelope = await backup.encryptBackup(storage, PASS);
  const target = memStorage();
  target.setItem("sentinel", "keep");
  await assert.rejects(
    () => backup.restoreBackup(target, envelope, "definitely wrong password"),
    /decrypted|passphrase/,
  );
  const tampered = { ...envelope };
  const bytes = trust.base64urlToBytes(envelope.ciphertext);
  bytes[10] ^= 1;
  tampered.ciphertext = trust.bytesToBase64url(bytes);
  await assert.rejects(() => backup.decryptBackup(tampered, PASS), /decrypted/);
  assert.equal(target.getItem("sentinel"), "keep");
  assert.equal(target.getItem("vickrey.journal"), null);
});

test("schema, kdf and iteration fields are enforced exactly", async () => {
  const { storage } = await seededStorage();
  const envelope = await backup.encryptBackup(storage, PASS);
  await assert.rejects(
    () => backup.decryptBackup({ ...envelope, schema: "other" }, PASS),
    /schema/,
  );
  await assert.rejects(
    () => backup.decryptBackup({ ...envelope, kdf: "PBKDF2-SHA1" }, PASS),
    /kdf/,
  );
  // No arbitrary KDF work from an untrusted file: only the fixed count.
  await assert.rejects(
    () => backup.decryptBackup({ ...envelope, iterations: 1 }, PASS),
    /iterations/,
  );
  await assert.rejects(
    () => backup.decryptBackup({ schema: "vickrey.backup-data/1" }, PASS),
    /schema/,
  );
});

async function forgedEnvelope(mutate) {
  const { storage } = await seededStorage();
  const envelope = await backup.encryptBackup(storage, PASS);
  const data = {
    schema: "vickrey.backup-data/1",
    storage: Object.fromEntries(
      backup.STORAGE_KEYS.map((k) => [k, storage.getItem(k)]),
    ),
  };
  mutate(data);
  const salt = trust.base64urlToBytes(envelope.salt);
  const iv = trust.base64urlToBytes(envelope.iv);
  const base = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(PASS),
    "PBKDF2",
    false,
    ["deriveKey"],
  );
  const key = await crypto.subtle.deriveKey(
    { name: "PBKDF2", salt, iterations: 600000, hash: "SHA-256" },
    base,
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt"],
  );
  const ciphertext = await crypto.subtle.encrypt(
    {
      name: "AES-GCM",
      iv,
      additionalData: new TextEncoder().encode("vickrey.backup/1"),
    },
    key,
    new TextEncoder().encode(JSON.stringify(data)),
  );
  return {
    ...envelope,
    ciphertext: trust.bytesToBase64url(new Uint8Array(ciphertext)),
  };
}

test("extra or prototype keys in the payload are rejected", async () => {
  const extra = await forgedEnvelope((data) => {
    data.storage["vickrey.extra"] = "x";
  });
  await assert.rejects(
    () => backup.decryptBackup(extra, PASS),
    /unexpected key/,
  );
  const proto = await forgedEnvelope((data) => {
    Object.defineProperty(data.storage, "__proto__", {
      value: "x",
      enumerable: true,
    });
  });
  await assert.rejects(
    () => backup.decryptBackup(proto, PASS),
    /unexpected key|storage is not an object/,
  );
  const wrongSchema = await forgedEnvelope((data) => {
    data.schema = "vickrey.backup-data/0";
  });
  await assert.rejects(() => backup.decryptBackup(wrongSchema, PASS), /schema/);
});

test("a broken journal chain or queue mismatch refuses export and restore", async () => {
  const { storage, first } = await seededStorage();
  const journal = JSON.parse(storage.getItem("vickrey.journal"));
  journal[1].entry.payload.species = "edited after sealing";
  storage.setItem("vickrey.journal", JSON.stringify(journal));
  await assert.rejects(
    () => backup.encryptBackup(storage, PASS),
    /journal chain/,
  );

  const { storage: storage2 } = await seededStorage();
  const queue = JSON.parse(storage2.getItem("vickrey.queue"));
  queue[0] = { ...queue[0], payload: { kind: "plant" } };
  storage2.setItem("vickrey.queue", JSON.stringify(queue));
  await assert.rejects(
    () => backup.encryptBackup(storage2, PASS),
    /differs from the sealed record|64-hex hash/,
  );

  const { storage: storage3 } = await seededStorage();
  storage3.setItem("vickrey.queue", "[]");
  const queue3 = [
    { hash: "0".repeat(64), signature: "x", observed_at: "t", payload: {} },
  ];
  storage3.setItem("vickrey.queue", JSON.stringify(queue3));
  await assert.rejects(
    () => backup.encryptBackup(storage3, PASS),
    /no matching journal record/,
  );
});

test("missing or mismatched device key is refused", async () => {
  const { storage } = await seededStorage();
  storage.removeItem("vickrey.device_key");
  await assert.rejects(() => backup.encryptBackup(storage, PASS), /device key/);
  const { storage: s2, pk } = await seededStorage();
  const other = await trust.generateKeyPair();
  const jwk2 = await crypto.subtle.exportKey("jwk", other.privateKey);
  s2.setItem("vickrey.device_key", JSON.stringify({ jwk: jwk2, pk }));
  await assert.rejects(
    () => backup.encryptBackup(s2, PASS),
    /halves do not match|cannot be imported/,
  );
});

test("restore refuses a non-empty journal or outbox", async () => {
  const { storage } = await seededStorage();
  const envelope = await backup.encryptBackup(storage, PASS);
  await assert.rejects(
    () => backup.restoreBackup(storage, envelope, PASS),
    /empty device/,
  );
  const busy = memStorage();
  busy.setItem("vickrey.journal", JSON.stringify([{ entry: {} }]));
  await assert.rejects(
    () => backup.restoreBackup(busy, envelope, PASS),
    /empty device/,
  );
});

test("a failed write rolls every key back", async () => {
  const { storage } = await seededStorage();
  const envelope = await backup.encryptBackup(storage, PASS);
  const target = memStorage();
  let calls = 0;
  const realSet = target.setItem;
  target.setItem = (k, v) => {
    calls += 1;
    if (k === "vickrey.journal") {
      const err = new Error("quota");
      err.name = "QuotaExceededError";
      throw err;
    }
    realSet(k, v);
  };
  await assert.rejects(
    () => backup.restoreBackup(target, envelope, PASS),
    /quota/,
  );
  // device_key was written before journal threw; rollback removed it again.
  assert.equal(target.getItem("vickrey.device_key"), null);
  assert.equal(target.getItem("vickrey.flow"), null);
});

test("short passphrases are refused on both sides", async () => {
  const { storage } = await seededStorage();
  await assert.rejects(
    () => backup.encryptBackup(storage, "short"),
    /at least 12/,
  );
  const envelope = await backup.encryptBackup(storage, PASS);
  await assert.rejects(
    () => backup.decryptBackup(envelope, "short"),
    /at least 12/,
  );
});

/* Vickrey encrypted backup — local only.
 *
 * Everything the field client owns lives in five localStorage keys. A backup
 * is those keys encrypted with AES-256-GCM under a passphrase the user
 * chooses (PBKDF2-SHA256, 600k iterations, fresh salt and IV). The file never
 * leaves the device unless the user moves it; the passphrase is never stored
 * or sent anywhere. Restore refuses a device that already holds a journal or
 * an outbox, validates everything cryptographically before writing a byte,
 * and rolls back if a write fails.
 */
(function (root, factory) {
  var api = factory(root);
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  if (typeof window !== "undefined" && typeof document !== "undefined") {
    window.VickreyBackup = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function (root) {
  "use strict";

  var STORAGE_KEYS = [
    "vickrey.device_key",
    "vickrey.flow",
    "vickrey.journal",
    "vickrey.queue",
    "vickrey.anchor_plan",
  ];
  var ENVELOPE_SCHEMA = "vickrey.backup/1";
  var DATA_SCHEMA = "vickrey.backup-data/1";
  var KDF = "PBKDF2-SHA256";
  var ITERATIONS = 600000;
  var MAX_BYTES = 10 * 1024 * 1024;
  var MIN_PASSPHRASE = 12;
  var KEY_CHECK = "vickrey.backup-key-check";
  var HASH_RE = /^[0-9a-f]{64}$/;

  var te = new TextEncoder();
  var td = new TextDecoder();

  function trustModule() {
    if (root.VickreyTrust) {
      return root.VickreyTrust;
    }
    if (typeof module === "object" && module.exports) {
      return require("./trust.js");
    }
    throw new Error("VickreyTrust is not loaded");
  }

  function subtle() {
    var c = root.crypto || (typeof crypto !== "undefined" ? crypto : null);
    if (!c || !c.subtle) {
      throw new Error("Web Crypto is not available");
    }
    return c.subtle;
  }

  function randomBytes(n) {
    var c = root.crypto || (typeof crypto !== "undefined" ? crypto : null);
    var out = new Uint8Array(n);
    c.getRandomValues(out);
    return out;
  }

  function isPlainObject(value) {
    return Boolean(value) && typeof value === "object" && !Array.isArray(value);
  }

  function fail(message) {
    throw new Error("invalid backup: " + message);
  }

  function checkPassphrase(passphrase) {
    if (typeof passphrase !== "string" || passphrase.length < MIN_PASSPHRASE) {
      throw new Error(
        "the passphrase must be at least " + MIN_PASSPHRASE + " characters",
      );
    }
  }

  async function deriveKey(passphrase, salt, iterations) {
    var base = await subtle().importKey(
      "raw",
      te.encode(passphrase),
      "PBKDF2",
      false,
      ["deriveKey"],
    );
    return subtle().deriveKey(
      {
        name: "PBKDF2",
        salt: salt,
        iterations: iterations,
        hash: "SHA-256",
      },
      base,
      { name: "AES-GCM", length: 256 },
      false,
      ["encrypt", "decrypt"],
    );
  }

  function readKeys(storage) {
    var out = {};
    STORAGE_KEYS.forEach(function (key) {
      var value = storage.getItem(key);
      out[key] = typeof value === "string" ? value : null;
    });
    return out;
  }

  function checkEntryShape(entry, where) {
    if (!isPlainObject(entry)) {
      fail(where + " entry is not an object");
    }
    if (typeof entry.hash !== "string" || !HASH_RE.test(entry.hash)) {
      fail(where + " entry has no 64-hex hash");
    }
    if (typeof entry.signature !== "string" || !entry.signature) {
      fail(where + " entry has no signature");
    }
    if (typeof entry.observed_at !== "string" || !entry.observed_at) {
      fail(where + " entry has no observed_at");
    }
    if (!isPlainObject(entry.payload)) {
      fail(where + " entry has no payload");
    }
  }

  function parseJson(text, where) {
    if (text === null || text === undefined) {
      return null;
    }
    if (typeof text !== "string") {
      fail(where + " is not stored text");
    }
    try {
      return JSON.parse(text);
    } catch (err) {
      fail(where + " is not valid JSON");
    }
  }

  /* Everything about the plaintext that must hold before it is encrypted or
   * restored: exact key allowlist, per-key shapes, a device key whose public
   * and private halves really belong together, an intact journal chain under
   * that key, and a queue whose entries match the journal's sealed copies. */
  async function validateStorage(storage, trust) {
    var deviceKey = parseJson(storage["vickrey.device_key"], "device key");
    if (
      !isPlainObject(deviceKey) ||
      !isPlainObject(deviceKey.jwk) ||
      typeof deviceKey.pk !== "string"
    ) {
      fail("a backup needs a valid device key");
    }
    var pair;
    try {
      pair = {
        privateKey: await subtle().importKey(
          "jwk",
          deviceKey.jwk,
          { name: "Ed25519" },
          false,
          ["sign"],
        ),
        publicKey: await trust.importPublicKey(deviceKey.pk),
      };
    } catch (err) {
      fail("the device key cannot be imported");
    }
    var challenge = await trust.signCommitment(pair.privateKey, KEY_CHECK);
    var keyOk = await trust.verifyCommitment(
      pair.publicKey,
      KEY_CHECK,
      challenge,
    );
    if (!keyOk) {
      fail("the device key's public and private halves do not match");
    }

    var flow = storage["vickrey.flow"];
    if (flow !== null && typeof flow !== "string") {
      fail("flow is not stored text");
    }

    var journal = parseJson(storage["vickrey.journal"], "journal") || [];
    if (!Array.isArray(journal)) {
      fail("journal is not a list");
    }
    var entries = [];
    var byHash = {};
    var SYNC_STATES = { pending: 1, anchored: 1, refused: 1, failed: 1 };
    journal.forEach(function (record, i) {
      if (!isPlainObject(record)) {
        fail("journal record " + (i + 1) + " is not an object");
      }
      checkEntryShape(record.entry, "journal record " + (i + 1));
      /* sync drives mounting (journalView, markPending): it must be an
       * object whose state is one the app knows how to render. */
      var sync = record.sync;
      if (
        sync !== undefined &&
        (!isPlainObject(sync) || !SYNC_STATES[sync.state])
      ) {
        fail("journal record " + (i + 1) + " has an invalid sync state");
      }
      entries.push(record.entry);
      byHash[record.entry.hash] = record.entry;
    });
    var verdict = await trust.verifyChain(entries, pair.publicKey);
    if (!verdict.ok) {
      fail("the journal chain does not verify (" + verdict.reason + ")");
    }

    var queue = parseJson(storage["vickrey.queue"], "queue") || [];
    if (!Array.isArray(queue)) {
      fail("queue is not a list");
    }
    queue.forEach(function (entry, i) {
      checkEntryShape(entry, "queue entry " + (i + 1));
      var sealed = byHash[entry.hash];
      if (!sealed) {
        fail("queue entry " + (i + 1) + " has no matching journal record");
      }
      if (trust.canonical(sealed) !== trust.canonical(entry)) {
        fail("queue entry " + (i + 1) + " differs from the sealed record");
      }
    });

    var plan = parseJson(storage["vickrey.anchor_plan"], "anchor plan") || {};
    if (!isPlainObject(plan)) {
      fail("anchor plan is not an object");
    }
    Object.keys(plan).forEach(function (key) {
      if (!HASH_RE.test(key)) {
        fail("anchor plan key is not a 64-hex commitment");
      }
      var draw = plan[key];
      if (typeof draw !== "number" || !isFinite(draw) || draw <= 0) {
        fail("anchor plan holds an invalid draw");
      }
    });
  }

  function checkData(data) {
    if (!isPlainObject(data) || data.schema !== DATA_SCHEMA) {
      fail('plaintext schema is not "' + DATA_SCHEMA + '"');
    }
    if (!isPlainObject(data.storage)) {
      fail("plaintext storage is not an object");
    }
    var allowed = {};
    STORAGE_KEYS.forEach(function (key) {
      allowed[key] = true;
    });
    Object.keys(data.storage).forEach(function (key) {
      // hasOwnProperty, not a truthy lookup: "__proto__" resolves to
      // Object.prototype on a plain object and would slip through.
      if (!Object.prototype.hasOwnProperty.call(allowed, key)) {
        fail("unexpected key in backup: " + key);
      }
    });
    var storage = {};
    STORAGE_KEYS.forEach(function (key) {
      /* Missing keys are not silently filled: a well-formed backup states
       * every allowlisted key, null meaning "absent on the device". */
      if (!Object.prototype.hasOwnProperty.call(data.storage, key)) {
        fail("backup is missing key: " + key);
      }
      var value = data.storage[key];
      if (value !== null && typeof value !== "string") {
        fail("stored value for " + key + " is not text");
      }
      storage[key] = typeof value === "string" ? value : null;
    });
    return storage;
  }

  /* Snapshot the five keys and encrypt them. Throws unless the device key is
   * valid and the journal chain and queue are consistent, so a backup never
   * preserves a state the app could not mount. */
  async function encryptBackup(storage, passphrase) {
    var trust = trustModule();
    checkPassphrase(passphrase);
    var snapshot = readKeys(storage);
    await validateStorage(snapshot, trust);
    var plaintext = te.encode(
      JSON.stringify({ schema: DATA_SCHEMA, storage: snapshot }),
    );
    if (plaintext.length > MAX_BYTES) {
      throw new Error("the backup is larger than 10 MB");
    }
    var salt = randomBytes(16);
    var iv = randomBytes(12);
    var key = await deriveKey(passphrase, salt, ITERATIONS);
    var ciphertext = await subtle().encrypt(
      {
        name: "AES-GCM",
        iv: iv,
        additionalData: te.encode(ENVELOPE_SCHEMA),
      },
      key,
      plaintext,
    );
    var envelope = {
      schema: ENVELOPE_SCHEMA,
      kdf: KDF,
      iterations: ITERATIONS,
      salt: trust.bytesToBase64url(salt),
      iv: trust.bytesToBase64url(iv),
      ciphertext: trust.bytesToBase64url(new Uint8Array(ciphertext)),
    };
    /* The file must be importable: a plaintext just under the byte cap can
       still encode past it. */
    if (JSON.stringify(envelope).length > MAX_BYTES) {
      throw new Error("the encrypted backup is larger than 10 MB");
    }
    return envelope;
  }

  /* Decrypt and fully validate an envelope. Returns the allowlisted storage
   * object; throws on any schema, shape, or cryptographic mismatch. Nothing
   * is written here — authentication happens before any restore write. */
  async function decryptBackup(envelope, passphrase) {
    var trust = trustModule();
    checkPassphrase(passphrase);
    if (!isPlainObject(envelope) || envelope.schema !== ENVELOPE_SCHEMA) {
      fail('envelope schema is not "' + ENVELOPE_SCHEMA + '"');
    }
    if (envelope.kdf !== KDF) {
      fail("unrecognised kdf");
    }
    // Fixed work factor: a hostile file must not pick the KDF cost.
    if (envelope.iterations !== ITERATIONS) {
      fail("unexpected kdf iterations");
    }
    if (JSON.stringify(envelope).length > MAX_BYTES) {
      fail("envelope is larger than 10 MB");
    }
    var salt, iv, ciphertext;
    try {
      salt = trust.base64urlToBytes(String(envelope.salt || ""));
      iv = trust.base64urlToBytes(String(envelope.iv || ""));
      ciphertext = trust.base64urlToBytes(String(envelope.ciphertext || ""));
    } catch (err) {
      fail("envelope fields are not base64url");
    }
    if (salt.length !== 16 || iv.length !== 12) {
      fail("salt or iv has the wrong length");
    }
    var key = await deriveKey(passphrase, salt, ITERATIONS);
    var plaintext;
    try {
      plaintext = await subtle().decrypt(
        {
          name: "AES-GCM",
          iv: iv,
          additionalData: te.encode(ENVELOPE_SCHEMA),
        },
        key,
        ciphertext,
      );
    } catch (err) {
      throw new Error(
        "the backup could not be decrypted — wrong passphrase or a changed file",
      );
    }
    if (plaintext.byteLength > MAX_BYTES) {
      fail("decrypted backup is larger than 10 MB");
    }
    var data;
    try {
      data = JSON.parse(td.decode(plaintext));
    } catch (err) {
      fail("decrypted backup is not valid JSON");
    }
    var storage = checkData(data);
    await validateStorage(storage, trust);
    return storage;
  }

  /* Write a validated backup onto an empty device. Refuses when a journal or
   * an outbox already exists; a lone auto-generated device key is replaced.
   * All writes are rolled back if any one of them fails. */
  async function restoreBackup(storage, envelope, passphrase) {
    var data = await decryptBackup(envelope, passphrase);
    var journalText = storage.getItem("vickrey.journal");
    var queueText = storage.getItem("vickrey.queue");
    var journal = journalText === null ? [] : parseJson(journalText, "journal");
    var queue = queueText === null ? [] : parseJson(queueText, "queue");
    /* Non-empty means records exist; unparseable or non-array storage is
     * also a refusal — overwriting unknown state is not "empty". */
    if (
      !Array.isArray(journal) ||
      !Array.isArray(queue) ||
      journal.length ||
      queue.length
    ) {
      throw new Error(
        "restore needs an empty device — this one already holds records",
      );
    }
    var previous = readKeys(storage);
    try {
      STORAGE_KEYS.forEach(function (key) {
        if (data[key] === null) {
          storage.removeItem(key);
        } else {
          storage.setItem(key, data[key]);
        }
      });
    } catch (err) {
      var rolledBack = true;
      STORAGE_KEYS.forEach(function (key) {
        try {
          if (previous[key] === null) {
            storage.removeItem(key);
          } else {
            storage.setItem(key, previous[key]);
          }
        } catch (rollbackErr) {
          rolledBack = false;
        }
      });
      if (!rolledBack) {
        throw new Error(
          "restore failed partway and the previous keys could not all be " +
            "put back — this device's storage may be inconsistent. Your " +
            "encrypted backup file is unchanged; retry on a cleared device.",
        );
      }
      throw err;
    }
    return data;
  }

  return {
    STORAGE_KEYS: STORAGE_KEYS,
    decryptBackup: decryptBackup,
    encryptBackup: encryptBackup,
    restoreBackup: restoreBackup,
  };
});

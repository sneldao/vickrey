/* Signed journal heads and append-only corrections. */
(function (root, factory) {
  var api = factory(root);
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  if (typeof window !== "undefined" && typeof document !== "undefined") {
    window.VickreyIntegrity = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function (root) {
  "use strict";

  var CHECKPOINT_SCHEMA = "vickrey.journal-checkpoint/1";
  var CORRECTION_SCHEMA = "vickrey.correction/1";
  var HASH_RE = /^[0-9a-f]{64}$/;

  function trust() {
    return root.VickreyTrust;
  }

  async function sealCheckpoint(head, count, privateKey) {
    if (
      !HASH_RE.test(head || "") ||
      !Number.isSafeInteger(count) ||
      count < 1
    ) {
      throw new Error(
        "A checkpoint needs a journal head and a positive entry count.",
      );
    }
    var body = { schema: CHECKPOINT_SCHEMA, head: head, count: count };
    var hash = await trust().commitment(body);
    return {
      schema: CHECKPOINT_SCHEMA,
      head: head,
      count: count,
      hash: hash,
      signature: await trust().signCommitment(privateKey, hash),
    };
  }

  async function verifyCheckpoint(checkpoint, head, count, publicKey) {
    if (!checkpoint || checkpoint.schema !== CHECKPOINT_SCHEMA) {
      return { ok: false, reason: "checkpoint_missing" };
    }
    if (
      checkpoint.head !== head ||
      checkpoint.count !== count ||
      !HASH_RE.test(checkpoint.hash || "") ||
      typeof checkpoint.signature !== "string" ||
      !checkpoint.signature
    ) {
      return { ok: false, reason: "checkpoint_mismatch" };
    }
    var expected = await trust().commitment({
      schema: CHECKPOINT_SCHEMA,
      head: head,
      count: count,
    });
    if (expected !== checkpoint.hash) {
      return { ok: false, reason: "checkpoint_hash" };
    }
    var valid = await trust().verifyCommitment(
      publicKey,
      checkpoint.hash,
      checkpoint.signature,
    );
    return valid ? { ok: true } : { ok: false, reason: "checkpoint_signature" };
  }

  async function sealCorrection(options) {
    options = options || {};
    if (!HASH_RE.test(options.supersedes || "")) {
      throw new Error("A correction must reference a sealed commitment.");
    }
    if (
      !options.payload ||
      typeof options.payload !== "object" ||
      Array.isArray(options.payload)
    ) {
      throw new Error("A correction needs a payload.");
    }
    return trust().sealObservation({
      privateKey: options.privateKey,
      prev: options.prev || null,
      observedAt: new Date().toISOString(),
      modelId: CORRECTION_SCHEMA,
      payload: {
        schema: CORRECTION_SCHEMA,
        supersedes: options.supersedes,
        reason: String(options.payload.reason || "").slice(0, 500),
        correction: options.payload.correction,
      },
    });
  }

  async function verifyCorrections(entries, journalEntries, publicKey) {
    entries = entries || [];
    var known = {};
    (journalEntries || []).forEach(function (entry) {
      known[entry.hash] = true;
    });
    var superseded = {};
    for (var i = 0; i < entries.length; i++) {
      var entry = entries[i];
      if (
        !entry ||
        entry.model_id !== CORRECTION_SCHEMA ||
        !entry.payload ||
        entry.payload.schema !== CORRECTION_SCHEMA ||
        !HASH_RE.test(entry.payload.supersedes || "") ||
        !known[entry.payload.supersedes] ||
        superseded[entry.payload.supersedes]
      ) {
        return { ok: false, brokenAt: i, reason: "correction_shape" };
      }
      superseded[entry.payload.supersedes] = true;
    }
    var verdict = await trust().verifyChain(entries, publicKey);
    verdict.checked = entries.length;
    return verdict;
  }

  return {
    CHECKPOINT_SCHEMA: CHECKPOINT_SCHEMA,
    CORRECTION_SCHEMA: CORRECTION_SCHEMA,
    sealCheckpoint: sealCheckpoint,
    sealCorrection: sealCorrection,
    verifyCheckpoint: verifyCheckpoint,
    verifyCorrections: verifyCorrections,
  };
});

/* Vickrey disclosure bundle — verify and build, locally.
 *
 * A disclosure is a file the record's owner chooses to share: one sealed
 * entry, the device public key, and the anchor service's receipt and
 * verification response. This module checks the parts that can be checked
 * without trusting anyone: the entry recomputes to its commitment and its
 * signature verifies under the bundled key. The embedded `verification`
 * block is a historical assertion by the anchor service — it is carried,
 * displayed, and compared, but it is NOT treated as fresh proof; a new
 * check has to be asked of the configured anchor service.
 */
(function (root, factory) {
  var api = factory(root);
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  if (typeof window !== "undefined" && typeof document !== "undefined") {
    window.VickreyDisclosure = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function (root) {
  "use strict";

  var SCHEMA = "vickrey.disclosure/1";
  var HASH_RE = /^[0-9a-f]{64}$/;

  function trustModule() {
    if (root.VickreyTrust) {
      return root.VickreyTrust;
    }
    if (typeof module === "object" && module.exports) {
      return require("./trust.js");
    }
    throw new Error("VickreyTrust is not loaded");
  }

  function isPlainObject(value) {
    return Boolean(value) && typeof value === "object" && !Array.isArray(value);
  }

  function fail(message) {
    throw new Error("invalid disclosure: " + message);
  }

  function checkEntry(entry) {
    if (!isPlainObject(entry)) {
      fail("entry is not an object");
    }
    if (typeof entry.hash !== "string" || !HASH_RE.test(entry.hash)) {
      fail("entry.hash is not a 64-hex commitment");
    }
    if (typeof entry.signature !== "string" || !entry.signature) {
      fail("entry.signature is missing");
    }
    if (typeof entry.observed_at !== "string" || !entry.observed_at) {
      fail("entry.observed_at is missing");
    }
    if (!isPlainObject(entry.payload)) {
      fail("entry.payload is missing");
    }
    if (
      entry.prev !== null &&
      entry.prev !== undefined &&
      !HASH_RE.test(entry.prev)
    ) {
      fail("entry.prev is not a 64-hex link");
    }
  }

  function checkReceipt(receipt) {
    if (!isPlainObject(receipt)) {
      fail("receipt is not an object");
    }
    if (typeof receipt.receipt_id !== "string" || !receipt.receipt_id) {
      fail("receipt.receipt_id is missing");
    }
    if (
      typeof receipt.commitment !== "string" ||
      !HASH_RE.test(receipt.commitment)
    ) {
      fail("receipt.commitment is not a 64-hex commitment");
    }
  }

  /* Local verification of a shared bundle. Checks only what can be checked
   * here: the entry hashes to its commitment and the signature verifies
   * under the bundled device key, and the receipt really names that
   * commitment. One entry verifies its own seal — it does not establish
   * that the sender's whole journal chain is intact, and the embedded
   * `verification` is a past service assertion, not a fresh fact. Throws
   * on anything that does not check out. */
  async function verifyDisclosure(bundle) {
    var trust = trustModule();
    if (!isPlainObject(bundle)) {
      fail("bundle is not an object");
    }
    if (bundle.schema !== SCHEMA) {
      fail('schema is not "' + SCHEMA + '"');
    }
    var entry = bundle.entry;
    checkEntry(entry);
    if (typeof bundle.public_key !== "string" || !bundle.public_key) {
      fail("public_key is missing");
    }
    checkReceipt(bundle.receipt);
    if (bundle.receipt.commitment !== entry.hash) {
      fail("receipt commitment does not match the entry hash");
    }
    var publicKey;
    try {
      publicKey = await trust.importPublicKey(bundle.public_key);
    } catch (err) {
      fail("public_key cannot be imported");
    }
    var verdict = await trust.verifyChain([entry], publicKey);
    if (!verdict.ok) {
      fail("entry does not verify (" + verdict.reason + ")");
    }
    return {
      entryVerified: true,
      signatureVerified: true,
      commitment: entry.hash,
      receipt: bundle.receipt,
    };
  }

  /* Assemble the shareable bundle from the parts the owner holds: the sealed
   * entry, the device public key text, and the anchor service's disclosure
   * response ({receipt, verification}). Only the contract fields are
   * carried; nothing else leaves the device. The bundle is verified before
   * it is returned so a malformed response never produces a bad file. */
  function pick(obj, keys) {
    var out = {};
    (keys || []).forEach(function (key) {
      if (obj && obj[key] !== undefined) {
        out[key] = obj[key];
      }
    });
    return out;
  }

  var ENTRY_KEYS = [
    "observed_at",
    "location",
    "model_id",
    "payload",
    "prev",
    "hash",
    "signature",
  ];
  var RECEIPT_KEYS = [
    "receipt_id",
    "commitment",
    "status",
    "mode",
    "shielded",
    "txid",
    "height",
    "anchored_at",
    "error",
  ];
  var VERIFICATION_KEYS = [
    "receipt_id",
    "commitment",
    "txid",
    "height",
    "confirmations",
    "network",
    "transaction_verified",
    "commitment_verified",
    "binding",
    "verification_source",
    "reason",
  ];

  /* Assemble the shareable bundle from the parts the owner holds: the sealed
   * entry, the device public key text, and the anchor service's disclosure
   * response ({receipt, verification}). Only the contract fields are carried
   * — an unexpected field in the service's answer or the entry never leaves
   * the device inside this file. The bundle is verified before it is
   * returned so a malformed response never produces a bad file. */
  async function buildDisclosure(entry, publicKeyText, disclosureResponse) {
    var response = disclosureResponse || {};
    var bundle = {
      schema: SCHEMA,
      entry: pick(entry, ENTRY_KEYS),
      public_key: publicKeyText,
      receipt: pick(response.receipt, RECEIPT_KEYS),
      verification: pick(response.verification, VERIFICATION_KEYS),
    };
    await verifyDisclosure(bundle);
    return bundle;
  }

  return {
    SCHEMA: SCHEMA,
    buildDisclosure: buildDisclosure,
    verifyDisclosure: verifyDisclosure,
  };
});

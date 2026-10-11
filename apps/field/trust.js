/* Vickrey trust core.
 *
 * The seal, in code: canonicalise an observation, hash it into a commitment,
 * sign that commitment with the device key, and chain each entry to the one
 * before it. Editing any past entry breaks the chain; forging the signature
 * fails verification. Works with the Web Crypto API in both the browser and
 * Node, so the same code runs on the phone and in tests.
 */
(function (root, factory) {
  var api = factory(root);
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  if (typeof window !== "undefined" && typeof document !== "undefined") {
    window.VickreyTrust = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function (root) {
  "use strict";

  var subtle = root.crypto && root.crypto.subtle ? root.crypto.subtle : null;
  var te = new TextEncoder();

  function canonical(value) {
    if (value === null || typeof value !== "object") {
      return JSON.stringify(value);
    }
    if (Array.isArray(value)) {
      return "[" + value.map(canonical).join(",") + "]";
    }
    var keys = Object.keys(value).sort();
    return (
      "{" +
      keys
        .map(function (key) {
          return JSON.stringify(key) + ":" + canonical(value[key]);
        })
        .join(",") +
      "}"
    );
  }

  function bytesToHex(bytes) {
    var out = "";
    for (var i = 0; i < bytes.length; i++) {
      out += bytes[i].toString(16).padStart(2, "0");
    }
    return out;
  }

  function bytesToBase64url(bytes) {
    var binary = "";
    for (var i = 0; i < bytes.length; i++) {
      binary += String.fromCharCode(bytes[i]);
    }
    return btoa(binary)
      .replace(/\+/g, "-")
      .replace(/\//g, "_")
      .replace(/=+$/, "");
  }

  function base64urlToBytes(text) {
    var padded = text.replace(/-/g, "+").replace(/_/g, "/");
    while (padded.length % 4) {
      padded += "=";
    }
    var binary = atob(padded);
    var bytes = new Uint8Array(binary.length);
    for (var i = 0; i < binary.length; i++) {
      bytes[i] = binary.charCodeAt(i);
    }
    return bytes;
  }

  async function sha256Hex(text) {
    var digest = await subtle.digest("SHA-256", te.encode(text));
    return bytesToHex(new Uint8Array(digest));
  }

  /* The commitment: a stable hash of the canonical form. */
  function commitment(value) {
    return sha256Hex(canonical(value));
  }

  async function generateKeyPair() {
    return subtle.generateKey({ name: "Ed25519" }, true, ["sign", "verify"]);
  }

  async function exportPublicKey(publicKey) {
    var spki = await subtle.exportKey("spki", publicKey);
    return bytesToBase64url(new Uint8Array(spki));
  }

  async function importPublicKey(base64url) {
    return subtle.importKey(
      "spki",
      base64urlToBytes(base64url),
      { name: "Ed25519" },
      true,
      ["verify"],
    );
  }

  /* Sign a commitment (the hex hash string). */
  async function signCommitment(privateKey, hash) {
    var sig = await subtle.sign("Ed25519", privateKey, te.encode(hash));
    return bytesToBase64url(new Uint8Array(sig));
  }

  async function verifyCommitment(publicKey, hash, signature) {
    return subtle.verify(
      "Ed25519",
      publicKey,
      base64urlToBytes(signature),
      te.encode(hash),
    );
  }

  /* Coarsen a coordinate so the anchor never carries precise location. */
  function coarseLocation(location, decimals) {
    if (
      !location ||
      typeof location.lat !== "number" ||
      typeof location.lon !== "number"
    ) {
      return null;
    }
    var factor = Math.pow(10, decimals === undefined ? 2 : decimals);
    return {
      lat: Math.round(location.lat * factor) / factor,
      lon: Math.round(location.lon * factor) / factor,
    };
  }

  function committedBody(prev, entry) {
    return {
      prev: prev || null,
      observed_at: entry.observed_at,
      location: entry.location || null,
      model_id: entry.model_id || null,
      payload: entry.payload,
    };
  }

  /* Seal one observation onto the chain. Returns the stored entry. */
  async function sealObservation(opts) {
    opts = opts || {};
    var entry = {
      observed_at: opts.observedAt || new Date().toISOString(),
      location: opts.location || null,
      model_id: opts.modelId || null,
      payload: opts.payload,
    };
    var prev = opts.prev || null;
    entry.prev = prev;
    entry.hash = await commitment(committedBody(prev, entry));
    entry.signature = await signCommitment(opts.privateKey, entry.hash);
    return entry;
  }

  /* Verify a whole chain: every hash recomputes, every link holds, and every
   * signature checks out under the device key. */
  async function verifyChain(entries, publicKey) {
    entries = entries || [];
    for (var i = 0; i < entries.length; i++) {
      var entry = entries[i];
      var expected = await commitment(committedBody(entry.prev, entry));
      if (expected !== entry.hash) {
        return { ok: false, brokenAt: i, reason: "hash" };
      }
      if (i > 0 && entry.prev !== entries[i - 1].hash) {
        return { ok: false, brokenAt: i, reason: "link" };
      }
      if (publicKey) {
        var valid = await verifyCommitment(
          publicKey,
          entry.hash,
          entry.signature,
        );
        if (!valid) {
          return { ok: false, brokenAt: i, reason: "signature" };
        }
      }
    }
    return { ok: true, brokenAt: null };
  }

  return {
    base64urlToBytes: base64urlToBytes,
    bytesToBase64url: bytesToBase64url,
    bytesToHex: bytesToHex,
    canonical: canonical,
    coarseLocation: coarseLocation,
    commitment: commitment,
    exportPublicKey: exportPublicKey,
    generateKeyPair: generateKeyPair,
    importPublicKey: importPublicKey,
    sealObservation: sealObservation,
    sha256Hex: sha256Hex,
    signCommitment: signCommitment,
    verifyChain: verifyChain,
    verifyCommitment: verifyCommitment,
  };
});

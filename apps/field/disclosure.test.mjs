import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);
const trust = require("./trust.js");
const disclosure = require("./disclosure.js");

async function sealedPair(
  payload = { kind: "bird", species: "European robin" },
) {
  const pair = await trust.generateKeyPair();
  const entry = await trust.sealObservation({
    privateKey: pair.privateKey,
    payload,
    modelId: "gemma3",
  });
  const publicKey = await trust.exportPublicKey(pair.publicKey);
  return { entry, publicKey, pair };
}

function receiptFor(entry, extra = {}) {
  return {
    receipt_id: "rec_test1",
    commitment: entry.hash,
    status: "confirmed",
    mode: "B",
    shielded: true,
    txid: "f".repeat(64),
    height: 101,
    anchored_at: "2026-10-28T00:00:00Z",
    ...extra,
  };
}

function verificationFor(entry, extra = {}) {
  return {
    receipt_id: "rec_test1",
    commitment: entry.hash,
    txid: "f".repeat(64),
    height: 101,
    confirmations: 5,
    network: "regtest",
    transaction_verified: true,
    commitment_verified: true,
    binding: "encrypted_memo",
    verification_source: "service_wallet",
    reason: "commitment_in_encrypted_memo",
    ...extra,
  };
}

test("buildDisclosure assembles a bundle that verifies locally", async () => {
  const { entry, publicKey } = await sealedPair();
  const response = {
    receipt: receiptFor(entry),
    verification: verificationFor(entry),
  };
  const bundle = await disclosure.buildDisclosure(entry, publicKey, response);
  assert.equal(bundle.schema, "vickrey.disclosure/1");
  assert.equal(bundle.public_key, publicKey);
  assert.deepEqual(bundle.entry, entry);
  const result = await disclosure.verifyDisclosure(bundle);
  assert.equal(result.entryVerified, true);
  assert.equal(result.signatureVerified, true);
  assert.equal(result.commitment, entry.hash);
  assert.equal(result.receipt.receipt_id, "rec_test1");
});

test("a tampered entry or signature fails verification", async () => {
  const { entry, publicKey } = await sealedPair();
  const bundle = await disclosure.buildDisclosure(entry, publicKey, {
    receipt: receiptFor(entry),
    verification: verificationFor(entry),
  });
  const tampered = JSON.parse(JSON.stringify(bundle));
  tampered.entry.payload.species = "Misidentified magpie";
  await assert.rejects(
    () => disclosure.verifyDisclosure(tampered),
    /does not verify/,
  );
  const forged = JSON.parse(JSON.stringify(bundle));
  forged.entry.signature = trust.bytesToBase64url(new Uint8Array(64));
  await assert.rejects(
    () => disclosure.verifyDisclosure(forged),
    /does not verify/,
  );
  const wrongKey = JSON.parse(JSON.stringify(bundle));
  const other = await trust.generateKeyPair();
  wrongKey.public_key = await trust.exportPublicKey(other.publicKey);
  await assert.rejects(
    () => disclosure.verifyDisclosure(wrongKey),
    /does not verify/,
  );
});

test("a changed or malformed receipt is rejected", async () => {
  const { entry, publicKey } = await sealedPair();
  const bundle = await disclosure.buildDisclosure(entry, publicKey, {
    receipt: receiptFor(entry),
    verification: verificationFor(entry),
  });
  const wrong = JSON.parse(JSON.stringify(bundle));
  wrong.receipt.commitment = "0".repeat(64);
  await assert.rejects(
    () => disclosure.verifyDisclosure(wrong),
    /does not match the entry hash/,
  );
  const missing = JSON.parse(JSON.stringify(bundle));
  delete missing.receipt.receipt_id;
  await assert.rejects(
    () => disclosure.verifyDisclosure(missing),
    /receipt_id/,
  );
});

test("schema, shape and missing fields are rejected", async () => {
  await assert.rejects(
    () => disclosure.verifyDisclosure(null),
    /not an object/,
  );
  await assert.rejects(
    () => disclosure.verifyDisclosure({ schema: "nope" }),
    /schema/,
  );
  const { entry, publicKey } = await sealedPair();
  const bundle = await disclosure.buildDisclosure(entry, publicKey, {
    receipt: receiptFor(entry),
    verification: verificationFor(entry),
  });
  for (const field of ["hash", "signature", "observed_at", "payload"]) {
    const bad = JSON.parse(JSON.stringify(bundle));
    delete bad.entry[field];
    await assert.rejects(
      () => disclosure.verifyDisclosure(bad),
      new RegExp(field.replace("_", "[_ ]?"), "i"),
    );
  }
});

test("the embedded verification is carried, never trusted as fresh proof", async () => {
  const { entry, publicKey } = await sealedPair();
  // A bundle whose embedded verification flatly contradicts itself still
  // verifies locally: that block is a historical service assertion and the
  // result deliberately does not echo it as a fact.
  const bundle = await disclosure.buildDisclosure(entry, publicKey, {
    receipt: receiptFor(entry),
    verification: verificationFor(entry, {
      transaction_verified: false,
      commitment_verified: false,
    }),
  });
  const result = await disclosure.verifyDisclosure(bundle);
  assert.equal(result.entryVerified, true);
  assert.equal("transaction_verified" in result, false);
  assert.equal("commitment_verified" in result, false);
});

test("buildDisclosure refuses a response that does not fit the entry", async () => {
  const { entry, publicKey } = await sealedPair();
  await assert.rejects(
    () =>
      disclosure.buildDisclosure(entry, publicKey, {
        receipt: receiptFor(entry, { commitment: "9".repeat(64) }),
        verification: verificationFor(entry),
      }),
    /does not match the entry hash/,
  );
});

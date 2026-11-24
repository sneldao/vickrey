import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import crypto from "node:crypto";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";

import {
  IDEMPOTENCY_RE,
  LOCAL_RECORD_SCHEMA,
  PUBLIC_RECEIPT_SCHEMA,
  applyDemoPublicNoticePolicy,
  apiUrl,
  buildSubmissionRequest,
  challengeUrl,
  createLocalSealedRecord,
  demoHealthFailures,
  fieldTaskAllowed,
  healthUrl,
  isoUtcMicros,
  newIdempotencyKey,
  publicReceiptProblems,
  receiptUrl,
  requestJson,
  resolveApiBase,
  signCanonicalVerdict,
  verifyVerdictSignature,
} from "./receipts-core.mjs";

const require = createRequire(import.meta.url);
const trust = require("../field/trust.js");
const serviceDirectory = new URL("../../services/receipts/", import.meta.url);
const readme = readFileSync(new URL("README.md", serviceDirectory), "utf8");
const demoPrivateKeyBase64 = readme.match(
  /PKCS#8 Base64 \(demo only\):\s*\n\s*([A-Za-z0-9+/=]+)/,
)?.[1];
assert.ok(
  demoPrivateKeyBase64,
  "service README must document the demo private key",
);
const demoPrivateKeyPem = [
  "-----BEGIN " + "PRIVATE KEY-----",
  demoPrivateKeyBase64,
  "-----END " + "PRIVATE KEY-----",
].join("\n");

const fixedVerdict = {
  verdict_id: "00000000-0000-4000-8000-000000000001",
  challenge_id: "11111111-1111-4111-8111-111111111111",
  submission_id: "22222222-2222-4222-8222-222222222222",
  submission_version: 1,
  commitment: "A".repeat(64),
  criteria_hash: "B".repeat(64),
  verdict: "accepted",
  policy_id: "public-notice-v1",
  policy_version: 1,
  reason: "Policy applied: café — accepted.",
  issued_at: "2026-11-24T13:00:00.123456+01:00",
  signature: "0".repeat(128),
};

function pythonVerdictFixture(payload = fixedVerdict) {
  const script = String.raw`
import json
import sys
from cryptography.hazmat.primitives import serialization
from app.models import VerdictIn
from app.signing import canonical_verdict_payload, verdict_signing_bytes

value = json.load(sys.stdin)
model = VerdictIn(**value["payload"])
private_key = serialization.load_pem_private_key(value["private_key"].encode("ascii"), password=None)
public_key = private_key.public_key().public_bytes(
    serialization.Encoding.Raw, serialization.PublicFormat.Raw
).hex()
message = verdict_signing_bytes(model.model_dump())
print(json.dumps({
    "payload": canonical_verdict_payload(model.model_dump()),
    "bytes_hex": message.hex(),
    "public_key_hex": public_key,
    "signature": private_key.sign(message).hex()
}))
`;
  return JSON.parse(
    execFileSync("python3", ["-c", script], {
      cwd: serviceDirectory,
      input: JSON.stringify({
        payload,
        private_key: demoPrivateKeyPem,
      }),
      encoding: "utf8",
    }),
  );
}

test("canonical verdict bytes and Ed25519 signature match the Python service fixture", async () => {
  const fixture = pythonVerdictFixture();
  const signed = await signCanonicalVerdict(fixedVerdict, {
    privateKey: demoPrivateKeyBase64,
    publicKeyHex: fixture.public_key_hex,
  });
  assert.deepEqual(signed.payload, fixture.payload);
  assert.equal(signed.signingBytesHex, fixture.bytes_hex);
  assert.equal(signed.body.signature, fixture.signature);
  assert.equal(Object.hasOwn(signed.body, "schema"), false);
  assert.equal(pythonVerdictFixture(signed.body).signature, fixture.signature);
  assert.equal(signed.payload.issued_at, "2026-11-24T12:00:00.123456Z");
  assert.match(signed.body.signature, /^[0-9a-f]{128}$/);
  assert.equal(
    await verifyVerdictSignature(
      fixture.public_key_hex,
      signed.payload,
      signed.body.signature,
    ),
    true,
  );
  assert.equal(
    await verifyVerdictSignature(
      fixture.public_key_hex,
      { ...signed.payload, reason: "Tampered after signing." },
      signed.body.signature,
    ),
    false,
  );

  const prefix = Buffer.from("302a300506032b6570032100", "hex");
  const publicKey = crypto.createPublicKey({
    key: Buffer.concat([prefix, Buffer.from(fixture.public_key_hex, "hex")]),
    format: "der",
    type: "spki",
  });
  assert.equal(
    crypto.verify(
      null,
      Buffer.from(fixture.bytes_hex, "hex"),
      publicKey,
      Buffer.from(fixture.signature, "hex"),
    ),
    true,
  );
});

test("UTC formatting always retains six microsecond digits", () => {
  assert.equal(
    isoUtcMicros("2026-11-24T13:00:00.1+01:00"),
    "2026-11-24T12:00:00.100000Z",
  );
  assert.equal(
    isoUtcMicros("2026-11-24T12:00:00Z"),
    "2026-11-24T12:00:00.000000Z",
  );
  assert.equal(
    isoUtcMicros(new Date("2026-11-24T12:00:00.123Z")),
    "2026-11-24T12:00:00.123000Z",
  );
  assert.throws(() => isoUtcMicros("2026-11-24T12:00:00"), /timezone/);
});

test("API URLs default to same-origin /healthz and /v1", () => {
  const base = resolveApiBase({
    configuredBase: "",
    currentHref: "https://receipts.test/app/",
  });
  assert.equal(base, "");
  assert.equal(healthUrl(base), "/healthz");
  assert.equal(apiUrl(base, "/v1/challenges"), "/v1/challenges");
  const id = "11111111-1111-4111-8111-111111111111";
  assert.equal(receiptUrl(base, id), `/v1/receipts/${id}`);
  assert.equal(
    challengeUrl(base, id, "/submissions"),
    `/v1/challenges/${id}/submissions`,
  );
});

test("config and ?receipts= overrides construct local API URLs without duplicate slashes", () => {
  const currentHref = "https://receipts.test/app/";
  assert.equal(
    resolveApiBase({ configuredBase: "http://127.0.0.1:8099/", currentHref }),
    "http://127.0.0.1:8099",
  );
  assert.equal(
    resolveApiBase({ configuredBase: "/service", currentHref }),
    "https://receipts.test/service",
  );
  assert.equal(
    resolveApiBase({
      configuredBase: "https://configured.test",
      receiptsParam: "http://localhost:8099/",
      currentHref,
    }),
    "http://localhost:8099",
  );
  assert.equal(
    resolveApiBase({
      configuredBase: "https://configured.test",
      receiptsParam: "",
      currentHref,
    }),
    "",
  );
  assert.equal(
    healthUrl("http://localhost:8099"),
    "http://localhost:8099/healthz",
  );
});

test("unsafe API bases are rejected", () => {
  for (const configuredBase of [
    "file:///tmp/service",
    "https://user:pass@example.test",
    "https://example.test?token=secret",
    "https://example.test/#fragment",
  ]) {
    assert.throws(
      () =>
        resolveApiBase({
          configuredBase,
          currentHref: "https://receipts.test/",
        }),
      TypeError,
    );
  }
});

test("demo health gate fails closed and field work requires insufficient non-proof context", () => {
  const health = {
    status: "ok",
    mode: "demo",
    real_funds: false,
    settlement_network: "simulated_testnet",
  };
  assert.deepEqual(demoHealthFailures(health), []);
  assert.deepEqual(
    demoHealthFailures({ ...health, mode: "production", real_funds: true }),
    ["mode is not demo", "real_funds is not false"],
  );
  assert.deepEqual(
    demoHealthFailures({ ...health, settlement_network: "mainnet" }),
    ["settlement_network is not simulated_testnet"],
  );
  assert.equal(
    fieldTaskAllowed({ status: "insufficient", is_cryptographic_proof: false }),
    true,
  );
  for (const status of ["likely", "unlikely", "unavailable"]) {
    assert.equal(
      fieldTaskAllowed({ status, is_cryptographic_proof: false }),
      false,
    );
  }
  assert.equal(
    fieldTaskAllowed({ status: "insufficient", is_cryptographic_proof: true }),
    false,
  );
});

test("submission construction sends exactly commitment plus allowlisted public metadata", () => {
  const request = buildSubmissionRequest("C".repeat(64), {
    captured_at: "2026-11-24T12:00:00.123456Z",
    public_location: "North trail public kiosk",
    observation_status: "observed",
    public_summary: "must-not-leave-browser",
    latitude: 51.5,
    longitude: -0.1,
    raw_observation: { private: true },
    signature: "must-not-leave-browser",
    observer_public_key: "must-not-leave-browser",
  });
  assert.deepEqual(Object.keys(request).sort(), [
    "commitment",
    "public_metadata",
  ]);
  assert.deepEqual(Object.keys(request.public_metadata).sort(), [
    "captured_at",
    "observation_status",
    "public_location",
  ]);
  assert.equal(request.commitment, "c".repeat(64));
  const serialized = JSON.stringify(request);
  for (const forbidden of [
    "latitude",
    "longitude",
    "raw_observation",
    "public_summary",
    "signature",
    "observer_public_key",
    "must-not-leave-browser",
  ]) {
    assert.equal(serialized.includes(forbidden), false);
  }
});

test("the real trust.js seal retains signature/public key locally and verifies", async () => {
  const task = {
    id: "33333333-3333-4333-8333-333333333333",
    public_location: "North trail public kiosk",
    created_at: "2026-11-24T12:00:00.000000Z",
    expires_at: "2026-11-24T14:00:00.000000Z",
    reject_if: ["notice is absent", "notice is unreadable"],
  };
  const criteria = {
    must_observe: "Read the posted notice at the public kiosk.",
    public_location: task.public_location,
    radius_m: 25,
    required_details: ["notice title", "visible posting date"],
    reject_if: task.reject_if,
  };
  const record = await createLocalSealedRecord(trust, {
    challengeId: fixedVerdict.challenge_id,
    criteriaHash: "b".repeat(64),
    task,
    claim: "The public north-trail kiosk notice is present today.",
    category: "public_notice",
    criteria,
    outcome: "observed",
    observationNote: "The notice title and visible posting date were readable.",
    observedAt: "2026-11-24T12:05:00.123456Z",
  });
  assert.equal(record.schema, LOCAL_RECORD_SCHEMA);
  assert.match(record.commitment, /^[0-9a-f]{64}$/);
  assert.equal(typeof record.sealed_entry.signature, "string");
  assert.equal(typeof record.observer_public_key, "string");
  assert.equal(record.sealed_entry.location, null);
  assert.equal(
    record.sealed_entry.payload.public_location,
    task.public_location,
  );
  assert.equal(record.public_metadata.observation_status, "observed");
  assert.equal("public_summary" in record.public_metadata, false);
  assert.match(record.sealed_entry.payload.public_summary, /notice title/);
  assert.equal(JSON.stringify(record).includes("privateKey"), false);
  const publicKey = await trust.importPublicKey(record.observer_public_key);
  assert.deepEqual(await trust.verifyChain([record.sealed_entry], publicKey), {
    ok: true,
    brokenAt: null,
  });
  const submission = buildSubmissionRequest(
    record.commitment,
    record.public_metadata,
  );
  assert.equal(submission.public_metadata.captured_at, record.captured_at);
  assert.equal(
    submission.public_metadata.public_location,
    task.public_location,
  );
});

test("local public-notice policy accepts, rejects, and declines deterministically", async () => {
  const task = {
    id: "33333333-3333-4333-8333-333333333333",
    public_location: "North trail public kiosk",
    created_at: "2026-11-24T12:00:00.000000Z",
    expires_at: "2026-11-24T14:00:00.000000Z",
    reject_if: ["notice is absent"],
  };
  const criteria = {
    must_observe: "Read the posted notice.",
    public_location: task.public_location,
    radius_m: 25,
    required_details: ["notice title"],
    reject_if: task.reject_if,
  };
  const record = await createLocalSealedRecord(trust, {
    challengeId: fixedVerdict.challenge_id,
    criteriaHash: "b".repeat(64),
    task,
    claim: "The public notice is present.",
    category: "public_notice",
    criteria,
    outcome: "observed",
    observationNote: "The notice title was readable.",
    observedAt: "2026-11-24T12:05:00.000000Z",
  });
  const challenge = { id: fixedVerdict.challenge_id };
  const apply = (outcome, observationNote) =>
    applyDemoPublicNoticePolicy({
      record,
      challenge,
      task,
      outcome,
      observationNote,
    });
  assert.equal(
    apply("observed", "The notice title was readable.").verdict,
    "accepted",
  );
  assert.equal(
    apply("not_observed", "The notice title was readable.").verdict,
    "rejected",
  );
  assert.equal(
    apply("observed", "The notice is absent today.").verdict,
    "rejected",
  );
  assert.equal(
    apply("cannot_determine", "The notice title was unreadable.").verdict,
    "cannot_determine",
  );
  record.seal_verification = { ok: false, brokenAt: 0, reason: "hash" };
  assert.equal(
    apply("observed", "The notice title was readable.").verdict,
    "cannot_determine",
  );
});

test("public receipt redaction assumptions accept the service shape and reject leaks", () => {
  const receipt = {
    schema: PUBLIC_RECEIPT_SCHEMA,
    status: "complete",
    challenge: { id: fixedVerdict.challenge_id },
    remote_evidence: { is_cryptographic_proof: false },
    field_evidence: {
      commitment: "a".repeat(64),
      raw_observation_received: false,
      commitment_verified_against_raw_record: false,
    },
    settlement: { real_funds: false },
    limitations: ["Settlement is a deterministic simulator: no real funds."],
  };
  assert.deepEqual(publicReceiptProblems(receipt), []);
  const leaked = structuredClone(receipt);
  leaked.public_metadata = { public_summary: "PRIVATE-SUMMARY-MARKER" };
  assert.ok(
    publicReceiptProblems(leaked).some((problem) =>
      problem.includes("public_metadata"),
    ),
  );
  const overstated = structuredClone(receipt);
  overstated.field_evidence.commitment_verified_against_raw_record = true;
  assert.ok(publicReceiptProblems(overstated).length > 0);
});

test("idempotency keys are unique, bounded, and service-safe", () => {
  const keys = Array.from({ length: 500 }, () => newIdempotencyKey("submit"));
  assert.equal(new Set(keys).size, keys.length);
  for (const key of keys) {
    assert.match(key, IDEMPOTENCY_RE);
    assert.ok(key.length >= 8 && key.length <= 128);
    assert.match(key, /^rr-demo-submit-[0-9a-f-]{36}$/);
  }
});

test("API errors surface status/detail without exposing bearer credentials", async () => {
  const token = "demo-verifier-token-change-me";
  let sent;
  await assert.rejects(
    requestJson("https://receipts.test/v1/challenges", {
      method: "POST",
      body: { claim: "Public notice" },
      token,
      idempotencyKey: "rr-demo-test-0001",
      expectedStatus: 201,
      fetchImpl: async (url, options) => {
        sent = { url, options };
        return new Response(
          JSON.stringify({
            detail: "invalid bearer token",
            code: "unauthorized",
          }),
          {
            status: 401,
            headers: { "Content-Type": "application/json" },
          },
        );
      },
    }),
    (error) => {
      assert.match(error.message, /HTTP 401/);
      assert.match(error.message, /invalid bearer token/);
      assert.equal(error.message.includes(token), false);
      assert.equal(error.code, "unauthorized");
      return true;
    },
  );
  assert.equal(sent.options.headers.Authorization, `Bearer ${token}`);
  assert.equal(sent.options.headers["Idempotency-Key"], "rr-demo-test-0001");
});

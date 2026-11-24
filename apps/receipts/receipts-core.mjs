export const VERDICT_SCHEMA = "reality-receipts.verifier-verdict.v1";
export const LOCAL_RECORD_SCHEMA =
  "vickrey.reality-receipts.local-sealed-record.v1";
export const PUBLIC_RECEIPT_SCHEMA = "reality-receipts.public-receipt.v1";
export const DEMO_POLICY_ID = "public-notice-v1";
export const DEMO_POLICY_VERSION = 1;
export const IDEMPOTENCY_RE = /^[A-Za-z0-9._:-]{8,128}$/;
export const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const HEX64_RE = /^[0-9a-f]{64}$/i;
const SIG128_RE = /^[0-9a-f]{128}$/i;
const POLICY_ID_RE = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$/;
const VERDICTS = new Set([
  "accepted",
  "rejected",
  "needs_witness",
  "cannot_determine",
]);
const ED25519_SPKI_PREFIX = Uint8Array.from([
  0x30, 0x2a, 0x30, 0x05, 0x06, 0x03, 0x2b, 0x65, 0x70, 0x03, 0x21, 0x00,
]);

export class ApiError extends Error {
  constructor(
    message,
    { url = "", method = "GET", status = 0, code = "" } = {},
  ) {
    super(message);
    this.name = "ApiError";
    this.url = url;
    this.method = method;
    this.status = status;
    this.code = code;
  }
}

function requireString(value, label, { min = 1, max = 4096 } = {}) {
  if (typeof value !== "string") {
    throw new TypeError(`${label} must be a string`);
  }
  const clean = value.trim();
  if (clean.length < min || clean.length > max) {
    throw new RangeError(`${label} must contain ${min}-${max} characters`);
  }
  return clean;
}

function requireInteger(value, label, { min = 1, max = 1_000_000 } = {}) {
  if (!Number.isInteger(value) || value < min || value > max) {
    throw new RangeError(`${label} must be an integer from ${min} to ${max}`);
  }
  return value;
}

export function normalizeUuid(value, label = "id") {
  const clean = requireString(value, label, { max: 64 }).toLowerCase();
  if (!UUID_RE.test(clean)) {
    throw new TypeError(`${label} must be a UUID`);
  }
  return clean;
}

export function newUuid(random = () => globalThis.crypto.randomUUID()) {
  return normalizeUuid(random());
}

export function newIdempotencyKey(
  operation,
  random = () => globalThis.crypto.randomUUID(),
) {
  const slug = requireString(operation, "operation", { max: 32 })
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, "-")
    .replace(/^-+|-+$/g, "");
  if (!slug) throw new TypeError("operation must contain letters or digits");
  const key = `rr-demo-${slug}-${normalizeUuid(random())}`;
  if (!IDEMPOTENCY_RE.test(key)) {
    throw new RangeError(
      "generated idempotency key is outside the service limit",
    );
  }
  return key;
}

export function resolveApiBase({
  configuredBase = "",
  receiptsParam = null,
  currentHref = "https://example.test/",
} = {}) {
  const raw = receiptsParam === null ? configuredBase : receiptsParam;
  if (typeof raw !== "string") {
    throw new TypeError("receipts API base must be a string");
  }
  const value = raw.trim();
  if (!value) return "";
  const url = new URL(value, currentHref);
  if (url.protocol !== "https:" && url.protocol !== "http:") {
    throw new TypeError("receipts API base must use http or https");
  }
  if (url.username || url.password) {
    throw new TypeError("receipts API base must not contain credentials");
  }
  if (url.search || url.hash) {
    throw new TypeError(
      "receipts API base must not contain a query or fragment",
    );
  }
  const path = url.pathname.replace(/\/+$/, "");
  return `${url.origin}${path}`;
}

export function apiUrl(base, path) {
  if (typeof path !== "string" || !path.startsWith("/")) {
    throw new TypeError("API path must start with /");
  }
  return `${String(base).replace(/\/+$/, "")}${path}`;
}

export function healthUrl(base) {
  return apiUrl(base, "/healthz");
}

export function challengeUrl(base, challengeId, suffix = "") {
  const id = normalizeUuid(challengeId, "challenge id");
  if (suffix && !suffix.startsWith("/")) {
    throw new TypeError("challenge suffix must start with /");
  }
  return apiUrl(base, `/v1/challenges/${id}${suffix}`);
}

export function receiptUrl(base, challengeId) {
  return apiUrl(
    base,
    `/v1/receipts/${normalizeUuid(challengeId, "challenge id")}`,
  );
}

export function submissionUrl(base, submissionId, suffix = "") {
  const id = normalizeUuid(submissionId, "submission id");
  if (suffix && !suffix.startsWith("/")) {
    throw new TypeError("submission suffix must start with /");
  }
  return apiUrl(base, `/v1/submissions/${id}${suffix}`);
}

export function verdictUrl(base, verdictId) {
  return apiUrl(
    base,
    `/v1/verdicts/${normalizeUuid(verdictId, "verdict id")}/settlement`,
  );
}

/* Match Python strftime("%Y-%m-%dT%H:%M:%S.%fZ") after UTC conversion. */
export function isoUtcMicros(value = new Date()) {
  let date;
  let remainder = "000";
  if (value instanceof Date) {
    date = value;
  } else if (typeof value === "string") {
    const match = value.match(
      /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,6}))?(Z|[+-]\d{2}:\d{2})$/,
    );
    if (!match) {
      throw new TypeError("timestamp must be ISO 8601 with a timezone");
    }
    const fraction = (match[2] || "").padEnd(6, "0");
    remainder = fraction.slice(3);
    date = new Date(`${match[1]}.${fraction.slice(0, 3)}${match[3]}`);
  } else {
    date = new Date(value);
  }
  if (!Number.isFinite(date.getTime())) {
    throw new RangeError("timestamp is invalid");
  }
  const base = date.toISOString().slice(0, 19);
  const millis = String(date.getUTCMilliseconds()).padStart(3, "0");
  return `${base}.${millis}${remainder}Z`;
}

function canonicalInner(value, ancestors = new Set()) {
  if (
    value === null ||
    typeof value === "string" ||
    typeof value === "boolean"
  ) {
    return JSON.stringify(value);
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) {
      throw new TypeError("canonical JSON cannot contain non-finite numbers");
    }
    return JSON.stringify(value);
  }
  if (typeof value !== "object") {
    throw new TypeError("canonical JSON contains an unsupported value");
  }
  if (ancestors.has(value)) {
    throw new TypeError("canonical JSON cannot contain a cycle");
  }
  ancestors.add(value);
  let result;
  if (Array.isArray(value)) {
    result = `[${value.map((item) => canonicalInner(item, ancestors)).join(",")}]`;
  } else {
    result = `{${Object.keys(value)
      .sort()
      .map(
        (key) =>
          `${JSON.stringify(key)}:${canonicalInner(value[key], ancestors)}`,
      )
      .join(",")}}`;
  }
  ancestors.delete(value);
  return result;
}

export function canonicalJson(value) {
  return canonicalInner(value);
}

export function canonicalVerdictPayload(input) {
  if (!input || typeof input !== "object") {
    throw new TypeError("verdict payload is required");
  }
  const commitment = requireString(input.commitment, "commitment", {
    max: 64,
  }).toLowerCase();
  const criteriaHash = requireString(input.criteria_hash, "criteria hash", {
    max: 64,
  }).toLowerCase();
  if (!HEX64_RE.test(commitment) || !HEX64_RE.test(criteriaHash)) {
    throw new TypeError(
      "commitment and criteria hash must be 64 hex characters",
    );
  }
  if (!VERDICTS.has(input.verdict)) {
    throw new TypeError("unsupported verdict");
  }
  const policyId = requireString(input.policy_id, "policy id", { max: 64 });
  if (!POLICY_ID_RE.test(policyId)) {
    throw new TypeError("policy id contains unsupported characters");
  }
  return {
    schema: VERDICT_SCHEMA,
    verdict_id: normalizeUuid(input.verdict_id, "verdict id"),
    challenge_id: normalizeUuid(input.challenge_id, "challenge id"),
    submission_id: normalizeUuid(input.submission_id, "submission id"),
    submission_version: requireInteger(
      input.submission_version,
      "submission version",
    ),
    commitment,
    criteria_hash: criteriaHash,
    verdict: input.verdict,
    policy_id: policyId,
    policy_version: requireInteger(input.policy_version, "policy version"),
    reason: requireString(input.reason, "reason", { max: 500 }),
    issued_at: isoUtcMicros(input.issued_at),
  };
}

export function verdictSigningBytes(input) {
  return new TextEncoder().encode(
    canonicalJson(canonicalVerdictPayload(input)),
  );
}

export function bytesToHex(bytes) {
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join(
    "",
  );
}

export function hexToBytes(hex) {
  if (
    typeof hex !== "string" ||
    hex.length % 2 !== 0 ||
    !/^[0-9a-f]*$/i.test(hex)
  ) {
    throw new TypeError("hex value is invalid");
  }
  const bytes = new Uint8Array(hex.length / 2);
  for (let index = 0; index < bytes.length; index += 1) {
    bytes[index] = Number.parseInt(hex.slice(index * 2, index * 2 + 2), 16);
  }
  return bytes;
}

function privateKeyToBytes(value) {
  const encoded = requireString(value, "private key", { max: 4096 }).replace(
    /\s+/g,
    "",
  );
  if (!/^[A-Za-z0-9+/]+={0,2}$/.test(encoded)) {
    throw new TypeError("demo verifier key must be PKCS#8 Base64");
  }
  const binary = atob(encoded);
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
}

export async function importDemoVerifierPrivateKey(
  value,
  cryptoImpl = globalThis.crypto,
) {
  if (!cryptoImpl?.subtle) {
    throw new Error("WebCrypto is unavailable; use HTTPS or localhost");
  }
  return cryptoImpl.subtle.importKey(
    "pkcs8",
    privateKeyToBytes(value),
    { name: "Ed25519" },
    false,
    ["sign"],
  );
}

export async function importEd25519PublicKeyHex(
  hex,
  cryptoImpl = globalThis.crypto,
) {
  const clean = requireString(hex, "public key", { min: 64, max: 64 });
  if (!HEX64_RE.test(clean)) {
    throw new TypeError(
      "Ed25519 public key must be 64 lowercase hex characters",
    );
  }
  if (!cryptoImpl?.subtle) throw new Error("WebCrypto is unavailable");
  const raw = hexToBytes(clean);
  const spki = new Uint8Array(ED25519_SPKI_PREFIX.length + raw.length);
  spki.set(ED25519_SPKI_PREFIX);
  spki.set(raw, ED25519_SPKI_PREFIX.length);
  return cryptoImpl.subtle.importKey("spki", spki, { name: "Ed25519" }, false, [
    "verify",
  ]);
}

export async function verifyVerdictSignature(
  publicKeyHex,
  payload,
  signatureHex,
  cryptoImpl = globalThis.crypto,
) {
  if (!SIG128_RE.test(signatureHex)) return false;
  try {
    const key = await importEd25519PublicKeyHex(publicKeyHex, cryptoImpl);
    return await cryptoImpl.subtle.verify(
      "Ed25519",
      key,
      hexToBytes(signatureHex),
      verdictSigningBytes(payload),
    );
  } catch {
    return false;
  }
}

export async function signCanonicalVerdict(
  input,
  { privateKey, publicKeyHex, cryptoImpl = globalThis.crypto } = {},
) {
  const payload = canonicalVerdictPayload(input);
  const bytes = new TextEncoder().encode(canonicalJson(payload));
  const importedPrivateKey = await importDemoVerifierPrivateKey(
    privateKey,
    cryptoImpl,
  );
  const signature = bytesToHex(
    new Uint8Array(
      await cryptoImpl.subtle.sign("Ed25519", importedPrivateKey, bytes),
    ),
  );
  if (
    !publicKeyHex ||
    !(await verifyVerdictSignature(
      publicKeyHex,
      payload,
      signature,
      cryptoImpl,
    ))
  ) {
    throw new Error("the locally signed demo verdict did not verify");
  }
  return {
    payload,
    body: { ...payload, signature },
    signingBytesHex: bytesToHex(bytes),
  };
}

export async function assertWebCryptoEd25519(cryptoImpl = globalThis.crypto) {
  if (!cryptoImpl?.subtle || !cryptoImpl.randomUUID) {
    throw new Error(
      "This browser lacks WebCrypto Ed25519 or secure random UUIDs",
    );
  }
  let pair;
  try {
    pair = await cryptoImpl.subtle.generateKey({ name: "Ed25519" }, true, [
      "sign",
      "verify",
    ]);
    const bytes = new TextEncoder().encode("reality-receipts-capability-check");
    const signature = await cryptoImpl.subtle.sign(
      "Ed25519",
      pair.privateKey,
      bytes,
    );
    if (
      !(await cryptoImpl.subtle.verify(
        "Ed25519",
        pair.publicKey,
        signature,
        bytes,
      ))
    ) {
      throw new Error("Ed25519 verification failed");
    }
  } catch (error) {
    throw new Error(
      `WebCrypto Ed25519 is unavailable in this browser (${error.message}). Use a current browser over HTTPS or localhost.`,
    );
  }
}

export function demoHealthFailures(health) {
  const failures = [];
  if (!health || typeof health !== "object")
    return ["health response is missing"];
  if (health.status !== "ok") failures.push("status is not ok");
  if (health.mode !== "demo") failures.push("mode is not demo");
  if (health.real_funds !== false) failures.push("real_funds is not false");
  if (health.settlement_network !== "simulated_testnet") {
    failures.push("settlement_network is not simulated_testnet");
  }
  return failures;
}

export function fieldTaskAllowed(remoteEvidence) {
  return (
    remoteEvidence?.status === "insufficient" &&
    remoteEvidence?.is_cryptographic_proof === false
  );
}

export function buildPublicMetadata({
  capturedAt,
  publicLocation,
  publicSummary,
}) {
  return {
    captured_at: isoUtcMicros(capturedAt),
    public_location: requireString(publicLocation, "public location", {
      max: 120,
    }),
    public_summary: requireString(publicSummary, "public summary", {
      max: 240,
    }),
  };
}

export function buildSubmissionRequest(commitment, metadata) {
  const cleanCommitment = requireString(commitment, "commitment", {
    max: 64,
  }).toLowerCase();
  if (!HEX64_RE.test(cleanCommitment)) {
    throw new TypeError("commitment must be 64 lowercase hex characters");
  }
  if (!metadata || typeof metadata !== "object") {
    throw new TypeError("public metadata is required");
  }
  return {
    commitment: cleanCommitment,
    public_metadata: buildPublicMetadata({
      capturedAt: metadata.captured_at,
      publicLocation: metadata.public_location,
      publicSummary: metadata.public_summary,
    }),
  };
}

export async function createLocalSealedRecord(
  trust,
  {
    challengeId,
    criteriaHash,
    task,
    claim,
    category,
    criteria,
    outcome,
    observationNote,
    observedAt = new Date(),
  },
) {
  if (
    !trust?.generateKeyPair ||
    !trust?.sealObservation ||
    !trust?.verifyChain
  ) {
    throw new Error(
      "../field/trust.js did not load; no observation was sealed",
    );
  }
  const challenge_id = normalizeUuid(challengeId, "challenge id");
  const task_id = normalizeUuid(task.id, "task id");
  const captured_at = isoUtcMicros(observedAt);
  const public_metadata = buildPublicMetadata({
    capturedAt: captured_at,
    publicLocation: task.public_location,
    publicSummary: observationNote,
  });
  if (public_metadata.public_location !== criteria.public_location) {
    throw new Error("task and criteria public locations do not match");
  }
  const keyPair = await trust.generateKeyPair();
  const payload = {
    schema: "reality-receipts.public-observation.v1",
    challenge_id,
    task_id,
    criteria_hash: criteriaHash.toLowerCase(),
    claim,
    category,
    public_location: criteria.public_location,
    criteria: {
      must_observe: criteria.must_observe,
      public_location: criteria.public_location,
      radius_m: criteria.radius_m,
      required_details: [...criteria.required_details],
      reject_if: [...criteria.reject_if],
    },
    outcome,
    public_summary: public_metadata.public_summary,
  };
  const sealedEntry = await trust.sealObservation({
    privateKey: keyPair.privateKey,
    observedAt: captured_at,
    location: null,
    modelId: "human-public-notice-demo-v1",
    payload,
  });
  const observerPublicKey = await trust.exportPublicKey(keyPair.publicKey);
  const sealVerification = await trust.verifyChain(
    [sealedEntry],
    keyPair.publicKey,
  );
  if (!sealVerification.ok) {
    throw new Error("the local Vickrey seal failed verification");
  }
  return {
    schema: LOCAL_RECORD_SCHEMA,
    challenge_id,
    task_id,
    submission_id: null,
    captured_at,
    criteria_hash: criteriaHash.toLowerCase(),
    observer_public_key: observerPublicKey,
    observer_public_key_encoding: "base64url-spki",
    commitment: sealedEntry.hash,
    sealed_entry: sealedEntry,
    public_metadata,
    seal_verification: sealVerification,
    service_boundary: {
      sent_fields: ["commitment", "public_metadata"],
      raw_observation_received: false,
      precise_location_received: false,
      observer_private_key_retained: false,
    },
  };
}

function truncate(text, max = 500) {
  const characters = Array.from(text);
  return characters.length <= max
    ? text
    : `${characters.slice(0, max - 1).join("")}…`;
}

export function applyDemoPublicNoticePolicy({
  record,
  challenge,
  task,
  outcome,
  observationNote,
}) {
  const base = {
    policy_id: DEMO_POLICY_ID,
    policy_version: DEMO_POLICY_VERSION,
  };
  if (
    !record?.seal_verification?.ok ||
    record.commitment !== record.sealed_entry?.hash ||
    record.criteria_hash !== record.sealed_entry?.payload?.criteria_hash
  ) {
    return {
      ...base,
      verdict: "cannot_determine",
      reason:
        "Local demo policy cannot determine the claim because the sealed record did not verify.",
    };
  }
  if (
    record.challenge_id !== challenge.id ||
    record.task_id !== task.id ||
    record.public_metadata.public_location !== task.public_location
  ) {
    return {
      ...base,
      verdict: "cannot_determine",
      reason:
        "Local demo policy cannot determine the claim because the sealed record is not bound to this public task.",
    };
  }
  const captured = Date.parse(record.captured_at);
  if (
    !Number.isFinite(captured) ||
    captured < Date.parse(task.created_at) ||
    captured >= Date.parse(task.expires_at)
  ) {
    return {
      ...base,
      verdict: "cannot_determine",
      reason:
        "Local demo policy cannot determine the claim because the capture is outside the task window.",
    };
  }
  const note = observationNote.trim().toLowerCase();
  const rejectMatches = (task.reject_if || []).filter(
    (phrase) => phrase.trim() && note.includes(phrase.trim().toLowerCase()),
  );
  if (outcome === "not_observed" || rejectMatches.length > 0) {
    const detail =
      outcome === "not_observed"
        ? "the observer marked the notice not observed"
        : `the note matched reject-if text: ${rejectMatches.join("; ")}`;
    return {
      ...base,
      verdict: "rejected",
      reason: truncate(
        `Local demo policy public-notice-v1 rejected the claim because ${detail}.`,
      ),
    };
  }
  if (outcome === "cannot_determine" || note.length < 8) {
    return {
      ...base,
      verdict: "cannot_determine",
      reason:
        "Local demo policy cannot determine the claim because the observation is inconclusive.",
    };
  }
  return {
    ...base,
    verdict: "accepted",
    reason:
      "Local demo policy public-notice-v1 accepted the claim: the seal verified, the public task and capture window matched, the observer marked it observed, and no reject-if text matched. The service did not verify the raw record.",
  };
}

export function publicReceiptProblems(receipt) {
  const problems = [];
  if (!receipt || typeof receipt !== "object") return ["receipt is missing"];
  if (receipt.schema !== PUBLIC_RECEIPT_SCHEMA) {
    problems.push("unexpected receipt schema");
  }
  if (
    !["complete", "complete_no_payout", "awaiting_settlement"].includes(
      receipt.status,
    )
  ) {
    problems.push("unexpected receipt status");
  }
  if (!UUID_RE.test(receipt.challenge?.id || "")) {
    problems.push("receipt has no valid challenge id");
  }
  if (!HEX64_RE.test(receipt.field_evidence?.commitment || "")) {
    problems.push("receipt has no valid commitment");
  }
  if (receipt.field_evidence?.raw_observation_received !== false) {
    problems.push("receipt does not affirm raw-observation redaction");
  }
  if (
    receipt.field_evidence?.commitment_verified_against_raw_record !== false
  ) {
    problems.push("receipt overstates raw-record verification");
  }
  if (receipt.remote_evidence?.is_cryptographic_proof !== false) {
    problems.push("receipt presents remote context as proof");
  }
  if (receipt.settlement?.real_funds !== false) {
    problems.push("receipt does not affirm simulated settlement");
  }
  if (
    !Array.isArray(receipt.limitations) ||
    !receipt.limitations.some((item) =>
      String(item).toLowerCase().includes("no real funds"),
    )
  ) {
    problems.push("receipt omits the no-real-funds limitation");
  }
  const forbiddenKeys = new Set([
    "public_metadata",
    "public_summary",
    "raw_observation",
    "raw_record",
    "sealed_entry",
    "observer_public_key",
    "observer_private_key",
    "private_key",
    "precise_location",
    "latitude",
    "longitude",
    "payload",
    "location",
  ]);
  const walk = (value, path = "receipt") => {
    if (!value || typeof value !== "object") return;
    for (const [key, child] of Object.entries(value)) {
      if (forbiddenKeys.has(key)) {
        problems.push(`unexpected redacted field ${path}.${key}`);
      }
      walk(child, `${path}.${key}`);
    }
  };
  walk(receipt);
  return [...new Set(problems)];
}

export function buildReceiptShareUrl(currentHref, challengeId) {
  const url = new URL(currentHref);
  url.searchParams.set("challenge", normalizeUuid(challengeId, "challenge id"));
  url.searchParams.delete("challenge_id");
  return url.href;
}

function responseDetail(data) {
  if (typeof data?.detail === "string") return data.detail;
  if (data?.detail !== undefined) {
    try {
      return JSON.stringify(data.detail);
    } catch {
      return "request rejected";
    }
  }
  return "request rejected";
}

export async function requestJson(
  url,
  {
    method = "GET",
    body,
    token,
    idempotencyKey,
    expectedStatus = 200,
    fetchImpl = globalThis.fetch,
  } = {},
) {
  if (!fetchImpl)
    throw new ApiError("Fetch is unavailable in this browser", { url, method });
  const headers = { Accept: "application/json" };
  let payload;
  if (body !== undefined) {
    payload = typeof body === "string" ? body : JSON.stringify(body);
    headers["Content-Type"] = "application/json";
  }
  if (token) headers.Authorization = `Bearer ${token}`;
  if (idempotencyKey) {
    if (!IDEMPOTENCY_RE.test(idempotencyKey)) {
      throw new ApiError("Refusing to send an invalid idempotency key", {
        url,
        method,
      });
    }
    headers["Idempotency-Key"] = idempotencyKey;
  }
  let response;
  try {
    response = await fetchImpl(url, { method, headers, body: payload });
  } catch {
    throw new ApiError(
      `Network error while contacting ${url}. No success is claimed.`,
      { url, method },
    );
  }
  const text = await response.text();
  let data = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { detail: text.slice(0, 500) };
    }
  }
  if (response.status !== expectedStatus) {
    const code = typeof data?.code === "string" ? data.code : "request_failed";
    throw new ApiError(
      `${method} ${url} failed with HTTP ${response.status}: ${responseDetail(data)}`,
      { url, method, status: response.status, code },
    );
  }
  return {
    data,
    replayed: response.headers.get("Idempotency-Replayed") === "true",
  };
}

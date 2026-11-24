import {
  ApiError,
  applyDemoPublicNoticePolicy,
  apiUrl,
  assertWebCryptoEd25519,
  buildReceiptShareUrl,
  buildSubmissionRequest,
  challengeUrl,
  createLocalSealedRecord,
  demoHealthFailures,
  fieldTaskAllowed,
  healthUrl,
  isoUtcMicros,
  newIdempotencyKey,
  newUuid,
  normalizeUuid,
  publicReceiptProblems,
  receiptUrl,
  requestJson,
  resolveApiBase,
  signCanonicalVerdict,
  submissionUrl,
  verdictUrl,
} from "./receipts-core.mjs";

const byId = (id) => document.getElementById(id);
const dom = {
  form: byId("claim-form"),
  fields: byId("claim-fields"),
  claim: byId("claim"),
  category: byId("category"),
  bounty: byId("bounty"),
  mustObserve: byId("must-observe"),
  publicLocation: byId("public-location"),
  radius: byId("radius"),
  requiredDetails: byId("required-details"),
  rejectIf: byId("reject-if"),
  expiry: byId("expiry"),
  outcome: byId("observation-outcome"),
  observationNote: byId("observation-note"),
  status: byId("workflow-status"),
  error: byId("workflow-error"),
  workflow: byId("workflow"),
  endpoint: byId("endpoint-label"),
  run: byId("run-button"),
  retry: byId("retry-button"),
  reset: byId("reset-button"),
  download: byId("download-button"),
  ids: byId("workflow-ids"),
  lookupForm: byId("lookup-form"),
  lookupId: byId("lookup-id"),
  lookupButton: byId("lookup-button"),
  receiptSection: byId("receipt-section"),
  receiptTitle: byId("receipt-title"),
  receiptEmpty: byId("receipt-empty"),
  receipt: byId("receipt-content"),
  receiptActions: byId("receipt-actions"),
  receiptShare: byId("receipt-share"),
  copyLink: byId("copy-link-button"),
  print: byId("print-button"),
};

const config = window.VICKREY_RECEIPTS_CONFIG || {};
const DOCUMENTED_DEMO_TOKENS = Object.freeze({
  claimant: "demo-claimant-token-change-me",
  observer: "demo-observer-token-change-me",
  verifier: "demo-verifier-token-change-me",
  settlement: "demo-settlement-token-change-me",
});
const DOCUMENTED_DEMO_PUBLIC_KEY =
  "9ec22a5e31611ca5ac59b8545e60000be7a50181a28460cb21a5b63ed19dc76d";
const STAGE_ORDER = [
  "health",
  "claim",
  "remote_evidence",
  "field_evidence",
  "verdict",
  "settlement",
  "receipt",
];
const ACTION_STAGE = {
  health: "health",
  create: "claim",
  remote: "remote_evidence",
  task: "field_evidence",
  seal: "field_evidence",
  submit: "field_evidence",
  verdict: "verdict",
  settle: "settlement",
  receipt: "receipt",
};
const ACTION_LABEL = {
  health: "demo boundary check",
  create: "challenge creation",
  remote: "remote evidence",
  task: "field-task creation",
  seal: "local seal",
  submit: "commitment submission",
  verdict: "verdict signing and submission",
  settle: "simulated settlement",
  receipt: "public receipt fetch",
};
const BADGE_TEXT = {
  pending: "Waiting",
  running: "Working",
  success: "Complete",
  error: "Failed",
  blocked: "Not reached",
  skipped: "Not permitted",
};
const stages = new Map(
  [...document.querySelectorAll(".stage")].map((element) => [
    element.dataset.stage,
    {
      element,
      detail: element.querySelector(".stage-detail"),
      badge: element.querySelector(".stage-badge"),
    },
  ]),
);

const state = {
  apiBase: "",
  baseError: null,
  running: false,
  lookupRunning: false,
  context: null,
  receipt: null,
};

function setStatus(message) {
  dom.status.textContent = message;
}

function setError(error, active = true) {
  const message = error instanceof Error ? error.message : String(error);
  dom.error.textContent = active
    ? `${error instanceof ApiError && error.code ? `[${error.code}] ` : ""}${message}`
    : "No errors.";
  dom.error.dataset.active = String(active);
}

function setStage(name, status, detail) {
  const stage = stages.get(name);
  if (!stage) return;
  stage.element.dataset.state = status;
  stage.badge.textContent = BADGE_TEXT[status] || status;
  if (detail !== undefined) stage.detail.textContent = detail;
}

function resetStages() {
  const initialDetails = {
    health: "Not checked.",
    claim: "Immutable claim and criteria not created.",
    remote_evidence: "Context only; never cryptographic proof.",
    field_evidence:
      "A task is permitted only after insufficient remote evidence.",
    verdict: "Canonical Ed25519 verdict signed under the local demo policy.",
    settlement: "Deterministic simulator only; no real funds.",
    receipt: "Fetched separately from the redacted public endpoint.",
  };
  for (const name of STAGE_ORDER)
    setStage(name, "pending", initialDetails[name]);
}

function blockLaterStages(action) {
  const stageName = ACTION_STAGE[action];
  const index = STAGE_ORDER.indexOf(stageName);
  for (const later of STAGE_ORDER.slice(index + 1)) {
    if (stages.get(later).element.dataset.state === "pending") {
      setStage(later, "blocked", "Not reached because the workflow stopped.");
    }
  }
}

function updateButtons() {
  const failed = Boolean(state.context?.failedAt);
  dom.fields.disabled = state.running || failed || Boolean(state.baseError);
  dom.run.disabled = state.running || failed || Boolean(state.baseError);
  dom.retry.hidden = !failed || state.running;
  dom.retry.disabled = state.running || Boolean(state.baseError);
  dom.reset.hidden = state.running || (!failed && !state.context);
  dom.reset.disabled = state.running;
  dom.download.disabled = !state.context?.localRecord;
  dom.lookupButton.disabled =
    state.running || state.lookupRunning || failed || Boolean(state.baseError);
  dom.lookupId.disabled = dom.lookupButton.disabled;
  dom.workflow.setAttribute("aria-busy", String(state.running));
  dom.run.textContent =
    state.context && !failed ? "Run another demo" : "Run demo workflow";
}

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function definitionList(entries) {
  const list = node("dl", "receipt-dl");
  for (const [label, value, mono = false] of entries) {
    const row = node("div");
    row.append(node("dt", "", label));
    list.append(row);
    row.append(node("dd", mono ? "mono" : "", value ?? "—"));
  }
  return list;
}

function receiptCard(title, wide = false) {
  const card = node(
    "section",
    `receipt-card${wide ? " receipt-card-wide" : ""}`,
  );
  card.append(node("h4", "", title));
  return card;
}

function bulletList(items) {
  const list = node("ul");
  for (const item of items) list.append(node("li", "", item));
  return list;
}

function renderReceipt(receipt, { focus = false } = {}) {
  const problems = publicReceiptProblems(receipt);
  if (problems.length) {
    throw new Error(
      `The receipt response violated the expected public redaction contract and was not displayed: ${problems.join("; ")}.`,
    );
  }
  const challenge = receipt.challenge;
  const criteria = challenge.criteria;
  const remote = receipt.remote_evidence;
  const field = receipt.field_evidence;
  const verdict = receipt.verdict;
  const settlement = receipt.settlement;
  const article = node("article", "receipt");
  article.setAttribute("aria-label", "Redacted public Reality Receipt");

  const header = node("header", "receipt-header");
  const heading = node("div");
  heading.append(node("p", "eyebrow", "Reality Receipts · public record"));
  heading.append(node("h3", "", challenge.claim));
  heading.append(
    node("p", "receipt-id", `${receipt.receipt_id} · ${receipt.schema}`),
  );
  const stamp = node(
    "div",
    "receipt-stamp",
    receipt.status.replaceAll("_", " "),
  );
  stamp.dataset.status = receipt.status;
  header.append(heading, stamp);
  article.append(header);

  const grid = node("div", "receipt-grid");
  const claimCard = receiptCard("Claim and challenge", true);
  claimCard.append(node("p", "claim-text", challenge.claim));
  claimCard.append(
    definitionList([
      ["Challenge ID", challenge.id, true],
      ["Category", challenge.category],
      ["Sponsor", challenge.sponsor],
      [
        "Bounty",
        `${challenge.bounty.amount.toLocaleString()} ${challenge.bounty.currency} (simulated)`,
      ],
      ["Expires", challenge.expires_at],
      ["Criteria hash", receipt.criteria_hash, true],
    ]),
  );
  grid.append(claimCard);

  const criteriaCard = receiptCard("Public criteria");
  criteriaCard.append(node("p", "", criteria.must_observe));
  criteriaCard.append(
    definitionList([
      ["Public location", criteria.public_location],
      ["Radius", `${criteria.radius_m} m`],
    ]),
  );
  criteriaCard.append(node("p", "", "Required details"));
  criteriaCard.append(bulletList(criteria.required_details));
  criteriaCard.append(node("p", "", "Reject if"));
  criteriaCard.append(
    criteria.reject_if.length
      ? bulletList(criteria.reject_if)
      : node("p", "", "None specified."),
  );
  grid.append(criteriaCard);

  const remoteCard = receiptCard("Remote evidence");
  remoteCard.append(node("span", "decision", remote.status));
  remoteCard.append(node("p", "", remote.summary));
  remoteCard.append(
    definitionList([
      ["Provider", `${remote.provider} ${remote.provider_version}`],
      ["Source label", remote.source_label],
      ["Checked", remote.checked_at],
    ]),
  );
  remoteCard.append(
    node("p", "boundary-note", "Remote context is not cryptographic proof."),
  );
  grid.append(remoteCard);

  const fieldCard = receiptCard("Field evidence");
  fieldCard.append(
    definitionList([
      ["State", field.state],
      ["Submission ID", field.submission_id, true],
      ["Observer", field.observer],
      ["Source", field.source_label],
      ["Commitment", field.commitment, true],
      [
        "Raw observation received",
        field.raw_observation_received ? "Yes" : "No",
      ],
      [
        "Verified against raw record",
        field.commitment_verified_against_raw_record ? "Yes" : "No",
      ],
    ]),
  );
  fieldCard.append(
    node(
      "p",
      "boundary-note",
      "The service received a commitment, not the raw observation or precise location.",
    ),
  );
  grid.append(fieldCard);

  const verdictCard = receiptCard("Verifier verdict");
  const decision = node("span", "decision", verdict.verdict);
  decision.dataset.verdict = verdict.verdict;
  verdictCard.append(decision);
  verdictCard.append(node("p", "", verdict.reason));
  verdictCard.append(
    definitionList([
      ["Policy", `${verdict.policy.id} v${verdict.policy.version}`],
      ["Verifier", verdict.verifier],
      ["Issued", verdict.issued_at],
      ["Resolved", verdict.resolved_at],
      ["Key fingerprint", verdict.verifier_key_fingerprint, true],
      ["Verification source", verdict.verification_source],
    ]),
  );
  const signature = node("details", "signature-details");
  signature.append(node("summary", "", "Show public verdict signature"));
  signature.append(node("pre", "", verdict.signature));
  verdictCard.append(signature);
  verdictCard.append(
    node(
      "p",
      "boundary-note",
      "The verifier applies explicit policy and may be wrong.",
    ),
  );
  grid.append(verdictCard);

  const settlementCard = receiptCard("Simulated settlement");
  settlementCard.append(
    definitionList([
      ["Operation", settlement.operation || "Pending"],
      ["Status", settlement.status],
      ["Recipient", settlement.recipient || "—"],
      [
        "Amount",
        settlement.amount === null ? "—" : settlement.amount.toLocaleString(),
      ],
      ["Currency", settlement.currency],
      ["Network", settlement.network],
      [
        "Simulator transaction",
        settlement.txid || "None",
        Boolean(settlement.txid),
      ],
      ["Settled", settlement.settled_at || "—"],
      ["Real funds", settlement.real_funds ? "Yes" : "No"],
    ]),
  );
  settlementCard.append(
    node(
      "p",
      "boundary-note",
      "Deterministic simulator only: no wallet, chain, QIE, or real funds.",
    ),
  );
  grid.append(settlementCard);

  const timestampsCard = receiptCard("Public timeline", true);
  timestampsCard.append(
    definitionList(
      Object.entries(receipt.timestamps).map(([label, value]) => [
        label.replaceAll("_", " "),
        value,
        false,
      ]),
    ),
  );
  grid.append(timestampsCard);

  const limitationsCard = receiptCard("Limitations", true);
  limitationsCard.append(bulletList(receipt.limitations));
  grid.append(limitationsCard);
  article.append(grid);
  article.append(
    node(
      "p",
      "receipt-footer",
      `Fetched from the public redacted endpoint at ${isoUtcMicros(new Date())}. This page did not receive the raw observation, observer signature, or observer public key.`,
    ),
  );

  dom.receipt.replaceChildren(article);
  dom.receipt.hidden = false;
  dom.receiptEmpty.hidden = true;
  dom.receiptActions.hidden = false;
  dom.receiptShare.href = buildReceiptShareUrl(
    window.location.href,
    challenge.id,
  );
  state.receipt = receipt;
  if (focus) {
    dom.receiptTitle.focus({ preventScroll: true });
    dom.receiptSection.scrollIntoView({ block: "start" });
  }
}

function clearReceipt() {
  dom.receipt.replaceChildren();
  dom.receipt.hidden = true;
  dom.receiptEmpty.hidden = false;
  dom.receiptActions.hidden = true;
  dom.receiptShare.removeAttribute("href");
  state.receipt = null;
}

function renderIdentifiers() {
  const context = state.context;
  dom.ids.replaceChildren();
  if (!context) {
    const row = node("div");
    row.append(node("dt", "", "Challenge"), node("dd", "", "Not created"));
    dom.ids.append(row);
    return;
  }
  const entries = [
    ["Challenge", context.challenge?.id],
    ["Criteria hash", context.challenge?.criteria_hash],
    ["Remote evidence", context.remote?.id],
    ["Remote status", context.remote?.status],
    ["Field task", context.task?.id],
    ["Submission", context.submission?.id],
    ["Commitment", context.localRecord?.commitment],
    ["Observer public key", context.localRecord?.observer_public_key],
    ["Verdict UUID", context.verdict?.verdict_id],
    ["Verdict record", context.verdict?.id],
    ["Settlement", context.settlement?.id],
    ["Simulated transaction", context.settlement?.txid],
  ].filter(
    ([, value]) => value !== undefined && value !== null && value !== "",
  );
  if (!entries.length) entries.push(["Workflow", "Preparing"]);
  for (const [label, value] of entries) {
    const row = node("div");
    row.append(node("dt", "", label), node("dd", "", String(value)));
    dom.ids.append(row);
  }
}

function toLocalDateTimeInput(date) {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

function initializeExpiry() {
  const now = Date.now();
  dom.expiry.value = toLocalDateTimeInput(new Date(now + 2 * 60 * 60 * 1000));
  dom.expiry.min = toLocalDateTimeInput(new Date(now + 60_000));
  dom.expiry.max = toLocalDateTimeInput(
    new Date(now + 30 * 24 * 60 * 60 * 1000 - 60_000),
  );
}

function parseLines(value, { required = false, max = 5 } = {}) {
  const items = value
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean);
  if (required && items.length === 0)
    throw new Error("Required details cannot be empty.");
  if (items.length > max)
    throw new Error(`Provide no more than ${max} items, one per line.`);
  for (const item of items) {
    if (Array.from(item).length > 200) {
      throw new Error(
        "Each criteria list item must be 200 characters or fewer.",
      );
    }
  }
  return items;
}

function readClaimSnapshot() {
  try {
    const requiredDetails = parseLines(dom.requiredDetails.value, {
      required: true,
    });
    const rejectIf = parseLines(dom.rejectIf.value);
    const expiresAt = isoUtcMicros(new Date(dom.expiry.value));
    const now = Date.now();
    if (Date.parse(expiresAt) <= now)
      throw new Error("Expiry must be in the future.");
    if (Date.parse(expiresAt) > now + 30 * 24 * 60 * 60 * 1000) {
      throw new Error(
        "Expiry must be within the service's 30-day maximum window.",
      );
    }
    const claim = dom.claim.value.trim();
    const mustObserve = dom.mustObserve.value.trim();
    const publicLocation = dom.publicLocation.value.trim();
    const observationNote = dom.observationNote.value.trim();
    if (!claim || !mustObserve || !publicLocation || !observationNote) {
      throw new Error(
        "Claim, criteria, public location, and observation note are required.",
      );
    }
    const radius = Number(dom.radius.value);
    const bounty = Number(dom.bounty.value);
    if (!Number.isInteger(radius) || radius < 1 || radius > 1000) {
      throw new Error("Radius must be an integer from 1 to 1,000 metres.");
    }
    if (!Number.isInteger(bounty) || bounty < 1 || bounty > 1_000_000) {
      throw new Error(
        "Bounty must be an integer from 1 to 1,000,000 simulated credits.",
      );
    }
    return {
      claim,
      category: dom.category.value,
      expires_at: expiresAt,
      bounty_amount: bounty,
      criteria: {
        must_observe: mustObserve,
        public_location: publicLocation,
        radius_m: radius,
        required_details: requiredDetails,
        reject_if: rejectIf,
      },
      outcome: dom.outcome.value,
      observation_note: observationNote,
    };
  } catch (error) {
    setError(error);
    setStatus("The claim was not submitted. Correct the form and try again.");
    return null;
  }
}

function assertDemoConfiguration() {
  for (const role of Object.keys(DOCUMENTED_DEMO_TOKENS)) {
    if (config.demoCredentials?.[role] !== DOCUMENTED_DEMO_TOKENS[role]) {
      throw new Error(
        `Refusing to run: ${role} credentials are not the documented local demo token.`,
      );
    }
  }
  if (config.demoVerifierPublicKeyHex !== DOCUMENTED_DEMO_PUBLIC_KEY) {
    throw new Error(
      "Refusing to run: the configured verifier key is not the documented demo public key.",
    );
  }
  if (!config.demoVerifierPrivateKeyPkcs8Base64) {
    throw new Error(
      "Refusing to run: the documented demo-only verifier private key is missing.",
    );
  }
}

async function checkedHealth({ updateStage = false } = {}) {
  if (updateStage) {
    setStage(
      "health",
      "running",
      "Checking /healthz before any credential is sent.",
    );
  }
  const response = await requestJson(healthUrl(state.apiBase));
  const failures = demoHealthFailures(response.data);
  if (failures.length) {
    setStage("health", "error", `Refused: ${failures.join("; ")}.`);
    throw new Error(
      `Refusing to run because /healthz failed the demo boundary: ${failures.join("; ")}. No demo credential was sent.`,
    );
  }
  state.context.health = response.data;
  if (updateStage) {
    setStage(
      "health",
      "success",
      `mode=demo · real_funds=false · settlement_network=simulated_testnet. Provider: ${response.data.remote_evidence_provider}; settlement: ${response.data.settlement_adapter}.`,
    );
  }
  return response.data;
}

async function mutate(action, { role, url, body }) {
  const context = state.context;
  context.currentAction = action;
  await checkedHealth();
  setStage(
    ACTION_STAGE[action],
    "running",
    action === "seal"
      ? "Generating an observer key and sealing locally with ../field/trust.js."
      : `Sending ${action} request with a unique idempotency key.`,
  );
  if (!context.requests[action]) {
    context.requests[action] = {
      key: newIdempotencyKey(action),
      body: body === undefined ? "{}" : JSON.stringify(body),
    };
  }
  const request = context.requests[action];
  const result = await requestJson(url, {
    method: "POST",
    body: request.body,
    token: config.demoCredentials[role],
    idempotencyKey: request.key,
    expectedStatus: 201,
  });
  if (result.replayed) {
    setStage(
      ACTION_STAGE[action],
      "running",
      "The service returned the original response for this idempotency key.",
    );
  }
  return result.data;
}

function requireChallengeId(challenge) {
  const id = normalizeUuid(challenge?.id, "challenge id");
  if (!/^[0-9a-f]{64}$/i.test(challenge?.criteria_hash || "")) {
    throw new Error("Challenge response has no valid criteria hash.");
  }
  return id;
}

async function runWorkflow() {
  const context = state.context;
  try {
    if (!context.health) {
      context.currentAction = "health";
      assertDemoConfiguration();
      await checkedHealth({ updateStage: true });
      await assertWebCryptoEd25519();
      if (!window.VickreyTrust?.sealObservation) {
        throw new Error(
          "../field/trust.js is unavailable; no claim was created.",
        );
      }
    }

    if (!context.challenge) {
      const { claim, category, expires_at, bounty_amount, criteria } =
        context.snapshot;
      const data = await mutate("create", {
        role: "claimant",
        url: apiUrl(state.apiBase, "/v1/challenges"),
        body: { claim, category, criteria, expires_at, bounty_amount },
      });
      const challenge = data.challenge;
      requireChallengeId(challenge);
      context.challenge = challenge;
      setStage(
        "claim",
        "success",
        `Challenge ${context.challenge.id} created with immutable criteria hash ${context.challenge.criteria_hash}.`,
      );
      renderIdentifiers();
    }

    if (!context.remote) {
      const data = await mutate("remote", {
        role: "claimant",
        url: challengeUrl(
          state.apiBase,
          context.challenge.id,
          "/remote-evidence",
        ),
      });
      const remote = data.remote_evidence;
      if (
        !["likely", "unlikely", "insufficient", "unavailable"].includes(
          remote?.status,
        )
      ) {
        throw new Error("Remote evidence returned an unsupported status.");
      }
      if (remote.is_cryptographic_proof !== false) {
        throw new Error(
          "Remote evidence violated the not-proof boundary; workflow stopped.",
        );
      }
      context.remote = remote;
      setStage(
        "remote_evidence",
        "success",
        `${context.remote.status}: ${context.remote.summary} Context only; not proof.`,
      );
      renderIdentifiers();
    }

    if (!fieldTaskAllowed(context.remote)) {
      setStage(
        "field_evidence",
        "skipped",
        `Not requested: remote status is ${context.remote.status}; the service permits a field task only for insufficient.`,
      );
      for (const later of ["verdict", "settlement", "receipt"]) {
        setStage(
          later,
          "blocked",
          "Not reached because field evidence was not permitted.",
        );
      }
      context.failedAt = null;
      state.running = false;
      setStatus(
        `Workflow stopped honestly after remote evidence: ${context.remote.status}. No field task, verdict, settlement, or receipt is claimed. Run again for a new deterministic demo case.`,
      );
      setError(null, false);
      updateButtons();
      return;
    }

    if (!context.task) {
      const data = await mutate("task", {
        role: "claimant",
        url: challengeUrl(state.apiBase, context.challenge.id, "/field-task"),
      });
      const task = data.field_task;
      normalizeUuid(task?.id, "task id");
      if (task.public_location !== context.challenge.criteria.public_location) {
        throw new Error(
          "Field task public location does not match the challenge criteria.",
        );
      }
      context.task = task;
      setStage(
        "field_evidence",
        "running",
        `Field task ${context.task.id} created for ${context.task.public_location}, radius ${context.task.radius_m} m.`,
      );
      renderIdentifiers();
    }

    if (!context.localRecord) {
      context.currentAction = "seal";
      setStage(
        "field_evidence",
        "running",
        "Generating an observer key and sealing public-safe payload/time locally with ../field/trust.js.",
      );
      context.localRecord = await createLocalSealedRecord(window.VickreyTrust, {
        challengeId: context.challenge.id,
        criteriaHash: context.challenge.criteria_hash,
        task: context.task,
        claim: context.snapshot.claim,
        category: context.snapshot.category,
        criteria: context.challenge.criteria,
        outcome: context.snapshot.outcome,
        observationNote: context.snapshot.observation_note,
        observedAt: new Date(),
      });
      setStage(
        "field_evidence",
        "running",
        "Local Vickrey seal verified. Signature and observer public key retained locally; raw payload not uploaded.",
      );
      renderIdentifiers();
      updateButtons();
    }

    if (!context.submission) {
      const submissionBody = buildSubmissionRequest(
        context.localRecord.commitment,
        context.localRecord.public_metadata,
      );
      const data = await mutate("submit", {
        role: "observer",
        url: challengeUrl(state.apiBase, context.challenge.id, "/submissions"),
        body: submissionBody,
      });
      const submission = data.submission;
      normalizeUuid(submission?.id, "submission id");
      if (submission.commitment !== context.localRecord.commitment) {
        throw new Error(
          "Submission response commitment does not match the local seal.",
        );
      }
      context.submission = submission;
      context.localRecord.submission_id = submission.id;
      setStage(
        "field_evidence",
        "success",
        "Commitment and allowlisted public metadata accepted. Raw observation, observer signature, and observer public key were not sent.",
      );
      renderIdentifiers();
      updateButtons();
    }

    if (!context.verdict) {
      context.currentAction = "verdict";
      const policy = applyDemoPublicNoticePolicy({
        record: context.localRecord,
        challenge: context.challenge,
        task: context.task,
        outcome: context.snapshot.outcome,
        observationNote: context.snapshot.observation_note,
      });
      if (!context.signedVerdict) {
        setStage(
          "verdict",
          "running",
          `Local demo policy ${policy.policy_id} v${policy.policy_version} applied: ${policy.verdict}. Signing canonical UTF-8 JSON.`,
        );
        context.signedVerdict = await signCanonicalVerdict(
          {
            verdict_id: newUuid(),
            challenge_id: context.challenge.id,
            submission_id: context.submission.id,
            submission_version: context.submission.version,
            commitment: context.localRecord.commitment,
            criteria_hash: context.challenge.criteria_hash,
            verdict: policy.verdict,
            policy_id: policy.policy_id,
            policy_version: policy.policy_version,
            reason: policy.reason,
            issued_at: new Date(),
          },
          {
            privateKey: config.demoVerifierPrivateKeyPkcs8Base64,
            publicKeyHex: config.demoVerifierPublicKeyHex,
          },
        );
      }
      const data = await mutate("verdict", {
        role: "verifier",
        url: submissionUrl(state.apiBase, context.submission.id, "/verdicts"),
        body: context.signedVerdict.body,
      });
      const verdict = data.verdict;
      normalizeUuid(verdict?.id, "verdict record id");
      if (
        verdict.verdict_id !== context.signedVerdict.payload.verdict_id ||
        verdict.signature !== context.signedVerdict.body.signature
      ) {
        throw new Error(
          "Verdict response does not match the locally signed verdict.",
        );
      }
      context.verdict = verdict;
      setStage("verdict", "success", `${policy.verdict}: ${policy.reason}`);
      renderIdentifiers();
    }

    if (!context.settlement) {
      const data = await mutate("settle", {
        role: "settlement",
        url: verdictUrl(state.apiBase, context.verdict.id),
      });
      const settlement = data.settlement;
      if (
        settlement.real_funds !== false ||
        settlement.network !== "simulated_testnet"
      ) {
        throw new Error(
          "Settlement response violated the simulated-no-real-funds boundary.",
        );
      }
      context.settlement = settlement;
      setStage(
        "settlement",
        "success",
        `${context.settlement.operation}: ${context.settlement.amount} ${context.settlement.currency}. ${context.settlement.txid || "No simulator transaction (no payout)"}. No real funds.`,
      );
      renderIdentifiers();
    }

    if (!context.receipt) {
      context.currentAction = "receipt";
      setStage(
        "receipt",
        "running",
        "Fetching the separate redacted public receipt.",
      );
      const response = await requestJson(
        receiptUrl(state.apiBase, context.challenge.id),
      );
      if (response.data.challenge?.id !== context.challenge.id) {
        throw new Error(
          "Public receipt challenge id does not match this workflow.",
        );
      }
      renderReceipt(response.data);
      context.receipt = response.data;
      setStage(
        "receipt",
        "success",
        "Redacted public receipt fetched and rendered. Raw observation and public metadata are absent.",
      );
    }

    context.failedAt = null;
    state.running = false;
    setStatus(
      `Demo complete: ${context.receipt.status}. Verdict ${context.verdict.verdict}; settlement ${context.settlement.operation} on simulated_testnet with no real funds.`,
    );
    setError(null, false);
    updateButtons();
  } catch (error) {
    const action = context.currentAction || "health";
    context.failedAt = action;
    setStage(ACTION_STAGE[action], "error", `Failed: ${error.message}`);
    blockLaterStages(action);
    setError(error);
    setStatus(
      `Workflow stopped at ${ACTION_LABEL[action]}. No later success is claimed. Retry reuses the saved request body and idempotency key where applicable.`,
    );
    state.running = false;
    renderIdentifiers();
    updateButtons();
  }
}

async function startWorkflow() {
  if (state.running || state.baseError) return;
  const snapshot = readClaimSnapshot();
  if (!snapshot) return;
  state.context = {
    snapshot,
    requests: {},
    health: null,
    challenge: null,
    remote: null,
    task: null,
    localRecord: null,
    submission: null,
    verdict: null,
    signedVerdict: null,
    settlement: null,
    receipt: null,
    failedAt: null,
    currentAction: null,
  };
  clearReceipt();
  setError(null, false);
  resetStages();
  renderIdentifiers();
  setStatus(
    "Checking the demo boundary. No credential is sent until /healthz passes.",
  );
  state.running = true;
  updateButtons();
  await runWorkflow();
}

async function retryWorkflow() {
  if (!state.context?.failedAt || state.running) return;
  setError(null, false);
  setStatus(
    `Retrying ${ACTION_LABEL[state.context.failedAt]} with the saved local state${
      state.context.requests[state.context.failedAt]
        ? " and the same idempotency key/request body"
        : ""
    }.`,
  );
  state.running = true;
  updateButtons();
  await runWorkflow();
}

function resetWorkflow() {
  state.context = null;
  state.running = false;
  clearReceipt();
  resetStages();
  renderIdentifiers();
  setError(null, false);
  setStatus(
    "Ready for a new local run. Previous server records, if any, are unchanged and were not deleted.",
  );
  updateButtons();
  dom.claim.focus();
}

async function lookupReceipt(challengeId, { focus = false } = {}) {
  if (state.running || state.lookupRunning || state.baseError) return;
  let id;
  try {
    id = normalizeUuid(challengeId, "challenge id");
  } catch (error) {
    setError(error);
    setStatus("Public receipt lookup was not sent.");
    return;
  }
  clearReceipt();
  setError(null, false);
  setStatus(
    `Fetching public receipt for challenge ${id}. No bearer token is used.`,
  );
  state.lookupRunning = true;
  updateButtons();
  try {
    const response = await requestJson(receiptUrl(state.apiBase, id));
    renderReceipt(response.data, { focus });
    setStatus(
      `Public receipt loaded: ${response.data.status}. Settlement is simulated with no real funds.`,
    );
  } catch (error) {
    setError(error);
    setStatus("Public receipt lookup failed. No receipt is displayed.");
  } finally {
    state.lookupRunning = false;
    updateButtons();
  }
}

async function copyReceiptLink() {
  if (!state.receipt) return;
  const link = dom.receiptShare.href;
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(link);
    } else {
      const temporary = node("textarea");
      temporary.value = link;
      temporary.setAttribute("readonly", "");
      temporary.style.position = "fixed";
      temporary.style.opacity = "0";
      document.body.append(temporary);
      temporary.select();
      const copied = document.execCommand("copy");
      temporary.remove();
      if (!copied) throw new Error("Clipboard access was denied");
    }
    setStatus("Shareable public receipt link copied.");
  } catch {
    setStatus(
      `Copy the shareable receipt link from the “Open shareable receipt view” link: ${link}`,
    );
  }
}

function downloadLocalRecord() {
  const record = state.context?.localRecord;
  if (!record) return;
  const blob = new Blob([`${JSON.stringify(record, null, 2)}\n`], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `reality-receipts-${record.challenge_id}.local-sealed.json`;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  setStatus(
    "Local sealed record downloaded. It contains the public-safe payload, observer signature, and observer public key; it is not the public receipt.",
  );
}

dom.form.addEventListener("submit", (event) => {
  event.preventDefault();
  void startWorkflow();
});
dom.retry.addEventListener("click", () => void retryWorkflow());
dom.reset.addEventListener("click", resetWorkflow);
dom.download.addEventListener("click", downloadLocalRecord);
dom.lookupForm.addEventListener("submit", (event) => {
  event.preventDefault();
  void lookupReceipt(dom.lookupId.value, { focus: true });
});
dom.copyLink.addEventListener("click", () => void copyReceiptLink());
dom.print.addEventListener("click", () => window.print());

try {
  const receiptsParam = new URLSearchParams(window.location.search).get(
    "receipts",
  );
  state.apiBase = resolveApiBase({
    configuredBase: config.apiBase || "",
    receiptsParam,
    currentHref: window.location.href,
  });
  dom.endpoint.textContent = state.apiBase
    ? `API: ${state.apiBase}`
    : "API: same origin (/healthz, /v1)";
} catch (error) {
  state.baseError = error;
  dom.endpoint.textContent = "API: invalid base";
  setError(error);
  setStatus(
    "The workflow and receipt lookup are disabled because the API base is invalid.",
  );
}

initializeExpiry();
resetStages();
renderIdentifiers();
updateButtons();

const queryChallenge =
  new URLSearchParams(window.location.search).get("challenge") ??
  new URLSearchParams(window.location.search).get("challenge_id");
if (queryChallenge) {
  dom.lookupId.value = queryChallenge;
  void lookupReceipt(queryChallenge, { focus: true });
}

#!/usr/bin/env node
/* Refill the evidence ledger's board with the product's own sample walk.
 *
 * Every deploy resets the ledger's copy (docs/OPS.md), so the deployed board
 * can be empty when someone looks at it. Rather than a fixture, this runs the
 * field client's real modules — `trust.js` for the Ed25519 seal and the hash,
 * `logbook.js` for the chain, `app.js` for the exact body the client POSTs —
 * over `seed.js`'s sample walk, and drains it to `/ingest` the way a sync does.
 *
 * So the rows are genuine: real signatures, real chain links, coarse locations,
 * `VERIFIED` on the ledger's own two-source check. They are still demo data,
 * which is why every entry is anchored under flow id `sample-walk` — the board
 * groups by flow, so the label is visible on the page, not buried in a field.
 *
 * Usage:
 *
 *   node scripts/seed_ledger.mjs                          # the deployed ledger
 *   node scripts/seed_ledger.mjs http://127.0.0.1:8088    # a local one
 *   node scripts/seed_ledger.mjs --now 2026-10-28T01:29:16.424Z
 *
 * `--now` pins when the walk ended. A sample-walk entry's hash covers its
 * observed_at, so the same `--now` reproduces the same block ids, and `/ingest`
 * is an upsert keyed on block id: re-seeding overwrites those rows (new device
 * key, new signature, same ids) instead of piling up a second copy.
 */
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const dir = new URL("../apps/field/", import.meta.url).pathname;
const field = require(dir + "app.js");
const trust = require(dir + "trust.js");
const logbook = require(dir + "logbook.js");
const seed = require(dir + "seed.js");

const FLOW = "sample-walk";

function parseArgs(argv) {
  const out = { ledger: "https://vickrey-ledger.fly.dev", now: null };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--now") {
      out.now = argv[(i += 1)];
    } else if (arg === "--help" || arg === "-h") {
      out.help = true;
    } else if (!out.ledgerSet) {
      out.ledger = arg;
      out.ledgerSet = true;
    }
  }
  out.ledger = out.ledger.replace(/\/+$/, "");
  return out;
}

const args = parseArgs(process.argv.slice(2));
if (args.help) {
  console.log(
    "usage: node scripts/seed_ledger.mjs [ledgerUrl] [--now ISO_TIMESTAMP]",
  );
  process.exit(0);
}

/* An in-memory outbox: the logbook only needs list/enqueue/size, and nothing
 * here should touch a real device's localStorage. */
const queueEntries = [];
const queue = {
  enqueue(entry) {
    queueEntries.push(entry);
  },
  list() {
    return queueEntries.slice();
  },
  size() {
    return queueEntries.length;
  },
};

const pair = await trust.generateKeyPair();
const publicKeyText = await trust.exportPublicKey(pair.publicKey);
const book = logbook.createLogbook({ trust, queue, infer: {} });

const now = args.now ? new Date(args.now) : new Date();
if (Number.isNaN(now.getTime())) {
  console.error(`not a date: ${args.now}`);
  process.exit(2);
}

console.log(`ledger:     ${args.ledger}`);
console.log(`device key: ${publicKeyText.slice(0, 24)}…`);
console.log(`walk ends:  ${now.toISOString()}  (flow ${FLOW})`);

for (const step of seed.sampleWalk({ now })) {
  const reviewed = field.reviewedIdentification(step.suggestion, step.decision);
  const entry = await book.seal(reviewed, {
    privateKey: pair.privateKey,
    model: step.modelId,
    observedAt: step.observedAt,
    location: trust.coarseLocation(step.location, 2),
  });
  const response = await fetch(`${args.ledger}/ingest`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(field.relayBody(entry, FLOW, publicKeyText)),
  });
  const row = await response.json().catch(() => null);
  if (!response.ok) {
    console.error(`${response.status} refusing ${entry.hash.slice(0, 14)}`);
    console.error(JSON.stringify(row));
    process.exit(1);
  }
  console.log(
    `${response.status} ${entry.payload.species.padEnd(22)} ${String(
      row && row.status,
    ).padEnd(
      9,
    )} block ${entry.hash.slice(0, 14)}  observed ${entry.observed_at}`,
  );
}

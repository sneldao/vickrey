// Browser-facing defaults. These are URLs the browser can open.
//
// Override any of them per-visit without editing this file, which is what
// scripts/demo_field.sh and scripts/demo_single.sh use on random ports:
//
//   index.html?ledger=http://127.0.0.1:8095&commons=http://127.0.0.1:8088
//
// The defaults below point at the deployed ledger on Fly.io, so the hosted
// field client works with no query string at all. The local demo scripts always
// pass explicit parameters, so they are unaffected.
//
//   ledger  — where anchors are POSTed (the Messages API insert path, or
//           scripts/anchor_relay.py in a local demo).
//   commons — the evidence ledger that reads the block back and answers
//           /observations/similar. Defaults to the same host as ledger.
//   place   — a place *name* for the web-context lookup. Never a coordinate:
//           the anchoring rule is not relaxed because a search engine wants a
//           location.
window.VICKREY_CONFIG = {
  ledgerUrl: "https://vickrey-ledger.fly.dev",
  commonsUrl: "https://vickrey-ledger.fly.dev",
  modelEndpoint: "http://127.0.0.1:11434",
  model: "gemma3",
  ledgerLabel: "fly.io",
  place: "Hackney, London",

  // Shielded anchoring — docs/ECATHON.md, wire contract in
  // docs/ZANCHOR_API.md. "public" is today's behaviour (anchor message to the
  // commons). "shielded" sends ONLY the commitment to zanchorUrl and never
  // touches the public commons; the receipt (commitment <-> txid <-> height)
  // stays with the device and the verifier.
  anchorMode: "public",
  zanchorUrl: "http://127.0.0.1:8092",

  // The anchor schedule (timing-leak mitigation). No anchor may sit closer
  // than 30 minutes to its capture, and a batch is spread over a 20-minute
  // jitter window — never at capture, never at "back in range". Demos pass
  // small values via ?minDelay=…&jitter=…; do not shrink these here.
  anchorMinDelayMs: 30 * 60 * 1000,
  anchorJitterMs: 20 * 60 * 1000,
};

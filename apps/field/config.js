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
};

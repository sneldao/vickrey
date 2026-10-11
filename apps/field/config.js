// Browser-facing defaults. These are URLs the browser can open.
//
// Override any of them per-visit without editing this file, which is what
// scripts/demo_field.sh uses on random ports:
//
//   index.html?ledger=http://127.0.0.1:8095&commons=http://127.0.0.1:8088
//
// ledger  — where anchors are POSTed (the Messages API insert path, or
//           scripts/anchor_relay.py in a local demo).
// commons — the evidence ledger that reads the block back and answers
//           /observations/similar. Defaults to the same host as ledger.
window.VICKREY_CONFIG = {
  ledgerUrl: "http://localhost:8088",
  commonsUrl: "http://localhost:8088",
  modelEndpoint: "http://127.0.0.1:11434",
  model: "gemma3",
};

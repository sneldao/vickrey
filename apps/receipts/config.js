/* Reality Receipts browser configuration.
 *
 * apiBase is the service origin or base path, without /v1. An empty value uses
 * the page's own origin: /healthz and /v1/... . For a local service on another
 * port, open index.html?receipts=http://127.0.0.1:8099 (a same-origin proxy is
 * still preferable for browser runs).
 *
 * The credentials below are the public demo credentials documented
 * in services/receipts/README.md. Production configuration rejects them. This
 * app never asks for, reads, or transmits production credentials.
 */
window.VICKREY_RECEIPTS_CONFIG = {
  apiBase: "",
  demoCredentials: {
    claimant: "demo-claimant-token-change-me",
    observer: "demo-observer-token-change-me",
    verifier: "demo-verifier-token-change-me",
    settlement: "demo-settlement-token-change-me",
  },
  demoVerifierPrivateKeyPkcs8Base64:
    "MC4CAQAwBQYDK2VwBCIEIIbpY5LXW+aqAXbpNgZIndVrscwpfw3NnZgUdlFig6nF",
  demoVerifierPublicKeyHex:
    "9ec22a5e31611ca5ac59b8545e60000be7a50181a28460cb21a5b63ed19dc76d",
};

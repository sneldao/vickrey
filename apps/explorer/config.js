// Browser-facing defaults. The Docker entrypoint rewrites this file from
// EXPLORER_LEDGER_URL, DASHBOARD_URL, and HORNET_PUBLIC_URL.
// These are URLs the browser can open, not Docker DNS names.
window.VICKREY_CONFIG = {
  ledgerUrl: "http://localhost:8088",
  dashboardUrl: "http://localhost:31011",
  hornetUrl: "http://localhost:14265",
};

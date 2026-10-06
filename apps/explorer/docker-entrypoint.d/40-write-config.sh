#!/bin/sh
# Rewrite config.js from the container environment. The browser, not this
# container, calls these URLs. EXPLORER_LEDGER_URL is separate from the
# messages-api LEDGER_URL, which points at /ingest and may be a Docker name.
set -eu

json_escape() {
  printf '%s' "$1" | awk '
    BEGIN { ORS = "" }
    {
      gsub(/\\/, "\\\\")
      gsub(/"/, "\\\"")
      if (NR > 1) {
        printf "\\n"
      }
      printf "%s", $0
    }
  '
}

LEDGER_URL="${EXPLORER_LEDGER_URL:-http://localhost:8088}"
DASHBOARD_URL="${DASHBOARD_URL:-http://localhost:31011}"
HORNET_PUBLIC_URL="${HORNET_PUBLIC_URL:-http://localhost:14265}"
OUT="${CONFIG_JS_PATH:-/usr/share/nginx/html/config.js}"

cat >"$OUT" <<EOF
window.VICKREY_CONFIG = {
  ledgerUrl: "$(json_escape "$LEDGER_URL")",
  dashboardUrl: "$(json_escape "$DASHBOARD_URL")",
  hornetUrl: "$(json_escape "$HORNET_PUBLIC_URL")"
};
EOF

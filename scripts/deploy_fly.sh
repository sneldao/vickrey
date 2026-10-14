#!/usr/bin/env bash
# Deploy the single-process ledger to Fly.io, in as few steps as possible.
#
#   ./scripts/deploy_fly.sh
#
# Idempotent: creates the app if it is missing, sets secrets only if the
# corresponding environment variable is exported, deploys, then waits for the
# health check and prints the URLs you need.
#
# Optional, exported before running:
#   MONGODB_URI  -- commons store (Atlas). Unset: the commons panel stays hidden.
#   TAVILY_API_KEY -- web context. Unset: the context button stays hidden.
#
# Neither is required. The ledger anchors and verifies without either.

set -euo pipefail

APP="${FLY_APP:-vickrey-ledger}"
ROOT=$(cd "$(dirname "$0")/.." && pwd)
LEDGER_DIR="${ROOT}/services/ledger"

if ! command -v fly >/dev/null 2>&1; then
  cat >&2 <<'EOF'
flyctl is not installed. One of:

  curl -L https://fly.io/install.sh | sh      # then: export PATH="$HOME/.fly/bin:$PATH"
  brew install flyctl

EOF
  exit 1
fi

if ! fly auth whoami >/dev/null 2>&1; then
  echo "Not authenticated. Run:  fly auth login   (opens a browser)" >&2
  exit 1
fi

echo "==> signed in as $(fly auth whoami 2>/dev/null)"

# Create the app if it does not exist. `fly apps create` fails if it does, and
# that failure is not fatal here.
if ! fly apps list --json 2>/dev/null | grep -q "\"${APP}\""; then
  echo "==> creating app ${APP} (lhr, per fly.toml)"
  fly apps create "${APP}" --org personal -y >/dev/null || \
    echo "    (app create reported something; continuing)"
else
  echo "==> app ${APP} already exists"
fi

SECRETS=()
[[ -n "${MONGODB_URI:-}" ]] && SECRETS+=("MONGODB_URI=${MONGODB_URI}")
[[ -n "${TAVILY_API_KEY:-}" ]] && SECRETS+=("TAVILY_API_KEY=${TAVILY_API_KEY}")
if [[ ${#SECRETS[@]} -gt 0 ]]; then
  echo "==> setting secrets: ${SECRETS[*]%%=*}"
  fly secrets set "${SECRETS[@]}" >/dev/null
else
  echo "==> no MONGODB_URI / TAVILY_API_KEY exported; deploying without them"
fi

echo "==> deploying (building the image; this is the slow part)"
# Run from services/ledger so the build context is that directory and the
# Dockerfile resolves relative to fly.toml. --build-context does not exist in
# this flyctl version.
cd "${LEDGER_DIR}"
fly deploy --wait-timeout 5m 2>&1 | tail -20

# REQUIRED, not optional. Fly's default rolling deploy leaves the old machine
# running alongside the new one, so the app comes up with TWO of them. With
# HORNET_EMBEDDED=1 each machine holds its own in-memory block store and its own
# SQLite file, so requests round-robin between two ledgers that cannot see each
# other: a block registered on one is missing on the other, so records strand at
# PENDING and the tamper route randomly 404s. This is silent -- health stays
# green on both machines.
echo "==> scaling to exactly 1 machine"
fly scale count 1 --yes >/dev/null 2>&1 || echo "    (scale failed; check 'fly machine list')"
sleep 5
MACHINES=$(fly machine list 2>/dev/null | grep -c "shared-cpu" || true)
echo "    machines running: ${MACHINES:-?}${MACHINES:+ (must be 1)}"

URL="https://${APP}.fly.dev"
echo "==> waiting for health"
for _ in $(seq 1 40); do
  if curl -sf "${URL}/health" >/dev/null 2>&1; then
    break
  fi
  sleep 3
done

echo
curl -sf "${URL}/health" | python3 -m json.tool 2>/dev/null || \
  echo "  (no health response yet -- check: fly logs)"

cat <<EOF

Deployed: ${URL}

  health       ${URL}/health
  ledger docs  ${URL}/docs

Field client (append this to your demo URL):

  ?ledger=${URL}&commons=${URL}&ledgerLabel=fly.io

Try it:  bash scripts/demo_field.sh is not needed -- open the field client
against the deployed ledger and seal, tamper, and sync.
EOF

#!/usr/bin/env bash
# Run the zanchor service against a local zcashd (regtest) for the dev loop.
#
#   ZCASH_RPC=http://zanchor:PASS@127.0.0.1:28232 ./run_local.sh
#
# Env: ZCASH_RPC (required), plus ZANCHOR_MODE / ZANCHOR_ANCHOR_ZADDR /
# ZANCHOR_RECIPIENT_ZADDR / ZANCHOR_RECIPIENT_TADDR as the service reads them
# (docs/ZANCHOR_API.md, app/main.py).
set -euo pipefail
cd "$(dirname "$0")"

: "${ZCASH_RPC:?export ZCASH_RPC=http://user:pass@127.0.0.1:28232}"
export ZANCHOR_RPC="${ZCASH_RPC}"
export ZANCHOR_DB="${ZANCHOR_DB:-data/zanchor.db}"

python -m uvicorn app.main:app --host 127.0.0.1 --port 8092

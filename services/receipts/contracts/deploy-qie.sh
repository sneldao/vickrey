#!/usr/bin/env bash
set -euo pipefail

# Deploys the minimal escrow without writing keys or deployment secrets to disk.
# Usage:
#   QIE_DEPLOYER_PRIVATE_KEY=0x... ./deploy-qie.sh testnet
#   QIE_DEPLOYER_PRIVATE_KEY=0x... QIE_MAINNET_ACK=I_APPROVE_REAL_QIE_MAINNET_FUNDS ./deploy-qie.sh mainnet

NETWORK="${1:-testnet}"
case "$NETWORK" in
  testnet)
    RPC_URL="${QIE_RPC_URL:-https://rpc4testnet.qie.digital/}"
    EXPECTED_CHAIN_ID="1983"
    EXPLORER_URL="https://testnet.qie.digital"
    ;;
  mainnet)
    RPC_URL="${QIE_RPC_URL:-https://rpc1mainnet.qie.digital/}"
    EXPECTED_CHAIN_ID="1990"
    EXPLORER_URL="https://mainnet.qie.digital"
    if [[ "${QIE_MAINNET_ACK:-}" != "I_APPROVE_REAL_QIE_MAINNET_FUNDS" ]]; then
      echo "Refusing mainnet deployment without QIE_MAINNET_ACK=I_APPROVE_REAL_QIE_MAINNET_FUNDS" >&2
      exit 2
    fi
    ;;
  *)
    echo "usage: $0 [testnet|mainnet]" >&2
    exit 2
    ;;
esac

if [[ -z "${QIE_DEPLOYER_PRIVATE_KEY:-}" ]]; then
  echo "QIE_DEPLOYER_PRIVATE_KEY is required in the environment" >&2
  exit 2
fi

FORGE="${FOUNDRY_FORGE:-$HOME/.foundry/bin/forge}"
CAST="${FOUNDRY_CAST:-$HOME/.foundry/bin/cast}"
if [[ ! -x "$FORGE" || ! -x "$CAST" ]]; then
  echo "Foundry forge/cast are required (expected under ~/.foundry/bin)" >&2
  exit 2
fi

cd "$(dirname "$0")"
CHAIN_ID="$($CAST chain-id --rpc-url "$RPC_URL")"
if [[ "$CHAIN_ID" != "$EXPECTED_CHAIN_ID" ]]; then
  echo "RPC chain id $CHAIN_ID does not match expected $EXPECTED_CHAIN_ID for $NETWORK" >&2
  exit 2
fi

OPERATOR_ADDRESS="${QIE_OPERATOR_ADDRESS:-}"
if [[ -z "$OPERATOR_ADDRESS" ]]; then
  OPERATOR_ADDRESS="$($CAST wallet address --private-key "$QIE_DEPLOYER_PRIVATE_KEY")"
fi

DEPLOY_JSON="$($FORGE create \
  src/RealityReceiptsEscrow.sol:RealityReceiptsEscrow \
  --rpc-url "$RPC_URL" \
  --private-key "$QIE_DEPLOYER_PRIVATE_KEY" \
  --broadcast \
  --json \
  --constructor-args "$OPERATOR_ADDRESS")"

python3 - "$DEPLOY_JSON" "$NETWORK" "$CHAIN_ID" "$RPC_URL" "$EXPLORER_URL" "$OPERATOR_ADDRESS" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
network, chain_id, rpc_url, explorer, operator = sys.argv[2:7]
address = payload.get("deployedTo")
tx = payload.get("transactionHash")
if not address or not tx:
    raise SystemExit(f"could not parse forge output: {payload}")
print(f"network={network}")
print(f"chain_id={chain_id}")
print(f"contract_address={address}")
print(f"deployment_tx={tx}")
print(f"operator={operator}")
print(f"explorer_tx={explorer}/tx/{tx}")
print("")
print("Verify source (if the explorer has not already indexed it):")
print(
    "forge verify-contract "
    f"{address} src/RealityReceiptsEscrow.sol:RealityReceiptsEscrow "
    f"--chain-id {chain_id} --verifier blockscout --verifier-url {explorer}/api/ "
    f"--constructor-args {operator}"
)
print("")
print("Backend environment:")
print(f"RECEIPTS_SETTLEMENT_ADAPTER=qie_escrow")
print(f"RECEIPTS_QIE_NETWORK=qie_{network}")
print(f"RECEIPTS_QIE_RPC_URL={rpc_url}")
print(f"RECEIPTS_QIE_CHAIN_ID={chain_id}")
print(f"RECEIPTS_QIE_CONTRACT_ADDRESS={address}")
print(f"RECEIPTS_QIE_EXPLORER_URL={explorer}")
print("RECEIPTS_QIE_OPERATOR_PRIVATE_KEY=<set only in the service environment>")
if network == "mainnet":
    print("RECEIPTS_QIE_MAINNET_ACK=I_APPROVE_REAL_QIE_MAINNET_FUNDS")
PY

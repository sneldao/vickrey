"""Regtest block miner for the demo deployment.

zcashd regtest does not auto-mine, and the anchor service's z_sendmany needs
confirmations (minconf 10). This loop mines one block every few seconds —
and refuses to run on anything but a regtest node, checked before any other
node call and again before every block, so it can never mine or spend
against main/testnet.
"""

from __future__ import annotations

import logging
import os
import sys
import time

from app.rpc import ZcashRpc

logger = logging.getLogger("vickrey.miner")
logging.basicConfig(level=logging.INFO, format="%(message)s")

POLL_SECONDS = 3.0
MAX_BACKOFF_SECONDS = 60.0


def require_regtest(rpc: ZcashRpc) -> None:
    net = rpc.network()
    if net != "regtest":
        raise SystemExit(
            f"mine_regtest refuses to run on network {net!r} (regtest only)"
        )


def main() -> int:
    url = os.environ.get("ZANCHOR_RPC", "")
    if not url:
        print("ZANCHOR_RPC is required", file=sys.stderr)
        return 2
    rpc = ZcashRpc(url)
    # The regtest check is the FIRST node call — nothing wallet-facing runs
    # before the chain identity is established.
    require_regtest(rpc)
    backoff = POLL_SECONDS
    logger.info("mining one regtest block every %.0fs", POLL_SECONDS)
    while True:
        try:
            require_regtest(rpc)
            rpc.call("generate", [1])
            backoff = POLL_SECONDS
        except SystemExit:
            raise
        except Exception as exc:  # RpcError or transport: retry, bounded
            # Never log the exception body — RPC URLs can carry credentials.
            logger.warning("mine attempt failed (%s)", type(exc).__name__)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
        time.sleep(backoff)
    return 0


if __name__ == "__main__":
    sys.exit(main())

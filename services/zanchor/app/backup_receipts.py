"""Offline receipt snapshot CLI.

    python -m app.backup_receipts --output ABSOLUTE_PATH

Reads the receipt database at ZANCHOR_DB and writes a consistent online
snapshot to a path that does not yet exist (created mode 600). The output
is plaintext sensitive data — encrypt it before moving it off the host;
see docs/DEPLOY_DEMO.md for the recovery recipe.
"""

from __future__ import annotations

import argparse
import os
import sys

from app.db import Receipts


def main() -> int:
    parser = argparse.ArgumentParser(prog="backup_receipts")
    parser.add_argument("--output", required=True, help="fresh snapshot path")
    args = parser.parse_args()
    if not os.path.isabs(args.output):
        parser.error("--output must be an absolute path")
    source = os.environ.get("ZANCHOR_DB", "")
    if not source or not os.path.isfile(source):
        print("source database not found", file=sys.stderr)
        return 2
    store = None
    try:
        store = Receipts(source)
        store.backup_to(args.output)
    except Exception as exc:
        # Type only: message bodies can carry paths or bearer ids.
        print(f"snapshot failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    finally:
        if store is not None:
            store.close()
    print("Receipt snapshot created")
    return 0


if __name__ == "__main__":
    sys.exit(main())

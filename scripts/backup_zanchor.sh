#!/usr/bin/env bash
# Consistent COLD snapshot of the Vickrey demo anchoring stack, encrypted on
# the host (the encrypted artifact is what moves off-host). Stops the minimum
# containers for a consistent copy, archives an EXACT allowlist — node volume
# (chain+wallet), receipts volume, settings/demo.env, generated metadata —
# encrypts with a symmetric passphrase, and restarts exactly what was running.
#
#   ./backup_zanchor.sh KEY_FILE OUTPUT.gpg
#
# Run on the host (nuncio-vultr) as linuxuser. Brief 503s on the demo API are
# expected during the stop window. OUTPUT must not exist. The key file must
# live OUTSIDE /home/linuxuser/.config/vickrey (it is archived; keys must
# never be inside their own backup).
set -euo pipefail

usage() { echo "usage: $0 KEY_FILE OUTPUT.gpg" >&2; exit 2; }
[ $# -eq 2 ] || usage
KEY_FILE="$1"
OUTPUT="$2"
[ -f "$KEY_FILE" ] || { echo "key file missing" >&2; exit 2; }
[ ! -e "$OUTPUT" ] || { echo "output already exists — refusing to overwrite" >&2; exit 2; }

# The archived settings must never contain the key itself.
case "$(realpath "$KEY_FILE")" in
  /home/linuxuser/.config/vickrey/*)
    echo "key file must live outside /home/linuxuser/.config/vickrey" >&2
    exit 2 ;;
esac
# demo.env is archived, so it must be a regular file, not a link somewhere.
[ -f /home/linuxuser/.config/vickrey/demo.env ] && \
[ ! -L /home/linuxuser/.config/vickrey/demo.env ] || \
  { echo "settings/demo.env missing or not a regular file" >&2; exit 1; }

umask 077

# -- preflight (before anything stops) ---------------------------------------
OUTDIR="$(dirname "$OUTPUT")"
[ -d "$OUTDIR" ] && [ -w "$OUTDIR" ] || { echo "output parent missing or unwritable" >&2; exit 1; }
command -v gpg >/dev/null || { echo "gpg not available" >&2; exit 1; }
for c in vickrey-demo-api vickrey-demo-miner vickrey-zanchor-test vickrey-zcashd-regtest; do
  docker inspect "$c" >/dev/null 2>&1 || { echo "expected container missing: $c" >&2; exit 1; }
done
for v in vickrey-regtest-data vickrey-demo_vickrey_demo_receipts; do
  docker volume inspect "$v" >/dev/null 2>&1 || { echo "expected volume missing: $v" >&2; exit 1; }
done
NODE_IMAGE="$(docker inspect vickrey-zcashd-regtest --format '{{.Config.Image}}')"
API_IMAGE="$(docker inspect vickrey-demo-api --format '{{.Config.Image}}')"
# The configured tag may not exist locally (container built/retagged from
# elsewhere) — fall back to the immutable image id, which always resolves.
docker image inspect "$NODE_IMAGE" >/dev/null 2>&1 || \
  NODE_IMAGE="$(docker inspect vickrey-zcashd-regtest --format '{{.Image}}')"
docker image inspect "$API_IMAGE" >/dev/null 2>&1 || \
  API_IMAGE="$(docker inspect vickrey-demo-api --format '{{.Image}}')"
[ -n "$NODE_IMAGE" ] && [ -n "$API_IMAGE" ] || { echo "images unresolved" >&2; exit 1; }

# WORK sits beside OUTPUT so the atomic hardlink never crosses filesystems.
WORK="$(mktemp -d "$OUTDIR/.vickrey-backup.XXXXXX")"
mkdir -p "$WORK/metadata"
docker inspect vickrey-zcashd-regtest > "$WORK/metadata/node.json"
chmod 600 "$WORK/metadata/node.json"

# -- record original state, then trap ---------------------------------------
declare -a WAS_RUNNING=()
for c in vickrey-zcashd-regtest vickrey-zanchor-test vickrey-demo-api vickrey-demo-miner; do
  [ "$(docker inspect "$c" --format '{{.State.Running}}' 2>/dev/null)" = "true" ] && WAS_RUNNING+=("$c")
done

STATUS=0
cleanup() {
  STATUS=$?
  local rc_fail=0 c
  # Restart only originally-running containers, node first.
  for c in vickrey-zcashd-regtest vickrey-zanchor-test vickrey-demo-api vickrey-demo-miner; do
    case " ${WAS_RUNNING[*]} " in
      *" $c "*)
        docker start "$c" >/dev/null 2>&1 || rc_fail=1 ;;
    esac
  done
  rm -rf "$WORK"
  if [ "$rc_fail" -ne 0 ]; then
    echo "operational error: a container failed to restart — check docker ps" >&2
    exit 1
  fi
  exit "$STATUS"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# -- stop the APIs, then require an empty queue ------------------------------
for c in vickrey-demo-api vickrey-zanchor-test; do
  case " ${WAS_RUNNING[*]} " in *" $c "*) docker stop -t 30 "$c" >/dev/null ;; esac
done

# Read-only pending check via the API image's Python (sqlite3 stdlib) — the
# receipts volume is mounted read-only and the container has no network.
PENDING="$(docker run --rm -i --network none \
  -v vickrey-demo_vickrey_demo_receipts:/receipts:ro \
  --entrypoint python3 "$API_IMAGE" - <<'PY'
import sqlite3, sys
try:
    n = sqlite3.connect("file:/receipts/zanchor.db?mode=ro", uri=True).execute(
        """SELECT COUNT(*) FROM receipts WHERE status IN ('queued', 'broadcast')"""
    ).fetchone()[0]
    print(n)
except Exception:
    sys.exit(1)
PY
)"
if [ "$PENDING" != "0" ]; then
  echo "receipt queue not empty or unreadable; nothing archived" >&2
  exit 1
fi

# -- stop the writer, then the chain; require a clean stop -------------------
for c in vickrey-demo-miner vickrey-zcashd-regtest; do
  case " ${WAS_RUNNING[*]} " in *" $c "*) docker stop -t 60 "$c" >/dev/null ;; esac
done
node_state="$(docker inspect vickrey-zcashd-regtest \
  --format '{{.State.Running}} {{.State.ExitCode}} {{.State.OOMKilled}}')"
if [ "$node_state" != "false 0 false" ]; then
  echo "node did not stop cleanly ($node_state); snapshot would be inconsistent — aborting" >&2
  exit 1
fi

# -- archive -> encrypt -> atomic place -------------------------------------
OUT_TMP="$WORK/backup.gpg"
docker run --rm --network none \
  -v vickrey-regtest-data:/node:ro \
  -v vickrey-demo_vickrey_demo_receipts:/receipts:ro \
  -v /home/linuxuser/.config/vickrey/demo.env:/settings/demo.env:ro \
  -v "$WORK/metadata":/metadata:ro \
  --entrypoint tar "$NODE_IMAGE" -czf - -C / node receipts settings/demo.env metadata \
  | gpg --batch --pinentry-mode loopback --no-symkey-cache \
        --passphrase-file "$KEY_FILE" \
        --symmetric --cipher-algo AES256 \
        --output "$OUT_TMP"

# Atomic placement: hardlink fails if OUTPUT raced into existence.
ln "$OUT_TMP" "$OUTPUT"
chmod 600 "$OUTPUT"
echo "backup completed: $(basename "$OUTPUT")"

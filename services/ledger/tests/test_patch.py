"""The fan-out diff applies to the upstream send_data.py snapshot."""

from __future__ import annotations

import base64
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DIFF = REPO / "patches" / "iota-messages-api-send_data.py.diff"
UPSTREAM_B64 = Path(__file__).resolve().parent / "fixtures" / "send_data_upstream.b64"

# eclipse-aerios/iota-messages-api send_data.py @ 1ed089a (Apache-2.0).
# Stored as base64 so a newline-fixing hook cannot change the snapshot.


def test_messages_api_patch_applies_and_fans_out(tmp_path: Path):
    raw = base64.b64decode(UPSTREAM_B64.read_text())
    assert not raw.endswith(b"\n")
    target = tmp_path / "send_data.py"
    target.write_bytes(raw)

    result = subprocess.run(
        ["patch", "-p1", "--forward", "--batch", f"--input={DIFF}"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    patched = target.read_text()
    compile(patched, str(target), "exec")
    assert (
        'LEDGER_URL = os.environ.get("LEDGER_URL", "http://host.docker.internal:8088/ingest")'
        in patched
    )
    assert "def fanout_ledger" in patched
    assert 'message_obj = requestData["message"]' in patched
    assert "message = json.dumps(message_obj)" in patched
    assert "fanout_ledger(block_id, tag, message_obj, response.status_code)" in patched
    # The on-ledger bytes stay the upstream json.dumps of the object.
    assert "json.dumps(requestData" not in patched

    subprocess.run([sys.executable, "-m", "py_compile", str(target)], check=True)

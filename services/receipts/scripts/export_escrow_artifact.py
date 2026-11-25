"""Copy the compiled escrow ABI/bytecode into the Python service artifact."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (
    ROOT
    / "contracts"
    / "out"
    / "RealityReceiptsEscrow.sol"
    / "RealityReceiptsEscrow.json"
)
TARGET = ROOT / "app" / "artifacts" / "RealityReceiptsEscrow.json"

compiled = json.loads(SOURCE.read_text())
bytecode = compiled["bytecode"]
if isinstance(bytecode, dict):
    bytecode = bytecode["object"]
artifact = {
    "abi": compiled["abi"],
    "bytecode": bytecode,
    "compiler": compiled.get("metadata", {})
    and json.loads(compiled["metadata"]).get("compiler", {}),
    "contractName": "RealityReceiptsEscrow",
}
TARGET.parent.mkdir(parents=True, exist_ok=True)
TARGET.write_text(json.dumps(artifact, separators=(",", ":"), sort_keys=True) + "\n")
print(TARGET)

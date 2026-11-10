"""Bake a source inventory outside the source tree, with readable immutable bytes."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from package_gate import inventory

source, output = map(Path, sys.argv[1:3])
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(inventory(source), indent=2) + '\n')
output.chmod(0o644)

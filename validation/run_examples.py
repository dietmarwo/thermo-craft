"""Run every example in examples/python and save its output next to it.

Usage: python validation/run_examples.py [OUTPUT_DIR]

Each example runs in a fresh interpreter (`-I`) from the project root. The
output of `<name>.py` goes to `examples/python/outputs/<name>.txt`. A summary
with exit status and wall time per example is printed as JSON.
"""

import json
from pathlib import Path
import subprocess
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
examples = sorted((ROOT / "examples" / "python").glob("*.py"))
outputs = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "examples" / "python" / "outputs"
outputs.mkdir(parents=True, exist_ok=True)
summary = {}
for path in examples:
    start = perf_counter()
    result = subprocess.run([sys.executable, "-I", str(path)], cwd=ROOT, capture_output=True,
                            text=True, timeout=300, check=False)
    elapsed = perf_counter() - start
    (outputs / f"{path.stem}.txt").write_text(result.stdout + result.stderr)
    summary[path.stem] = {"exit": result.returncode, "seconds": round(elapsed, 3)}
print(json.dumps(summary, indent=2))
if any(row["exit"] for row in summary.values()):
    raise SystemExit("an example failed")

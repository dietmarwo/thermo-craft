"""Per-call cost of the full, lean and matrix Python APIs on the installed wheel.

Usage: python validation/python_call_costs.py MODULE

Times one regenerative candidate per call and 96-candidate batches, in
interleaved rounds, and prints microseconds per call (min and median of 25
rounds). Run on one CPU (for example `taskset -c 0`) for stable numbers.
"""

import importlib
import json
import statistics
import sys
from time import perf_counter

package = importlib.import_module(sys.argv[1])
example = package.load_example()
prepared = package.Prepared(example["model"])
x = example["parameters"]
rows = [[x[0] * (1 + (i % 13) * 0.003), x[1]] for i in range(96)]
batch = [{"id": f"candidate-{i:04}", "parameters": r} for i, r in enumerate(rows)]
cases = {
    "one_full_evaluate": (400, lambda: prepared.evaluate(x)),
    "one_lean_scores": (400, lambda: prepared.scores([{"id": "one", "parameters": x}])),
    "one_matrix": (400, lambda: prepared.score_matrix([x])),
    "batch96_full": (20, lambda: prepared.batch(batch)),
    "batch96_lean": (20, lambda: prepared.scores(batch)),
    "batch96_matrix": (20, lambda: prepared.score_matrix(rows)),
    "prepare": (400, lambda: package.Prepared(example["model"])),
}
samples = {name: [] for name in cases}
for name, (calls, call) in cases.items():
    call()
for _ in range(25):
    for name, (calls, call) in cases.items():
        start = perf_counter()
        for _ in range(calls):
            call()
        samples[name].append((perf_counter() - start) / calls * 1e6)
print(json.dumps({
    "unit": "microseconds per call; min and median of 25 interleaved rounds",
    "calls": {name: {"min_us": min(values), "median_us": statistics.median(values)}
              for name, values in samples.items()},
}, indent=2))

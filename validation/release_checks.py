"""Check the installed lean and matrix APIs and run the Python snippets in the tutorial."""

import importlib
import json
import math
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory


def check_matrix(prepared, rows, **budget):
    """Compare score_matrix with scores for equal-length rows; return the statuses."""
    lean = prepared.scores([{"id": str(i), "parameters": row} for i, row in enumerate(rows)],
                           **budget)["records"]
    scores, statuses, steps = prepared.score_matrix(rows, **budget)
    assert statuses == [r["status"] for r in lean], (statuses, lean)
    assert steps == [r["steps"] for r in lean], (steps, lean)
    for score, row in zip(scores, lean, strict=True):
        if row["status"] == "complete":
            assert score == row["score"], (score, row)
        else:
            assert row["score"] is None and math.isnan(score), (score, row)
    return statuses

module, tutorial = sys.argv[1:]
package = importlib.import_module(module)
example = package.load_example()
prepared = package.Prepared(example["model"])
candidates = [{"id": "ok", "parameters": example["parameters"]},
              {"id": "bad", "parameters": [1] * 63}]
with TemporaryDirectory() as tmp:
    flag = Path(tmp) / "cancel"
    flag.touch()
    for budget in ({}, {"workers": 4}, {"max_steps": 1}, {"cancel_file": str(flag)}):
        full = prepared.batch(candidates, **budget)
        lean = prepared.scores(candidates, **budget)
        assert lean["model_sha256"] == full["model_sha256"]
        assert lean["records"] == [r | {"metrics": None} for r in full["records"]]
        if "cancel_file" in budget:
            assert lean["records"][0]["status"] == "cancelled"
        matrix_rows = [example["parameters"]] * 2
        if len(example["parameters"]) == 2:
            matrix_rows.append(list(reversed(example["parameters"])))
        statuses = check_matrix(prepared, matrix_rows, **budget)
        if "cancel_file" in budget:
            assert set(statuses) == {"cancelled"}
    if module == "population_epidemiology":
        calendar = package.Prepared({"kind": "calendar", "initial_on_probability": 0.5,
                                     "segments": [{"duration": 1, "on_rate": 0, "off_rate": 0}] * 3})
        query = [{"id": "calendar", "parameters": []}]
        limited = calendar.scores(query, max_steps=2)["records"][0]
        assert (limited["status"], limited["steps"]) == ("work_limit", 2)
        canceled = calendar.scores(query, cancel_file=str(flag))["records"][0]
        assert (canceled["status"], canceled["steps"]) == ("cancelled", 0)
        complete = calendar.scores(query, max_steps=3)["records"][0]
        assert (complete["status"], complete["steps"], complete["score"]) == ("complete", 3, 0.5)
    if module == "rail_craft":
        closed = package.Prepared({
            "resources": [{"name": "one", "clearance": 0}], "horizon": 20,
            "trains": [{"name": "train", "release": 0, "planned": 0, "priority": 0,
                        "route": [{"resource": 0, "duration": 1}]}],
            "closures": [{"resource": 0, "start": a, "end": b} for a, b in ((0, 4), (2, 7), (7, 8))],
        })
        row = closed.evaluate([0, 0], trace=True)
        assert row["status"] == "complete"
        assert row["metrics"]["intervals"][0]["entry"] == 8
    if module == "robotics_control_craft":
        long = package.Prepared(example["model"] | {"dt_s": 1e-4})
        assert long.evaluate(example["parameters"])["status"] == "complete"
        traced = long.evaluate(example["parameters"], trace=True)
        assert traced["status"] == "invalid" and traced["steps"] == 10_001
try:
    prepared.scores([candidates[0] | {"trace": True}])
except ValueError:
    pass
else:
    raise AssertionError("scores accepted a traced candidate")
for bad in ([[1.0, 2.0], [1.0]], []):
    try:
        prepared.score_matrix(bad)
    except ValueError:
        pass
    else:
        raise AssertionError(f"score_matrix accepted {bad!r}")
if module == "thermo_craft":
    properties = package.Prepared({"kind": "property"})
    assert check_matrix(properties, [[3e6, 300.0], [1.0, 400.0], [1e5, 700.0]],
                        workers=2) == ["complete", "invalid", "complete"]
try:
    import numpy
except ImportError:
    numpy = None
if numpy is not None:
    array = numpy.array([example["parameters"]] * 3, dtype=float)
    assert prepared.score_matrix(array) == prepared.score_matrix(array.tolist())

snippets = re.findall(r"^```python\n(.*?)^```", Path(tutorial).read_text(), re.M | re.S)
assert len(snippets) >= 4
namespace = {}
for i, snippet in enumerate(snippets, 1):
    exec(compile(snippet, f"tutorial-{i}", "exec"), namespace)
print(json.dumps({"status": "passed", "tutorial_python_blocks": len(snippets),
                  "lean_api_and_budget_parity": True, "matrix_api_parity": True,
                  "numpy_matrix_input": numpy is not None}))

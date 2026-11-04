# thermo-craft user manual

Version 0.3.0. This manual is for researchers and engineers who use the
model: it covers installation, the model and request formats, every status
and error message, the Python, Rust and command-line interfaces, and how to
get reproducible and fast results. The [model card](model.md) states the
equations and research scope, the [architecture guide](architecture.md)
describes the implementation and its measured performance, and the
[tutorial](tutorial.md) is a shorter walk-through.

Every `python` block in this manual runs as written, in order, in one
session; `validation/release_checks.py` executes them against the installed
wheel. Shell examples were run from the project root on Linux, and their
output is copied from those runs.

## Contents

1. [What the model does](#1-what-the-model-does)
2. [Installation](#2-installation)
3. [Concepts](#3-concepts)
4. [Model reference](#4-model-reference)
5. [Request and result schemas](#5-request-and-result-schemas)
6. [Statuses and error messages](#6-statuses-and-error-messages)
7. [Budgets](#7-budgets)
8. [Python API](#8-python-api)
9. [Application scenarios](#9-application-scenarios)
10. [Optimization](#10-optimization)
11. [Rust API](#11-rust-api)
12. [Command-line interface](#12-command-line-interface)
13. [Reproducibility and provenance](#13-reproducibility-and-provenance)
14. [Performance tips](#14-performance-tips)
15. [Troubleshooting](#15-troubleshooting)

## 1. What the model does

thermo-craft evaluates two kinds of model:

- **`property`**: water and steam properties from IAPWS-IF97 (R7-97(2012))
  regions 1 (compressed liquid), 2 (vapor) and 4 (saturation), bounded to
  1 kPa-16 MPa and 273.16-1073.15 K. The upper pressure keeps saturation
  below region 3.
- **`rankine`**: a closed steam Rankine cycle with fixed boiler and
  condenser pressures and a superheated turbine inlet. Either the simple
  cycle (one expansion, one pump) or a regenerative cycle with two open
  feedwater heaters, three expansion stages and three pumps, whose two
  extraction pressures are the candidate parameters.

The model does not cover IF97 region 3 or 5, closed feedwater heaters,
reheat, arbitrary plant topologies or part-load behavior. All public
quantities are SI: Pa, K, J/kg, J/(kg K) and m^3/kg.

## 2. Installation

### 2.1 From the bundled wheel

The wheel in `packages/` targets Linux x86-64 with the CPython 3.10+ stable
ABI (`abi3`); it was tested with CPython 3.12. It has no Python
dependencies.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --no-deps packages/thermo_craft-0.3.0-cp310-abi3-manylinux_2_34_x86_64.whl
```

The examples in `examples/python/` also use NumPy, SciPy and fcmaes:

```sh
python -m pip install numpy==2.3.5 scipy==1.17.0 fcmaes
```

### 2.2 From source

Building needs Rust 1.88 or later and maturin 1.9.6. The crate's
dependencies are pinned in `Cargo.lock`; Cargo needs them from its registry
or cache.

```sh
python -m pip install 'maturin==1.9.6'
maturin sdist --out dist                      # source distribution
maturin build --release --locked --out dist   # wheel for this machine
python -m pip install --no-deps dist/thermo_craft-0.3.0-*.whl
```

The source distribution `packages/thermo_craft-0.3.0.tar.gz` also builds:
`maturin build --release --locked` inside the extracted directory gives the
manylinux-tagged wheel, and `python -m pip wheel --no-deps thermo_craft-0.3.0.tar.gz`
(which fetches maturin 1.9.6 for an isolated build) gives a wheel tagged
`linux_x86_64`. On the release host both contained the same native
extension as the bundled wheel.

### 2.3 Rust command-line tool and crate

```sh
cargo build --release --locked --bins --examples
target/release/thermo-craft describe
```

The crate archive `packages/thermo-craft-0.3.0.crate` is a gzipped tar
file; unpack it to use it as a path or vendored dependency. The library
name is `thermo_craft`.

### 2.4 Checking an installation

```python
import json
import thermo_craft
from thermo_craft import Prepared, load_example

case = load_example()
prepared = Prepared(case["model"])
row = prepared.evaluate(case["parameters"], trace=True)
assert row["status"] == "complete", row
print(row["id"], row["status"], row["steps"], round(row["score"], 6))
print(prepared.batch([{"id": "v", "parameters": case["parameters"]}])["version"])
```

## 3. Concepts

- **Model**: a JSON object (a Python `dict`) selecting a `kind` and its
  fixed inputs. `Prepared(model)` validates it once, hashes its exact
  serialized bytes and precomputes fixed states (turbine inlet, condenser
  saturation pair).
- **Candidate**: an `id` and a `parameters` vector, evaluated against a
  prepared model. Property queries and extraction pressures are candidates.
- **Record**: the outcome of one candidate: `id`, `status`, `steps`,
  `score`, `metrics` and `detail`.
- **Status**: `complete`, or why the candidate has no score (section 6).
  Invalid and infeasible candidates are normal results, not exceptions.
- **Score**: the number an optimizer minimizes. For a cycle it is minus the
  thermal efficiency; for a property query it is the specific enthalpy in
  J/kg. Only complete records have a score.
- **Steps**: the logical work a candidate used (section 4.6). The step count
  is part of the result contract and identical across releases, worker
  counts and APIs.
- **Budget**: per-call limits on workers, steps, wall time and a cancel
  file (section 7).
- **Three call styles** on the same prepared model and the same evaluator:
  - *full* (`batch`, `evaluate`, `evaluate_json`): records with all metrics;
  - *lean* (`scores`, `scores_json`): the same records with
    `metrics: null`;
  - *matrix* (`score_matrix`): parameter rows in, three lists out
    (scores, statuses, steps), with no JSON in either direction.

  Status, steps and score are identical in all three (score bit for bit).

## 4. Model reference

Unknown fields are rejected everywhere (`deny_unknown_fields`). Numbers are
JSON numbers; the Python wrapper refuses NaN and infinity in models,
candidates and budgets.

### 4.1 `kind: "property"`

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `kind` | string | yes | `"property"` |

No other fields are allowed.

### 4.2 `kind: "rankine"`

| Field | Type | Unit | Required | Bounds and checks | Default |
| --- | --- | --- | --- | --- | --- |
| `kind` | string | - | yes | `"rankine"` | - |
| `boiler_pa` | number | Pa | yes | 1 kPa-16 MPa; greater than `condenser_pa` | - |
| `condenser_pa` | number | Pa | yes | 1 kPa-16 MPa (saturation range) | - |
| `inlet_k` | number | K | yes | 273.16-1073.15 K and above the saturation temperature at `boiler_pa` (superheated inlet) | - |
| `turbine_efficiency` | number | - | yes | 0.1-1.0 (isentropic efficiency of every expansion) | - |
| `pump_efficiency` | number | - | yes | 0.1-1.0 (applied to every pump) | - |
| `min_exhaust_quality` | number | - | yes | 0-1 (minimum vapor mass fraction at the turbine exhaust) | - |
| `extraction` | boolean | - | no | `true`: two open feedwater heaters | `false` |

The packaged example (`models/example.json`, `load_example()`) is an
8 MPa / 813.15 K / 15 kPa regenerative cycle with turbine efficiency 0.88,
pump efficiency 0.8 and a 0.75 exhaust-quality limit.

### 4.3 Model errors

`Prepared(model)` raises `ValueError` (Rust: `Err(String)`) with these
messages:

| Message | Cause |
| --- | --- |
| `invalid pressure ordering, efficiency or exhaust limit` | `boiler_pa <= condenser_pa`, an efficiency outside 0.1-1.0, or `min_exhaust_quality` outside 0-1 |
| `invalid boiler inlet state` | boiler pressure outside 1 kPa-16 MPa, inlet temperature outside 273.16-1073.15 K, or inlet within 1e-7 K of saturation |
| `invalid condenser pressure` | condenser pressure outside 1 kPa-16 MPa |
| `boiler outlet must be superheated` | `inlet_k` at or below the saturation temperature of `boiler_pa` |
| `missing field ...`, `unknown field ...`, `unknown variant ...`, `invalid type ...` | JSON shape errors from the parser, for example ``unknown variant `brayton`, expected `property` or `rankine` `` |

```python
model = case["model"]
for bad in (model | {"boiler_pa": 10e3}, model | {"inlet_k": 500.0},
            model | {"condenser_pa": 500.0}, model | {"kind": "brayton"},
            {k: v for k, v in model.items() if k != "inlet_k"}):
    try:
        Prepared(bad)
    except ValueError as error:
        print(type(error).__name__, str(error)[:60])
```

### 4.4 Candidate parameters

| Model | `parameters` | Meaning |
| --- | --- | --- |
| `property` | `[p_pa, t_k]` | single-phase state at pressure and temperature |
| `property` | `[p_pa, quality, 0]` | saturated state at pressure with vapor mass fraction `quality` in 0-1; the third value must be exactly 0 |
| `rankine`, `extraction: false` | `[]` | the simple cycle has no candidate parameters |
| `rankine`, `extraction: true` | `[low_pa, high_pa]` | extraction pressures of the low- and high-pressure heaters; feasible only if condenser < low < high < boiler |

A P/T pair within 1e-7 K of saturation is rejected: give the quality form
instead.

```python
properties = Prepared({"kind": "property"})
liquid = properties.evaluate([3e6, 300.0])          # compressed liquid, region 1
vapor = properties.evaluate([3500.0, 700.0])        # superheated vapor, region 2
wet = properties.evaluate([1e5, 0.5, 0.0])          # wet steam, region 4
for row in (liquid, vapor, wet):
    s = row["metrics"]["state"]
    print(row["status"], s["t_k"], round(s["h_j_kg"]), s["quality"])
assert liquid["score"] == liquid["metrics"]["state"]["h_j_kg"]
```

### 4.5 Scores and metrics

**Property records.** `score` is the specific enthalpy `h_j_kg`.
`metrics` is `{"state": STATE}`.

**State objects** (`STATE`):

| Field | Unit | Meaning |
| --- | --- | --- |
| `h_j_kg` | J/kg | specific enthalpy |
| `p_pa` | Pa | pressure |
| `quality` | - | vapor mass fraction for saturated and wet states, `null` for single-phase states |
| `s_j_kg_k` | J/(kg K) | specific entropy |
| `t_k` | K | temperature |
| `v_m3_kg` | m^3/kg | specific volume |

Wet enthalpy, entropy and volume follow the lever rule between the
saturated liquid and vapor.

**Cycle records.** `score` is minus the thermal efficiency. All per-mass
quantities refer to one kilogram of boiler flow:

| Metric | Unit | Meaning |
| --- | --- | --- |
| `efficiency` | - | `net_work_j_kg / heat_in_j_kg` |
| `gross_work_j_kg` | J/kg | turbine work of all stages, weighted by the stage mass flows |
| `pump_work_j_kg` | J/kg | pump work, `v * dp / pump_efficiency` per pump with the inlet saturated-liquid volume |
| `net_work_j_kg` | J/kg | gross minus pump work; must be positive |
| `heat_in_j_kg` | J/kg | boiler heat input; must be positive |
| `heat_rejected_j_kg` | J/kg | condenser heat rejection; must be positive |
| `energy_residual_j_kg` | J/kg | heat in minus heat rejected minus net work; must be within 1e-6 of heat in |
| `exhaust_quality` | - | vapor fraction at the turbine exhaust (1 if the exhaust is superheated) |
| `condenser_mass_fraction` | - | mass flow through the last stage and condenser (1 for the simple cycle) |
| `extractions_low_high` | - | bleed mass fractions `[low, high]` (`[0, 0]` for the simple cycle) |
| `heater_residuals_j_kg` | J/kg | mixing energy residuals of the `[low, high]` heaters; must be within 1e-6 of heat in |
| `states` | - | list of `STATE` objects |

`states` lists, for the regenerative cycle: turbine inlet, high-pressure
stage outlet (high bleed), intermediate stage outlet (low bleed), exhaust,
condensate (saturated liquid at the condenser), low-heater outlet and
high-heater outlet (saturated liquid at each extraction pressure). For the
simple cycle: turbine inlet, exhaust and condensate.

```python
row = prepared.evaluate(case["parameters"])
m = row["metrics"]
print(sorted(m))
print(round(m["efficiency"], 6), round(m["exhaust_quality"], 4), m["extractions_low_high"])
assert abs(m["net_work_j_kg"] - (m["gross_work_j_kg"] - m["pump_work_j_kg"])) < 1e-6
assert abs(sum(m["extractions_low_high"]) + m["condenser_mass_fraction"] - 1) < 1e-12
print(len(m["states"]), [s["quality"] for s in m["states"]])
```

### 4.6 Logical steps

Every candidate charges one step on entry. Each turbine stage solves two
states at its outlet pressure: the isentropic reference (from entropy) and
the actual outlet (from enthalpy). An outlet inside the wet region is found
directly by the lever rule and charges nothing; a single-phase outlet
charges 40 steps. The packaged example therefore takes 1 + 3 x 40 = 121
steps (high stage: both states superheated; intermediate stage: wet
reference, superheated outlet; exhaust: wet). Property queries take 1 step.

Since 0.3.0 the single-phase solve is a bracketed Newton iteration that
needs three or four Gibbs evaluations; it still charges the 40 steps of the
bisection it replaced, so step counts, `max_steps` outcomes and cached
campaign results are unchanged.

```python
for n in (120, 121):
    limited = prepared.evaluate(case["parameters"], max_steps=n)
    print(n, limited["status"], limited["steps"])
```

## 5. Request and result schemas

### 5.1 Candidate

```json
{"id": "c-001", "parameters": [300000.0, 2000000.0], "trace": false}
```

| Field | Type | Rules |
| --- | --- | --- |
| `id` | string | 1-128 bytes, unique within the batch |
| `parameters` | array of numbers | at most 64 values |
| `trace` | boolean | optional, default `false`; at most 16 traced candidates per batch |

In thermo-craft full records already carry every metric, so `trace: true`
adds no fields; it is accepted for engine compatibility, counts toward the
16-trace limit, and is rejected by the lean API.

### 5.2 Budget

| Field | Type | Range | Default | Effect |
| --- | --- | --- | --- | --- |
| `workers` | integer | 1-64 | 1 | upper bound on evaluation threads |
| `max_steps` | integer | 1-100,000,000 | 1,000,000 | logical steps per candidate |
| `wall_ms` | integer | 1-86,400,000 | none | batch deadline in milliseconds |
| `cancel_file` | string (path) | - | none | stop when this file exists |

In Python the budget is passed as keyword arguments; in Rust and the CLI as
a JSON object. Section 7 describes each limit.

### 5.3 Request (CLI)

```json
{
  "schema": "thermo-craft.request/0.1",
  "model": {"kind": "property"},
  "candidates": [{"id": "steam", "parameters": [1000000.0, 600.0]}],
  "budget": {"workers": 1}
}
```

`budget` is optional. `models/request.json` is a complete regenerative
example.

### 5.4 Result

```json
{
  "model_sha256": "7ddb3d78...",
  "records": [
    {"id": "steam", "status": "complete", "steps": 1, "score": 3108976.8117186152,
     "metrics": {"state": {"h_j_kg": 3108976.8117186152, "p_pa": 1000000.0, "quality": null,
                           "s_j_kg_k": 7222.372649758314, "t_k": 600.0, "v_m3_kg": 0.2712072554629714}},
     "detail": null}
  ],
  "schema": "thermo-craft.result/0.1",
  "version": "0.3.0"
}
```

Records are in candidate order. `score` is `null` unless `status` is
`complete`; `detail` is `null` for complete records and a message
otherwise; `metrics` is `null` in lean results and for failed candidates.
The schema tags stay at 0.1 because the JSON shape is unchanged since
0.1.0; `version` is the package version. The matrix API is not part of the
JSON schema.

### 5.5 Batch limits and request errors

A request that breaks a batch rule fails as a whole (Python `ValueError`,
Rust `Err`, CLI exit 1). No candidate is evaluated.

| Message | Cause |
| --- | --- |
| `invalid budget or batch size` | 0 or more than 4,096 candidates, or a budget value out of range |
| `invalid or duplicate candidate id, or parameter vector exceeds limit` | empty, longer than 128 bytes or repeated `id`, or more than 64 parameters |
| `at most 16 traced candidates per batch` | more than 16 candidates with `trace: true` |
| `scores mode accepts untraced candidates only` | a traced candidate passed to `scores` / `scores_json` |
| ``unknown field `...` `` / ``missing field `...` `` | candidate or budget shape error |
| `unsupported request schema` | CLI request `schema` is not `thermo-craft.request/0.1` |
| `request exceeds 16 MiB` | CLI input larger than 16 MiB |
| `matrix rows must be between 1 and 4096` | `score_matrix` with 0 or more than 4,096 rows |
| `parameter count is not a multiple of the row count` | Rust `score_matrix` with a ragged flat buffer |
| `parameter vector exceeds limit` | `score_matrix` rows longer than 64 |
| `ragged parameter rows` | Python `score_matrix` rows of different lengths |
| `score_matrix expects a 2-D array of parameter rows` | Python `score_matrix` given an array that is not 2-D |

```python
x = case["parameters"]
attempts = {
    "no candidates": lambda: prepared.batch([]),
    "duplicate id": lambda: prepared.batch([{"id": "a", "parameters": x}] * 2),
    "65 parameters": lambda: prepared.batch([{"id": "a", "parameters": [1.0] * 65}]),
    "17 traces": lambda: prepared.batch(
        [{"id": str(i), "parameters": x, "trace": True} for i in range(17)]),
    "lean trace": lambda: prepared.scores([{"id": "a", "parameters": x, "trace": True}]),
    "workers 0": lambda: prepared.batch([{"id": "a", "parameters": x}], workers=0),
    "unknown budget": lambda: prepared.batch([{"id": "a", "parameters": x}], bogus=1),
    "ragged rows": lambda: prepared.score_matrix([[1.0, 2.0], [1.0]]),
}
for name, call in attempts.items():
    try:
        call()
    except ValueError as error:
        print(f"{name}: {str(error)[:70]}")
```

## 6. Statuses and error messages

| Status | Meaning | Score | Typical action |
| --- | --- | --- | --- |
| `complete` | evaluated and passed every check | yes | use the score |
| `invalid` | the candidate does not fit the model (wrong length, out-of-range property query, nonfinite objective) | no | fix the input; never retry unchanged |
| `infeasible` | well formed, but the cycle violates a physical or design constraint | no | penalize in a search |
| `work_limit` | the candidate reached `max_steps` | no | raise `max_steps` |
| `cancelled` | the cancel file existed at a step check | no | remove the file and retry |
| `wall_limit` | the batch deadline passed at a step check | no | raise `wall_ms` or use smaller batches |

The first three are fixed for given inputs and are cached by the campaign;
the last three depend on the budget or the clock.

Candidate `detail` messages:

| Status | `detail` | Cause |
| --- | --- | --- |
| `invalid` | `pressure outside 1 kPa to 16 MPa` | property query or saturation pressure out of range |
| `invalid` | `temperature outside 273.16 to 1073.15 K` | property query temperature out of range |
| `invalid` | `P/T pair on saturation boundary requires quality` | temperature within 1e-7 K of saturation |
| `invalid` | `quality outside [0,1]` | quality form with quality out of range |
| `invalid` | `expected [pressure_pa, temperature_k] or [pressure_pa, quality, 0]` | property vector of another shape |
| `invalid` | `simple Rankine model has no candidate parameters` | non-empty vector for `extraction: false` |
| `invalid` | `expected low and high extraction pressure in Pa` | regenerative vector without exactly two values |
| `invalid` | `nonfinite objective` | the score was not finite |
| `infeasible` | `expected condenser < low extraction < high extraction < boiler` | extraction pressures out of order (also any NaN pressure) |
| `infeasible` | `turbine exhaust violates minimum quality` | exhaust quality below `min_exhaust_quality` |
| `infeasible` | `open-heater mix has no feasible extraction fraction` | a heater balance would need a bleed fraction outside [0, 1) |
| `infeasible` | `inverse state outside bounded IF97 envelope` | an expansion target outside 273.16-1073.15 K at its pressure |
| `infeasible` | `cycle fails power, heat or balance checks` | non-positive heat or work, or an energy residual above 1e-6 of heat input |
| `work_limit` | `candidate step budget reached` | `max_steps` reached |
| `cancelled` | `cancel file exists` | cancel file present |
| `wall_limit` | `batch deadline reached` | `wall_ms` elapsed |

The last three `infeasible` checks guard the numerics. The expansions of a
superheated inlet into this fixed topology stay inside the envelope and
give bleed fractions in range, so valid plants do not normally report them.

```python
checks = [
    ([2e6, 1e6], "high below low"),
    ([10e3, 2e6], "low below the condenser"),
    ([3e5, 2e6, 1.0], "three values"),
]
for parameters, label in checks:
    r = prepared.evaluate(parameters)
    print(f"{label:24} {r['status']:10} {r['steps']} {r['detail']}")
strict = Prepared(model | {"min_exhaust_quality": 0.9})
r = strict.evaluate(case["parameters"])
print(r["status"], r["steps"], r["detail"])
```

## 7. Budgets

**`workers`** is an upper bound on threads for one call. The engine runs
`min(workers, candidates, available CPUs)` threads, one of them the calling
thread; with one thread (or one candidate) it evaluates inline. Records
always come back in input order with the same values whatever the worker
count. The CPU count comes from `std::thread::available_parallelism()`,
which respects CPU affinity and cgroup quotas, and is read once per process.

**`max_steps`** limits each candidate separately (section 4.6). A candidate
that needs exactly `max_steps` steps completes; one more step would end it
with `work_limit` and `steps == max_steps`.

**`wall_ms`** sets one deadline for the whole call, measured from the start
of evaluation. Candidates check it at every logical step; those still
running or not yet started when it passes end as `wall_limit`. Which
candidates finish depends on the machine and load, so do not cache
`wall_limit` results.

**`cancel_file`** names a file whose existence stops evaluation at the next
step check. Create it from another process or thread to stop a long batch;
candidates that have not taken a step yet report `cancelled` with 0 steps.

Budgets with `wall_ms` or `cancel_file` are *monitored*: every step checks
the file system or the clock, which costs time. Leave them unset for the
fastest evaluation.

```python
import os
import tempfile

rows = [case["parameters"]] * 8
same = prepared.score_matrix(rows, workers=1) == prepared.score_matrix(rows, workers=4)
print("results independent of workers:", same)
with tempfile.TemporaryDirectory() as folder:
    flag = os.path.join(folder, "stop")
    open(flag, "w").close()
    print(prepared.evaluate(case["parameters"], cancel_file=flag)["status"])
    os.remove(flag)
    print(prepared.evaluate(case["parameters"], cancel_file=flag)["status"])
deadline = prepared.scores([{"id": str(i), "parameters": case["parameters"]} for i in range(64)],
                           wall_ms=60_000)
print({r["status"] for r in deadline["records"]})
```

## 8. Python API

```python
from thermo_craft import Prepared, load_example
from thermo_craft import campaign
```

### 8.1 `Prepared(model)`

Validates and prepares a model (`dict`). The model is encoded as JSON with
sorted keys and compact separators before it reaches native code, and the
SHA-256 of those bytes is reported as `model_sha256`. Raises `ValueError`
for any model error (section 4.3). A prepared model is immutable and can be
shared by threads; every evaluation method releases the GIL while native
code runs.

### 8.2 `Prepared.evaluate(parameters, *, trace=False, **budget)`

Evaluates one candidate with id `"one"` and returns its full record
(`dict`). Convenient for replays and interactive work.

### 8.3 `Prepared.batch(candidates, **budget)`

Evaluates a list of candidate dicts in one native call and returns the full
result envelope (`model_sha256`, `records`, `schema`, `version`).

### 8.4 `Prepared.scores(candidates, **budget)`

Same as `batch`, with `metrics: null` in every record and no metric
construction. Rejects traced candidates. Use it when you need IDs, details
and JSON-shaped records but not the metrics.

### 8.5 `Prepared.score_matrix(rows, **budget)`

Evaluates untraced candidates given as a list of equal-length parameter
lists or a 2-D NumPy array (any object with `tolist()` and `ndim == 2`),
without JSON. Returns three lists in row order: `scores` (float, NaN for
every row that is not complete), `statuses` (str) and `steps` (int).
Rows are numbered by position; there are no IDs and no duplicate check.
At most 4,096 rows of at most 64 values per call; rows may be empty
(dimension 0) for the simple cycle.

```python
import math

rows = [case["parameters"], [2e6, 1e6], [250e3, 1.8e6]]
scores, statuses, steps = prepared.score_matrix(rows, workers=2)
lean = prepared.scores([{"id": str(i), "parameters": r} for i, r in enumerate(rows)])
for score, status, used, record in zip(scores, statuses, steps, lean["records"]):
    assert (status, used) == (record["status"], record["steps"])
    assert score == record["score"] or (math.isnan(score) and record["score"] is None)
print(statuses, steps)
simple = Prepared(model | {"extraction": False})
print(simple.score_matrix([[], []]))
```

With NumPy:

```python
import numpy as np

grid = np.array([[lo, hi] for lo in (2e5, 3e5, 4e5) for hi in (1.5e6, 2e6, 2.5e6)])
scores, statuses, _ = prepared.score_matrix(grid)
best = int(np.nanargmin(scores))
print(grid[best].tolist(), -scores[best])
```

### 8.6 `load_example()`

Returns the packaged `{"model": ..., "parameters": ...}` fixture (the
regenerative example of section 4.2 and its validated grid winner).

### 8.7 `thermo_craft.campaign`

`campaign.run(database, scenarios, candidates, *, workers=1, chunk_size=16, **budget)`
evaluates every candidate against every scenario and returns rows in
scenario-major order. Each row is
`{"scenario", "key", "build_sha256", "model_sha256", "record"}`.

- `database`: path of an SQLite file, created if missing (WAL mode).
- `scenarios`: list of `{"id": str, "model": dict}`.
- `candidates`: list of candidate dicts (section 5.1).
- `chunk_size`: candidates per native call and per SQLite transaction
  (1-256).
- `budget`: passed to `Prepared.batch`; `cancel_file` is excluded from the
  cache identity.

Each record is keyed by the SHA-256 of the installed native extension, the
scenario id, the model, the candidate and the budget settings. `complete`,
`invalid` and `infeasible` records are cached in the `results` table and
reused by later runs with the same key; every evaluated record, including
`cancelled`, `wall_limit` and `work_limit`, is appended to the `attempts`
journal. A rerun therefore resumes interrupted work and replays finished
work without evaluating it again. Duplicate scenario or candidate IDs raise
`ValueError`. `campaign.digest(value)` is the hash used for keys.

```python
import sqlite3
from thermo_craft import campaign

scenarios = [{"id": "nominal", "model": model},
             {"id": "summer", "model": model | {"condenser_pa": 25e3}}]
pairs = [[2e5, 1.5e6], [3e5, 2e6], [4e5, 2.5e6]]
candidates = [{"id": f"pair-{k}", "parameters": p} for k, p in enumerate(pairs)]
with tempfile.TemporaryDirectory() as folder:
    database = os.path.join(folder, "campaign.sqlite")
    flag = os.path.join(folder, "stop")
    open(flag, "w").close()
    interrupted = campaign.run(database, scenarios, candidates, cancel_file=flag)
    print({row["record"]["status"] for row in interrupted})
    os.remove(flag)
    first = campaign.run(database, scenarios, candidates, workers=2)
    again = campaign.run(database, scenarios, candidates, workers=1)
    assert first == again
    with sqlite3.connect(database) as connection:
        cached = connection.execute("SELECT count(*) FROM results").fetchone()[0]
        attempts = connection.execute("SELECT count(*) FROM attempts").fetchone()[0]
    print(cached, attempts)
    for row in first:
        print(row["scenario"], row["record"]["id"], round(-row["record"]["score"], 5))
```

The same workflow is available as a script for JSON manifests:

```sh
python validation/run_campaign.py thermo_craft models/campaign.json campaign.sqlite
```

## 9. Application scenarios

The scripts in [`examples/python/`](../examples/python/README.md) answer
complete questions and save their output in `examples/python/outputs/`.
This section shows the core of each scenario.

### 9.1 Property tables

A saturation table from the quality form, and superheated enthalpies with a
finite-difference cp from `score_matrix` (the score of a property query is
h). Full script: `examples/python/property_tables.py`.

```python
table = properties.batch([{"id": f"{p:g}-{x}", "parameters": [p, x, 0.0]}
                          for p in (1e4, 1e5, 1e6) for x in (0.0, 1.0)])["records"]
for f, g in zip(table[0::2], table[1::2]):
    f, g = f["metrics"]["state"], g["metrics"]["state"]
    print(f"p {f['p_pa']:9.0f} Pa  T_sat {f['t_k']:8.3f} K  h_fg {(g['h_j_kg'] - f['h_j_kg']) / 1e3:7.1f} kJ/kg")
h, _, _ = properties.score_matrix([[1e6, 699.5], [1e6, 700.5]])
print("cp at 1 MPa, 700 K:", round((h[1] - h[0]) / 1e3, 4), "kJ/(kg K)")
```

### 9.2 The simple cycle

Set `extraction` to `false` and pass an empty vector.

```python
simple = Prepared(model | {"extraction": False})
r = simple.evaluate([])
print(r["status"], r["steps"], round(r["metrics"]["efficiency"], 5),
      round(r["metrics"]["exhaust_quality"], 4), len(r["metrics"]["states"]))
```

### 9.3 Extraction-pressure study

Scan both pressures, find the infeasible region and the best design, and
compare with the simple cycle. Full script with a text map:
`examples/python/extraction_map.py`.

```python
from collections import Counter

low = [50e3 * (30 ** (k / 11)) for k in range(12)]
high = [0.5e6 * (12 ** (k / 11)) for k in range(12)]
rows = [[a, b] for a in low for b in high]
scores, statuses, _ = prepared.score_matrix(rows, workers=2)
print(Counter(statuses))
k = min(range(len(rows)), key=lambda i: scores[i] if statuses[i] == "complete" else 1.0)
best = prepared.evaluate(rows[k])["metrics"]
print([round(v) for v in rows[k]], round(best["efficiency"], 5),
      round(best["efficiency"] - r["metrics"]["efficiency"], 5))
```

### 9.4 Design and operating scenarios

Compare boiler conditions, or a plant across seasons, by preparing one
model per scenario. `examples/python/cycle_comparison.py` compares simple
and regenerative cycles over boiler pressure and inlet temperature.

```python
for boiler, inlet in ((4e6, 723.15), (8e6, 813.15), (12e6, 873.15)):
    scenario = model | {"boiler_pa": boiler, "inlet_k": inlet}
    eta = -Prepared(scenario).score_matrix([[3e5, 2e6]])[0][0]
    eta_simple = Prepared(scenario | {"extraction": False}).evaluate([])["metrics"]["efficiency"]
    print(f"{boiler / 1e6:4.0f} MPa {inlet:7.2f} K  regenerative {eta:.4f}  simple {eta_simple:.4f}")
```

### 9.5 Sensitivity

Perturb one model input at a time and re-prepare. Full script with all
inputs and a condenser-pressure study: `examples/python/sensitivity.py`.

```python
def efficiency(m, parameters=case["parameters"]):
    s, st, _ = Prepared(m).score_matrix([parameters])
    return -s[0] if st[0] == "complete" else math.nan

for key in ("turbine_efficiency", "inlet_k", "condenser_pa"):
    step = 1e-3 * model[key]
    slope = (efficiency(model | {key: model[key] + step})
             - efficiency(model | {key: model[key] - step})) / (2 * step)
    print(f"{key:20} d(eta)/dx = {slope:.4e}  elasticity {slope * model[key] / efficiency(model):.3f}")
```

### 9.6 Constraint effects

The exhaust-quality limit is the active constraint for wet, high-pressure
designs. Count how much of a grid it removes:

```python
for limit in (0.75, 0.88, 0.895):
    _, st, _ = Prepared(model | {"min_exhaust_quality": limit}).score_matrix(rows)
    print(limit, Counter(st))
```

## 10. Optimization

For an optimizer, the objective is the score of a `complete` record, and
every other status needs a penalty larger than any feasible score. Cycle
scores are minus efficiency, so any value above 0 works; a penalty that
grows with the violation (for example how far the low pressure exceeds the
high one) helps an optimizer back into the feasible region. Search in
log-pressure space: the optimum is broad and spans decades.

Use `score_matrix` for objectives: a population-based optimizer can score a
whole generation in one call (and use native workers), and a scalar
objective can score a single row. Replay the winner with `evaluate` to
inspect it.

```python
def penalized(rows, scores, statuses):
    return [s if st == "complete" else 1.0 + max(0.0, math.log10(r[0] / r[1]))
            for r, s, st in zip(rows, scores, statuses)]

def population(log_rows):
    rows = (10.0 ** np.asarray(log_rows)).tolist()
    scores, statuses, _ = prepared.score_matrix(rows, workers=2)
    return penalized(rows, scores, statuses)

print([round(v, 4) for v in population([[5.5, 6.3], [6.3, 5.5]])])
```

SciPy's `differential_evolution` in vectorized mode passes the population
as an array of shape (dimensions, population):

```python
from scipy.optimize import differential_evolution

bounds = [(math.log10(20e3), math.log10(3e6)), (math.log10(0.2e6), math.log10(7.5e6))]
result = differential_evolution(lambda xt: np.array(population(xt.T)), bounds, vectorized=True,
                                updating="deferred", popsize=10, maxiter=30, seed=1,
                                polish=False, tol=1e-12)
print([round(10 ** v) for v in result.x], round(-result.fun, 6))
```

fcmaes optimizers with an ask/tell interface score each population with one
call:

```python
from loguru import logger
from scipy.optimize import Bounds
from fcmaes import cmaes

logger.remove()
es = cmaes.Cmaes(Bounds(*zip(*bounds)), [5.5, 6.3], input_sigma=0.3, popsize=12,
                 max_evaluations=480, rg=np.random.default_rng(2),
                 randn=np.random.RandomState(2).randn)  # seeds the normal samples too
while True:
    xs = es.ask()
    if es.tell(np.array(population(xs))) != 0:
        break
best = es.result()
print([round(10 ** v) for v in best.x], round(-best.fun, 6))
```

Standard minimizers such as `fcmaes.bitecpp.minimize`, `fcmaes.de.minimize`
or `scipy.optimize.minimize` call a scalar objective:

```python
from fcmaes import bitecpp

def objective(x):
    return population([x])[0]

result = bitecpp.minimize(objective, Bounds(*zip(*bounds)), max_evaluations=400,
                          rg=np.random.default_rng(3))
print(result.nfev, [round(10 ** v) for v in result.x], round(-result.fun, 6))
```

The optimization examples cover more: SciPy with a Nelder-Mead polish
(`optimize_scipy.py`), fcmaes CMA-ES and DE ask/tell with native workers
(`optimize_fcmaes_population.py`), BiteOpt and DE minimizers with graded
penalties and a strict exhaust limit (`optimize_fcmaes_minimize.py`), and a
worst-case robust design across operating scenarios (`robust_design.py`).

## 11. Rust API

The library crate is `thermo_craft`.

```rust
pub struct Prepared { /* private */ }
impl Prepared {
    pub fn new(model: &str) -> Result<Self, String>;
    pub fn model_sha256(&self) -> &str;
    pub fn evaluate_json(&self, candidates: &str, budget: &str) -> Result<String, String>;
    pub fn scores_json(&self, candidates: &str, budget: &str) -> Result<String, String>;
    pub fn score_matrix(&self, rows: usize, parameters: &[f64], budget: &str)
        -> Result<Vec<MatrixScore>, String>;
}
#[derive(Clone, Debug, PartialEq)]
pub struct MatrixScore { pub status: &'static str, pub steps: u64, pub score: Option<f64> }
pub fn run(request: &str) -> Result<serde_json::Value, String>;   // CLI request
pub fn capabilities() -> serde_json::Value;                       // `describe`
```

- `candidates` is a JSON array of candidates and `budget` a JSON object
  (`"{}"` for defaults); both return the result envelope of section 5.4.
- `score_matrix` takes `rows` candidates stored row-major in `parameters`;
  each row has `parameters.len() / rows` values (0 is allowed). It applies
  the same budget parsing, limits, worker dispatch, deadlines, cancellation
  and failure classification as `scores_json`, and its status, steps and
  score equal the JSON results bit for bit. `score` is `Some` only for
  `"complete"`.
- `Candidate`, `Work`, `Failure`, `invalid` and `infeasible` are public for
  the domain code inside the crate; applications do not need them.

`examples/matrix_scan.rs` is a complete program:

```sh
cargo run --release --locked --example matrix_scan -- models/example.json
```

```text
model sha256 c365d173c54842e093a18c9108be103b21c11d7b4fa943fff8a45eb32420001e
1600 candidates, statuses {"complete": 1476, "infeasible": 124}
best low 371.6 kPa, high 2.0311 MPa, efficiency 0.384123, steps 161
```

## 12. Command-line interface

```text
thermo-craft describe
thermo-craft run FILE      # or `run -` to read standard input
```

`describe` prints the capabilities. `run` reads one request (at most
16 MiB) and prints one line of JSON. Exit status 0 means every record is
complete, 2 means the request was valid but at least one record is not
complete, and 1 means the request was rejected; a rejection prints
`{"detail": ..., "status": "rejected"}` on standard error.

```sh
target/release/thermo-craft describe
```

```text
{"batch":true,"models":["bounded_if97_regions_1_2_4","closed_rankine","two_open_heater_rankine"],"schema":"thermo-craft.capabilities/0.1","version":"0.3.0","worker_limit":64}
```

```sh
echo '{"schema":"thermo-craft.request/0.1","model":{"kind":"property"},"candidates":[{"id":"steam","parameters":[1000000.0,600.0]}]}' | target/release/thermo-craft run -; echo "exit $?"
```

```text
{"model_sha256":"7ddb3d78443097ec230bc8437cf61ae65e1e816c5e8acb5420495f78d0e669da","records":[{"detail":null,"id":"steam","metrics":{"state":{"h_j_kg":3108976.8117186152,"p_pa":1000000.0,"quality":null,"s_j_kg_k":7222.372649758314,"t_k":600.0,"v_m3_kg":0.2712072554629714}},"score":3108976.8117186152,"status":"complete","steps":1}],"schema":"thermo-craft.result/0.1","version":"0.3.0"}
exit 0
```

A request with an unsuccessful record exits with 2:

```sh
echo '{"schema":"thermo-craft.request/0.1","model":{"kind":"property"},"candidates":[{"id":"ok","parameters":[1e5,400.0]},{"id":"hot","parameters":[1e5,2000.0]}]}' | target/release/thermo-craft run - | python -c "import json,sys; [print(r['id'], r['status'], r['detail']) for r in json.load(sys.stdin)['records']]"; echo "exit ${PIPESTATUS[1]}"
```

```text
ok complete None
hot invalid temperature outside 273.16 to 1073.15 K
exit 2
```

A rejected request exits with 1:

```sh
echo '{"schema":"thermo-craft.request/0.2","model":{"kind":"property"},"candidates":[]}' | target/release/thermo-craft run -; echo "exit $?"
```

```text
{"detail":"unsupported request schema","status":"rejected"}
exit 1
```

The packaged regenerative request:

```sh
target/release/thermo-craft run models/request.json | python -c "import json,sys; r=json.load(sys.stdin)['records'][0]; print(r['id'], r['status'], r['steps'], r['score'], r['metrics']['exhaust_quality'])"
```

```text
example complete 121 -0.38408189269858095 0.8925963835552144
```

The CLI result goes through a `serde_json::Value`, so its keys are sorted;
the library and Python results list record fields in the order `id`,
`status`, `steps`, `score`, `metrics`, `detail`. Both are the same JSON
object.

## 13. Reproducibility and provenance

- **Model identity.** `model_sha256` hashes the exact model bytes. Python
  encodes models with sorted keys and compact separators, so equal dicts
  give equal hashes. Bytes that differ (key order, spacing, `8e6` versus
  `8000000.0`) give different hashes in Rust and the CLI.
- **Determinism.** For a given build, model and candidate, status, steps,
  score and metrics are deterministic, independent of worker count, API
  style and batch composition. Only `wall_limit` and `cancelled` outcomes
  depend on timing.
- **Across releases.** The 0.3.0 numerical changes (Newton inverse, power
  tables, summation order) move values only in their last bits: every
  0.3.0 round was checked against its predecessor with relative tolerance
  5e-10 (absolute 5e-7 for quantities in J/kg and 1e-10 otherwise),
  record order, statuses, details and steps unchanged, and the
  independent IF97 and cycle validation passed. Store the package version
  with results that must be reproduced exactly.
- **Campaign cache.** Cache keys include the SHA-256 of the installed
  native extension, so a new build never reuses old cached results.
- **Validation.** `python validation/validate.py target/release/thermo-craft`
  checks official IF97 points, saturation consistency, pump and turbine
  balances, the regenerative winner and held-out stress cases;
  `evidence/validation.json` holds the last run.

```python
a = Prepared({"kind": "property"}).batch([{"id": "a", "parameters": [1e6, 600.0]}])
b = Prepared(dict(kind="property")).batch([{"id": "a", "parameters": [1e6, 600.0]}])
print(a["model_sha256"] == b["model_sha256"], a["model_sha256"][:16])
```

## 14. Performance tips

Measured on a 2-vCPU Intel Xeon host with Rust 1.97 and CPython 3.12; see
the Performance section of the [architecture guide](architecture.md) for
the full tables and evidence files.

- **Use `score_matrix` in optimization loops.** It skips JSON in both
  directions. Natively a regenerative candidate costs about 1.7 us; a full
  record about 3.2 us, of which about half is metric construction and JSON
  writing. From Python on one CPU, a one-row call cost 4.7 us with
  `score_matrix`, 10 us with `scores` and 27 us with `evaluate`.
- **Batch many candidates per call.** Natively the fixed cost of a call is
  well under a microsecond, but each Python call adds a few microseconds,
  and full results must be decoded from JSON in Python: 96 full records
  took 1.9 ms from Python against 0.19 ms for 96 matrix rows.
- **Request full records only for inspection.** Replay winners with
  `evaluate`.
- **Workers help large batches.** Thread start-up costs tens of
  microseconds, so a 96-candidate batch gains little from a second worker,
  while a 1,024-row matrix call ran 1.7x faster with two workers on two
  vCPUs. More threads than CPUs are never started.
- **Leave `wall_ms` and `cancel_file` unset** when you do not need them;
  monitored budgets check the clock or the file system at every step.
- **Prepare once.** `Prepared(model)` costs about 1 us natively and about
  6 us from Python; keep one prepared model per scenario instead of
  re-preparing inside a loop.

## 15. Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `ValueError` from `Prepared(...)` | A model error (section 4.3); the message names the problem. |
| `ValueError: Out of range float values are not JSON compliant` | NaN or infinity in a model, candidate or budget passed to `batch`, `scores` or `evaluate`. `score_matrix` accepts NaN and reports the row as `infeasible` (cycle) or `invalid` (property). |
| Every regenerative candidate is `infeasible` with the ordering message | Pressures in kPa or MPa instead of Pa, or swapped low and high values. |
| Many `infeasible` records with `turbine exhaust violates minimum quality` | The exhaust is too wet for `min_exhaust_quality`; raise the inlet temperature, lower the boiler pressure, or relax the limit. |
| `invalid` with `P/T pair on saturation boundary requires quality` | The temperature equals the saturation temperature; use `[p, quality, 0]`. |
| `work_limit` | `max_steps` is below the candidate's step count (section 4.6). |
| `cancelled` with 0 steps | The cancel file existed before evaluation; delete it. |
| `score_matrix` raises for an empty list or more than 4,096 rows | Split populations into chunks of at most 4,096 rows. |
| The wheel does not install | Its tag is Linux x86-64, CPython 3.10+ ABI; build from source (section 2.2) elsewhere. |
| A campaign re-evaluates everything | The native extension changed (new build), or the model, scenario ID, candidate or budget settings differ. |
| CLI output has keys in a different order than Python | Both are the same JSON object (section 12). |

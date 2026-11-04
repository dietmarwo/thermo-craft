# thermo-craft examples

Runnable Python examples for the bounded IF97 property model and the fixed
Rankine cycle. Each script is self-contained and finishes in about a second
on a 2-vCPU host. The saved output of `<name>.py` is in
[`outputs/<name>.txt`](outputs/). Regenerate all outputs from the project
root with an installed wheel:

```sh
python validation/run_examples.py
```

The application examples need only `thermo_craft`. The optimization examples
also need NumPy and SciPy, and the fcmaes examples need `fcmaes` 2.1.0 (which
installs `loguru`).

## Application examples

| Script | Question it answers | APIs used |
| --- | --- | --- |
| [`property_tables.py`](property_tables.py) | Saturation and superheat tables, cp by finite differences, official IF97 verification points and how out-of-range queries are reported | `batch`, `score_matrix` on the `property` kind |
| [`extraction_map.py`](extraction_map.py) | How efficiency depends on the two extraction pressures; where the infeasible region is; what the best grid design looks like in detail | `score_matrix` with two workers, `evaluate` replay |
| [`cycle_comparison.py`](cycle_comparison.py) | Simple versus regenerative cycle over boiler pressure and inlet temperature, and where the exhaust-quality limit binds | simple (`extraction: false`) and regenerative models, `score_matrix` |
| [`sensitivity.py`](sensitivity.py) | Derivatives and elasticities of efficiency with respect to each model input; cost of keeping a fixed extraction pair as the condenser pressure changes | re-prepared models, `score_matrix` |

## Optimization examples

| Script | Optimizer | Evaluation pattern |
| --- | --- | --- |
| [`optimize_scipy.py`](optimize_scipy.py) | SciPy `differential_evolution` (vectorized) and a Nelder-Mead polish | whole population per `score_matrix` call; single-row calls for the polish |
| [`optimize_fcmaes_population.py`](optimize_fcmaes_population.py) | fcmaes `cmaes.Cmaes` and `de.DE` ask/tell | whole population per `score_matrix` call with `workers=2` |
| [`optimize_fcmaes_minimize.py`](optimize_fcmaes_minimize.py) | fcmaes `bitecpp.minimize` (BiteOpt) and `de.minimize` | scalar objective with graded and flat failure penalties, nominal and strict exhaust limits |
| [`robust_design.py`](robust_design.py) | fcmaes `cmaes.Cmaes` ask/tell on a worst-case objective | one `score_matrix` call per scenario per generation |

All optimization examples search in log10 pressure space, map every status
other than `complete` to a penalty above any feasible score, and replay or
re-check the winner.

## Rust example

[`../matrix_scan.rs`](../matrix_scan.rs) scans a 40 x 40 pressure grid with
`Prepared::score_matrix`. Its output is in
[`../outputs/matrix_scan.txt`](../outputs/matrix_scan.txt):

```sh
cargo run --release --locked --example matrix_scan -- models/example.json
```

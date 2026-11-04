# thermo-craft performance implementation log

3 November 2026. Version 0.2.0, based on the prior 0.1.0 delivery
at `e6bded92642c`. The ZIP contains the updated source, runnable
examples, an ordered patch series, [tutorial](docs/tutorial.md),
[architecture](docs/architecture.md), raw evidence and build artifacts.
The [earlier implementation record](docs/implementation-0.1.0.md)
documents the original research scope and remaining external work.

## Ten incremental changes

Each row compares the indicated stage with its immediate predecessor.
Times are median milliseconds per prepared call. A ratio below 1.00×
means the new median was slower for that measurement. Small differences
vary with thread scheduling, code layout and host noise.

| Round | Commit | Change | Case | Before ms | After ms | Before / after |
| ---: | --- | --- | --- | ---: | ---: | ---: |
| 1 | `005b07b` | Evaluate singleton and one-worker batches on the calling thread, removing worker startup and join. | `one` | 0.109 | 0.061 | 1.79× |
| 2 | `8bab3d5` | Replace worker-local row collections and final sorting with one result slot per candidate index. Keep dynamic work assignment. | `parallel` | 2.901 | 2.795 | 1.04× |
| 3 | `9ff4cb4` | Validate unique candidate IDs through a pre-sized hash set. The large invalid batch isolates ID checks and response overhead from most domain computation. | `invalid` | 2.336 | 2.132 | 1.10× |
| 4 | `bda81e7` | Serialize a typed prepared batch directly and keep the public CLI result adapter. | `trace` | 0.721 | 0.624 | 1.16× |
| 5 | `6c1bec7` | Borrow candidate IDs until the batch is serialized, eliminating output-side string clones. | `invalid` | 1.553 | 1.521 | 1.02× |
| 6 | `2ed5e69` | Inline the unmonitored work counter. Keep cancellation, deadline and exhausted-budget checks on the guarded path. | `domain` | 3.550 | 3.766 | 0.94× |
| 7 | `f9ed4b3` | Add Rust and Python score-only entry points, preserving status, step counts, score and record order while skipping diagnostic construction. This row compares the earlier full path with the new lean path. | `lean-serial` | 5.389 | 4.448 | 1.21× |
| 8 | `9deb8c5` | Reuse the fixed pressure powers during inverse temperature search. | `domain` | 3.448 | 3.210 | 1.07× |
| 9 | `9aadd24` | Reuse ideal vapor temperature powers across Gibbs derivative terms. | `domain` | 3.295 | 3.225 | 1.02× |
| 10 | `58c6de6` | Evaluate scalar enthalpy or entropy during bisection and reconstruct a complete state at the final temperature. | `domain` | 3.162 | 3.025 | 1.05× |

Each stage passed locked Rust release tests and paired output checks
for the supplied workloads. The result comparisons
ignore the package-version string and require matching record order,
status, detail, steps, provenance and numeric values within tolerance.
Lean comparisons also normalize metrics to null. The benchmark commit
precedes the ten rounds. Documentation and version changes follow them.

## Cumulative native results

| Workload | 0.1.0 ms | Final ms | Before / after |
| --- | ---: | ---: | ---: |
| Single prepared evaluation | 0.112 | 0.045 | 2.50× |
| 96 full records, one worker | 6.499 | 4.688 | 1.39× |
| 96 full records, four workers | 2.713 | 1.802 | 1.51× |
| 12 traced records | 0.909 | 0.582 | 1.56× |
| 1,024 invalid candidates | 2.734 | 1.513 | 1.81× |
| 48 domain cases | 4.341 | 2.877 | 1.51× |
| 48 secondary domain cases | 0.254 | 0.084 | 3.04× |
| 96 lean scores | 6.221 | 3.652 | 1.70× |
| 48 lean domain scores | 4.091 | 2.399 | 1.71× |
| 48 lean secondary scores | 0.274 | 0.039 | 7.00× |

The lean API was introduced in 0.2.0. The baseline uses full
records for the three lean rows. The paired comparisons alternate process order,
exclude startup and model preparation, warm up each prepared evaluator,
and measure JSON decode, evaluation, checks and JSON encoding. They
use five observations per side on an AMD EPYC 9V74 with Rust 1.88.0,
using logical CPUs 0–3. These are fixed test workloads, with four
workers only in the parallel row. Ratios from individual stages do
not multiply into the cumulative ratio because the timings were rerun.

The supplemental workloads use a regenerative cycle at 950 K and a vapor property query. Reused ideal powers can alter the last bits of thermodynamic values. Official property points, cycle balance, pressure bounds and held-out cases passed. The model still covers the declared IF97 regions and cycle topology.

## Installed Python optimization

Seven runs per configuration used the same seed, bounds, starting point,
optimizer budget and final traced replay. CPython 3.12 and SciPy 1.17.0
ran on one logical CPU. Times include preparation, objective evaluation
and traced winner replay, excluding Python imports and wheel compilation.
The total median is calculated per run, separately from the column medians.

| Configuration | Prepare ms | Search ms | Replay ms | Total ms | Baseline / total |
| --- | ---: | ---: | ---: | ---: | ---: |
| v0.1.0-full | 0.076 | 15.243 | 0.169 | 15.510 | 1.00× |
| v0.2.0-full | 0.074 | 12.211 | 0.091 | 12.377 | 1.25× |
| v0.2.0-scores | 0.074 | 10.675 | 0.105 | 10.855 | 1.43× |

The run made **48** objective calls and classified
**0** failures. The selected vector was
`[362432.0581474683, 2033861.965363634]` with replay score **-0.384127048529**.
All configurations agreed on evaluation and failure counts, final
parameters and full replay score within the recorded tolerance.

## Release checks

- Rust formatting, Clippy with Python enabled and warnings denied,
  release tests, CLI request and native sweep passed.
- The independent domain validation passed against the release CLI.
- The wheel built from the extracted source distribution and installed
  into a fresh CPython 3.12 environment. Its ABI is CPython 3.10+ and
  its bundled target is Linux x86-64.
- The installed lean and full paths agreed on results, including mixed
  valid/invalid candidates, worker count, fixed work limits and
  cancellation. The tutorial's 4 Python blocks ran.
- SQLite cancellation/resume retained 21
  attempts and recovered 12 completed rows.
  Two full manifest runs against the same database produced identical output.
- The Rust crate archive passed Cargo package verification.

Run the packaged `validation/performance_pair.py` with saved native
benchmark binaries to reproduce comparisons. To reconstruct the ten
rounds in Git, apply `patches/*.patch` in filename order to the source
from the 0.1.0 ZIP. A baseline may first be committed locally. The patch
series includes the benchmark and release documentation commits around
the ten implementation commits.

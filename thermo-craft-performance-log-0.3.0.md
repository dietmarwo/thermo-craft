# thermo-craft performance implementation log

4 November 2026. Version 0.3.0, based on the 0.2.0 delivery imported at
`6c2df26`. The ZIP contains the updated source, runnable examples, the
patch series `patches/0.3.0/`, the new [user manual](docs/user-manual.md),
the updated [architecture guide](docs/architecture.md) with measured
performance, the [tutorial](docs/tutorial.md), raw evidence and build
artifacts. The [0.2.0 log](thermo-craft-performance-log-0.2.0.md) is kept
unchanged.

All measurements in this log come from one host: **2 vCPUs, Intel(R)
Xeon(R) Processor @ 2.10GHz (KVM guest), Rust 1.97.0, CPython 3.12.3**,
shared with other jobs; every build, test and timing ran under an exclusive
CPU lock. The 0.2.0 log's numbers came from another host (AMD EPYC 9V74,
4 CPUs, Rust 1.88) and are not compared with these.

## Ten incremental changes

Each row compares the round's benchmark binary with the previous kept
round's binary using `validation/performance_pair.py --samples 11`.
Times are median milliseconds per prepared call. "Paired" is the median of
the 11 adjacent before/after ratios. Before measuring each round, its
workload and expected effect were written to
`evidence/performance-0.3.0/plan.md`.

The host speed drifts between regimes lasting seconds (30 back-to-back runs
of one binary ranged from 2.1 to 4.3 ms), and that drift split the medians
in the round-1 run. From round 2 on, every round also ran a 41-sample
confirmation, whatever the official result, and was kept only if the
official ratio, the official paired median and the confirmation's paired
median were all at least 1.03. This rule, stricter than the 1.03 ratio of
medians alone, was fixed in the plan before any round-2 timing.

| Round | Commit | Change | Case | Before ms | After ms | Before / after | Paired | 41-sample paired |
| ---: | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | `1492f8e` | Add the typed score-matrix API: `Prepared::score_matrix`, `MatrixScore`, Python `score_matrix`, benchmark and pairing modes. See the note below. | `serial`, lean before, matrix after | 4.207 | 2.932 | 1.43x | - | 1.01x |
| 2 | `fa08179` | Solve fixed-pressure inverse states with a safeguarded Newton iteration on cp or cp/T, still charging the 40 logical steps of the bisection it replaced. | `domain` | 3.281 | 1.098 | 2.99x | 2.98x | 3.03x |
| 3 | `9645944` | Return typed metrics instead of `serde_json::Value` trees; JSON stays byte-identical. | `serial` | 1.482 | 0.805 | 1.84x | 1.61x | 1.66x |
| 4 | `d21e17a` | Take the saturation-side bracket value from the saturation pair (bit-identical) instead of re-evaluating it. | matrix `domain` | 0.556 | 0.491 | 1.13x | 1.14x | 1.13x |
| 5 | `246084c` | Build IF97 power tables from eight short multiplication chains instead of one long one. | matrix `serial` | 0.674 | 0.389 | 1.73x | 1.79x | 1.68x |
| 6 | `3d2816c` | Group Gibbs terms by pressure exponent at compile time and factor the pressure powers out of the sums. | matrix `serial` | 0.273 | 0.256 | 1.07x | 1.11x | 1.11x |
| 7 | `a338e59` | Precompute term factors n*J, n*J*(J-1) and power-table indices at compile time (bit-identical). | matrix `domain` | 0.172 | 0.134 | 1.28x | 1.33x | 1.36x |
| 8 | `0d69765` | Run one worker on the calling thread and start at most as many threads as CPUs. | `parallel` | 0.604 | 0.514 | 1.18x | 1.11x | 1.26x |
| 9 | `9db4b05` | Skip the 1073.15 K bracket evaluation when a precomputed floor proves a vapor target is inside the bracket. | matrix `domain` | 0.129 | 0.111 | 1.16x | 1.14x | 1.12x |
| 10 | `5fb2bbf` | Write result JSON directly with static keys; serde_json still formats numbers and strings (byte-identical). | `serial` | 0.443 | 0.407 | 1.09x | 1.15x | 1.17x |

**Round 1.** The brief required the matrix API as round 1, timed as lean
`scores_json` against matrix on `serial`. The official run reported 1.43x,
but its samples are bimodal: the host switched between a 2.8 ms and a
4.2 ms regime during the run, and the split fell between the two medians.
The 41-sample rerun gives a ratio of medians of 1.05x and a paired median
of 1.01x. The real native gain on this domain-bound workload is about 1%,
below the 1.03x bar, as the pre-round profile predicted (candidate JSON is
about 2% of a 0.2.0 serial batch). The round is kept only because it is
required. Where the JSON boundary matters, the same binaries show the API's
value: `domain2` 2.17x and `invalid` 46.5x (lean before, matrix after,
`round01-supplement-*.json`), and in Python the matrix path is the fastest
(see below). Counted strictly, nine rounds met the bar.

Every kept round passed `cargo fmt --check`, Clippy with the `python`
feature and warnings denied, `cargo test --release --locked`, and the
paired output check (`equal()` with its existing tolerances: record order,
status, detail, steps, provenance, scores and metrics) on all seven
workloads in full, lean and matrix modes. Rounds 3, 4, 7, 8 and 10 produced
byte-identical probe output. Rounds 2, 5, 6 and 9 change values in their
last bits, so `validation/validate.py` was run against that round's release
CLI and passed (`roundNN-validation.json`). Logical step counts are
unchanged in every round. New behavior has unit tests: matrix equivalence
and error cases, the Newton inverse against a bisection reference and the
40-step charge, bit equality of reused bracket values, blocked power
tables, grouped and precomputed Gibbs terms, the hot-end floors, capped
dispatch, typed metric order and direct JSON byte equality (15 tests).
The JSON files are in `evidence/performance-0.3.0/`.

## Rejected attempts

| Attempt | Change | Case | Before ms | After ms | Before / after | Paired | 41-sample paired | Outcome |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| First round 10 | Carry both pressure-power tables, ln(p) and ln(p/1 MPa) with each saturation pair for its inverses (bit-identical). | matrix `serial` | 0.210 | 0.178 | 1.18x | 1.19x | 1.006x | Rejected and reverted: the confirmation's paired median was below 1.03 |

Its JSON files are in `evidence/performance-0.3.0/rejected/`.

## Cumulative native results

The 0.2.0 baseline benchmark binary (built from `6c2df26`) against the
round-10 binary, `--samples 11`, alternating process order, excluding
startup and model preparation. The `parallel` workload keeps its four
requested workers on this 2-vCPU host: 0.2.0 starts four threads, 0.3.0
runs two. The two matrix rows use 0.2.0 lean scores as the baseline,
because 0.2.0 has no matrix API. Evidence:
`evidence/performance-0.3.0/cumulative/`.

| Workload | 0.2.0 ms | 0.3.0 ms | Before / after | Paired |
| --- | ---: | ---: | ---: | ---: |
| Single prepared evaluation (`one`) | 0.0473 | 0.0063 | 7.52x | 8.04x |
| 96 full records, one worker (`serial`) | 3.5064 | 0.3369 | 10.41x | 10.20x |
| 96 full records, four requested workers (`parallel`) | 2.6053 | 0.3588 | 7.26x | 7.37x |
| 12 traced records (`trace`) | 0.4143 | 0.0445 | 9.30x | 9.92x |
| 1,024 invalid candidates (`invalid`) | 1.4739 | 1.4503 | 1.02x | 1.02x |
| 48 domain cases at 950 K (`domain`) | 2.4193 | 0.2184 | 11.08x | 10.87x |
| 48 property queries (`domain2`) | 0.1131 | 0.0313 | 3.62x | 2.74x |
| 96 lean scores | 3.2052 | 0.2149 | 14.91x | 13.73x |
| 48 lean domain scores | 1.9426 | 0.1408 | 13.80x | 13.58x |
| 48 lean property scores | 0.0517 | 0.0328 | 1.58x | 1.50x |
| 96 matrix rows (baseline 0.2.0 lean) | 2.9197 | 0.2026 | 14.41x | 14.61x |
| 48 matrix domain rows (baseline 0.2.0 lean) | 1.8976 | 0.1333 | 14.23x | 14.52x |

The `invalid` workload is bound by JSON number parsing (64,512 numbers),
which no round changed. The property rows take about 30 us per call, where
process-level noise is large: 41-sample confirmations give 2.50x (full) and
1.44x (lean), and 0.0236 ms lean against 0.0314 ms full in 0.3.0
(`supplement-*-domain2-confirm41.json`). Supplementary matrix rows against
0.2.0 lean: `domain2` 4.70x, `invalid` 36.8x. Ratios from individual rounds
do not multiply into the cumulative ratio because the timings were rerun.

The time breakdown (`evidence/performance-0.3.0/breakdown.json`, from
`examples/breakdown.rs`) puts a regenerative candidate at about 1.65 us of
domain evaluation, 0.25 us of lean JSON and 1.3 us more for a full record;
the architecture guide has the tables.

## Installed Python optimization

Seven runs per configuration, interleaved, of
`validation/optimize_performance.py` with the same seed, bounds, starting
point, optimizer budget and final traced replay, on CPU 0
(`taskset -c 0`) with CPython 3.12.3, NumPy 2.3.5 and SciPy 1.17.0. The
0.3.0 wheel was built with maturin 1.9.6 from the extracted 0.3.0 sdist; its
native extension is byte-identical to the released wheel's. The 0.2.0
wheel is the one delivered in 0.2.0's `packages/`. Each wheel was installed
into its own fresh venv. Times include preparation, objective evaluation
and traced winner replay, excluding Python imports. The total median is
calculated per run, separately from the column medians
(`evidence/performance-0.3.0/python-optimization.json`).

| Configuration | Prepare ms | Search ms | Replay ms | Total ms | 0.2.0 full / total |
| --- | ---: | ---: | ---: | ---: | ---: |
| v0.2.0-full | 0.091 | 8.662 | 0.099 | 8.863 | 1.00x |
| v0.2.0-scores | 0.083 | 6.699 | 0.135 | 6.911 | 1.28x |
| v0.3.0-full | 0.084 | 6.642 | 0.049 | 6.768 | 1.31x |
| v0.3.0-scores | 0.093 | 5.790 | 0.067 | 5.942 | 1.49x |
| v0.3.0-matrix | 0.094 | 4.637 | 0.091 | 4.836 | 1.83x |

Every run made **48** objective calls and classified **0** failures. All
configurations selected `[362432.0581474683, 2033861.965363634]`. The
replay score is **-0.38412704852860363** with 0.2.0 and
**-0.38412704852854795** with 0.3.0, a relative difference of 1.4e-13,
inside the recorded tolerance. With 48 evaluations, SciPy's own work is
most of the remaining search time; Python per-call costs
(`python-call-costs-*.json`) show the larger API differences: one candidate
costs 27.4 us (`evaluate`), 10.0 us (`scores`) or 4.7 us (`score_matrix`) in
0.3.0, against 59.2 us and 35.7 us for the first two in 0.2.0.

## Release checks

All ran under the CPU lock; `evidence/release-checks.json` lists every
command and exit status.

- `cargo fmt --check`, Clippy with `--features python` and `-D warnings`,
  and `cargo test --release --locked` (15 unit tests) passed.
- The CLI request (`evidence/cli.json`), capabilities
  (`evidence/capabilities.json`) and native sweep
  (`evidence/native-sweep.json`) ran.
- The independent domain validation `validation/validate.py` passed
  against the release CLI (`evidence/validation.json`; maximum IF97
  relative error 2.8e-9 against the 5e-8 limit).
- The sdist was built with maturin, extracted, and the wheel was built from
  the extracted sdist and installed with `--no-deps` into a fresh CPython
  3.12 venv. Its ABI is CPython 3.10+ (`abi3`) and its target Linux
  x86-64.
- From a directory outside the source tree, `validation/installed.py`
  passed (`evidence/installed.json`): ordered replay across worker counts,
  fixed work limits, and SQLite cancellation and resume, which retained 21
  attempts and recovered 12 completed rows.
- `validation/release_checks.py` passed (`evidence/tutorial-check.json`):
  lean, full and matrix parity under default, four-worker, step-limited and
  cancel-file budgets, ragged and empty matrix rejection, NumPy input, the
  tutorial's 5 Python blocks and the user manual's 23 Python blocks.
- Two full manifest runs of `validation/run_campaign.py` against the same
  database produced identical output (`evidence/campaign-replay.json`).
- All eight Python examples ran with the installed wheel and reproduced
  the saved outputs in `examples/python/outputs/` exactly; a seeded SciPy
  search ran (`evidence/scipy-search.json`).
- `cargo package --locked` built and verified the crate archive.
- The user manual's install commands also ran literally in an extracted
  copy of the ZIP: `python3 -m venv` (CPython 3.13 on this host), pip
  installs of the bundled wheel, of NumPy, SciPy and fcmaes and of maturin,
  `maturin sdist` and `maturin build`, and `pip wheel` of the sdist, whose
  `linux_x86_64`-tagged wheel has the same native extension
  (`evidence/release-checks.json`).

## Reproduction

Benchmark binaries for every kept round are `examples/performance.rs`
built at that round's commit (`cargo build --release --locked --examples`).
Pair two of them with

```sh
python validation/performance_pair.py BEFORE AFTER models/example.json WORKLOAD --samples 11 \
    [--before-scores|--before-matrix] [--after-scores|--after-matrix]
```

To reconstruct the 0.3.0 history, unpack the 0.2.0 delivery, commit it as
a baseline, and apply `patches/0.3.0/*.patch` in filename order with
`git am`: the series holds the ten rounds (`0001`-`0010`) and three
release commits (`0011`-`0013`: manual, examples and performance evidence;
native release evidence and the move of the 0.2.0 records; installed
checks, packages and this log). The patch files and `SHA256SUMS` are added
by a final commit that is not part of the series. The 0.2.0 series is in
`patches/0.2.0/` and applies to the 0.1.0 source as described in the 0.2.0
log. `examples/breakdown.rs`,
`validation/python_call_costs.py` and `validation/run_examples.py`
regenerate the breakdown, the Python per-call costs and the example
outputs.

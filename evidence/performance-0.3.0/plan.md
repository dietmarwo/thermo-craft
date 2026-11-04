# thermo-craft 0.3.0 performance plan

Host: 2 vCPUs, Intel(R) Xeon(R) Processor @ 2.10GHz (KVM), Rust 1.97.0,
CPython 3.12. Shared by five agents; every timing run holds
`/home/claude/craft5/cpu.lock`.

Decision rule (fixed for every round, never changed after a timing):
time the declared workload with `validation/performance_pair.py
--samples 11` against the previous kept round's saved binary, inside the
CPU lock. Keep the round if the paired output check passes and the
median speedup (before median / after median) is at least 1.03x.
Otherwise revert it, save the JSON under `rejected/` and try something else.

Baseline profile of 0.2.0 on this host (scratch harness, 96 serial
candidates): candidate JSON decode 14 us per batch, domain evaluation
about 2.8 ms per batch (about 29 us per candidate), full metrics as
`serde_json::Value` plus encoding about 0.6-1.0 ms per batch. A serial
regenerative candidate takes 121 logical steps: three single-phase
inverse states, each a 40-step bisection with about 42 scalar Region 2
Gibbs evaluations, so roughly 126 of the 133 Gibbs evaluations per
candidate sit inside the bisection. Each scalar Region 2 evaluation
recomputes a 58-long sequential chain of reduced-temperature powers.

## Round 1: typed score-matrix API (required)

- Change: `Prepared::score_matrix(rows, parameters, budget)` returning
  `Vec<MatrixScore>`, a Python `score_matrix`, a `CRAFT_MATRIX` mode in
  `examples/performance.rs`, `--before-matrix/--after-matrix` in
  `validation/performance_pair.py`, `--matrix` in
  `validation/optimize_performance.py`.
- Workload: `serial` (96 candidates, one worker); before = round 0 lean
  `scores_json` (`--before-scores`), after = round 1 matrix
  (`--after-matrix`).
- Expected effect: removes candidate JSON decode, ID hashing, record
  construction and JSON encode. The profile puts these at roughly 1-3%
  of a domain-dominated serial batch, so the gain is expected to be
  small for this project; the decision rule above applies unchanged.

Round 1 result (recorded after its timing): the official 11-sample run
(`round01-serial.json`) reported 4.207 -> 2.932 ms, 1.43x, but its samples
are bimodal: the host switched between a ~2.8 ms and a ~4.2 ms speed regime
during the run, and the split landed between the two medians. A 41-sample
rerun (`round01-serial-confirm41.json`) gives a ratio of medians of 1.046x
and a median per-pair ratio of 1.014x. The real native effect on this
domain-dominated workload is therefore about 1-1.5%, below the 1.03x bar,
as the profile predicted. The round is kept only because the brief requires
the matrix API as round 1; it is not counted as a substantive native
improvement. Supplementary pairs on workloads where the JSON boundary
matters (same binaries, lean before, matrix after): `domain2` 2.17x
(`round01-supplement-domain2.json`), `invalid` 46.5x
(`round01-supplement-invalid.json`).

## Protocol for rounds 2-10 (written before any round-2 timing)

The host speed drifts between regimes lasting seconds (30 back-to-back runs
of one binary ranged 2.1-4.3 ms). Adjacent before/after samples share a
regime, so `performance_pair.py` now also reports `paired_median_speedup`,
the median of per-sample-pair ratios. For every round from 2 on:

1. Official run: `performance_pair.py --samples 11` in the lock, saved as
   `roundNN-<workload>.json`.
2. Confirmation run, always performed whatever the official result:
   `performance_pair.py --samples 41` in the lock, saved as
   `roundNN-<workload>-confirm41.json`.
3. Keep only if the output check passes and all three of the official
   `speedup`, the official `paired_median_speedup` and the confirmation
   `paired_median_speedup` are at least 1.03. This is stricter than the
   brief's rule, never looser. Otherwise revert and save both JSON files
   under `rejected/`.

## Round 2: safeguarded Newton inverse at fixed pressure

- Change: replace the 40-step bisection on temperature with a Newton solve
  on the same bracket, using cp (enthalpy) or cp/T (entropy) from a new
  second reduced-temperature derivative. A step leaving the bracket falls
  back to bisection. The 40 logical steps are still charged, before the
  solve, with the same limit, cancel and deadline checks. The range check
  and the final state reconstruction are unchanged.
- Workload: `domain` (48 full records at 950 K, four single-phase
  inverses per candidate). Full API on both sides.
- Expected effect: 3-4 Gibbs evaluations per inverse instead of 42, so
  roughly 3-5x on the domain kernel and at least 2x on full domain records.
- Values change in the last bits (the root is now accurate to about 1e-13 K
  instead of the 2^-41 bisection bracket); run `validation/validate.py`
  against the release CLI.
- Result: official 3.281 -> 1.099 ms, 2.99x (paired 2.98x); confirmation
  2.269 -> 0.750 ms, paired 3.03x. Kept. Probe parity passed on every
  workload and API mode; `validate.py` passed against the release CLI
  (`round02-validation.json`; best efficiency moved by 2.1e-13).

## Round 3: typed metrics serialized directly

- Profile after round 2 (scratch harness, 96 serial candidates): lean
  domain about 0.54 ms per batch, full `evaluate_json` about 1.8 ms. Building
  `serde_json::Value` metrics (a sorted map per record and per state, about
  100 allocations per record) and encoding them costs about 13 us per record.
- Change: the domain returns a typed `Metrics` enum (skipped, property state,
  cycle) whose struct fields are declared in sorted key order, so the JSON is
  byte-identical to the sorted `Value` maps. Records serialize it directly.
- Workload: `serial` (96 full records, one worker), full API both sides.
- Expected effect: about 1.5-2x on full serial records; lean and matrix
  paths unaffected. Bit-identical values.
- Result: official 1.482 -> 0.805 ms, 1.84x (paired 1.61x); confirmation
  1.311 -> 0.791 ms, paired 1.66x. Kept. Probe output is byte-identical for
  `serial`, `trace` and `domain2`; parity passed on every workload and mode.

## Round 4: reuse the saturation property as the near bracket value

- Profile after round 3: a serial candidate makes about 23 Gibbs
  evaluations: four for the two saturation pairs, and per single-phase
  inverse two bracket-end values, 3-4 Newton evaluations and one final
  state. The bracket end at the saturation temperature repeats the
  saturation state's own computation (same pressure powers, same terms,
  same operation order), so its value equals that state's enthalpy or
  entropy bit for bit.
- Change: take that end value from the saturation pair; evaluate only the
  far end (273.16 K or 1073.15 K). A unit test asserts the bit equality.
- Workload: `domain` with the matrix API on both sides (isolates the
  kernel; four single-phase inverses per candidate).
- Expected effect: about 4 of about 30 Gibbs evaluations removed per
  candidate, roughly 1.08-1.15x. Bit-identical results.
- Result: official 0.556 -> 0.491 ms, 1.13x (paired 1.14x); confirmation
  0.558 -> 0.495 ms, paired 1.13x. Kept. Probe output byte-identical for
  `serial`, `domain`, `domain2` and `trace`; parity passed everywhere.

## Round 5: blocked power tables

- Profile: a scalar Region 2 evaluation first builds y^0..y^58 as one
  sequential chain of 58 dependent multiplications (about 230 cycles of
  latency), Region 1 builds 43 negative and 17 positive powers the same way,
  and each pressure-power table is a 24- or 32-long chain.
- Change: build every power table from x^1..x^8 and then
  x^k = x^(k-8) * x^8, so eight independent chains of at most seven steps
  replace the long chain. Same number of multiplications.
- Workload: `serial` with the matrix API on both sides.
- Expected effect: roughly 1.15-1.3x on the kernel; the per-term
  accumulation chains then become the main latency bound.
- Last bits change (different multiplication association); run
  `validate.py` against the release CLI.
- Result: official 0.674 -> 0.389 ms, 1.73x (paired 1.79x); confirmation
  0.489 -> 0.288 ms, paired 1.68x. Kept. Larger than expected: the power
  chain dominated the evaluation latency. Parity passed on every workload
  and mode; `validate.py` passed against the release CLI
  (`round05-validation.json`).

## Round 6: factor pressure powers out of the Gibbs term sums

- Profile reasoning after round 5: each of g, g_pi, g_tau and g_tautau is
  accumulated over all 43 (Region 2) or 34 (Region 1) terms in one serial
  add chain, and every term multiplies by its pressure power again.
- Change: group the coefficient tables by pressure exponent (tables are
  already sorted by it; groups are computed at compile time). Sum the short
  per-group reduced-temperature series first, then combine each group with
  its pressure power. g and g_pi share the same inner sum. Fewer
  multiplications and per-group chains of at most eight terms.
- Workload: `serial` with the matrix API on both sides.
- Expected effect: roughly 1.1-1.3x on the kernel.
- Last bits change (summation order); run `validate.py`.
- Result: official 0.273 -> 0.256 ms, 1.07x (paired 1.11x); confirmation
  0.280 -> 0.255 ms, paired 1.11x. Kept. Parity passed on every workload
  and mode; `validate.py` passed (`round06-validation.json`).

## Round 7: precomputed term factors and power indices

- Profile after round 6 (scratch harness, min of 25 interleaved samples):
  serial matrix batch 242 us (2.5 us per candidate, about 20 Gibbs
  evaluations), vapor state 118 ns, liquid 102 ns. Each term still converts
  its exponents to floats, multiplies n*J and n*J*(J-1) at run time and
  branches on the exponent sign and on J = 0 or 1.
- Change: compile-time term tables with power-table indices and the
  products n*J and n*J*(J-1) (identical IEEE products), one combined
  positive/negative power table, and the same for the ideal-gas part.
  Zero factors replace the skipped J = 0 and J = 1 derivative terms.
- Workload: `domain` with the matrix API on both sides.
- Expected effect: roughly 1.1-1.25x on the kernel. Bit-identical results
  (same products, same summation order; an added +0 or -0 term leaves a sum
  unchanged).
- Result: official 0.172 -> 0.135 ms, 1.28x (paired 1.33x); confirmation
  0.169 -> 0.125 ms, paired 1.36x. Kept. Probe output byte-identical for
  `serial`, `domain`, `domain2` and `trace`; a unit test checks bit
  identity with the round-6 loop on a pressure/temperature grid.

## Round 8: worker dispatch on the calling thread, capped at the CPU count

- Profile after round 7 (scratch harness, 96 full serial records, min of 25):
  one worker 390-526 us, two workers 460-480 us, four workers 464-525 us;
  spawning and joining one scoped thread costs 16-46 us on this VM, and
  `available_parallelism()` costs about 64 us per call. With four requested
  workers the engine starts four threads on two vCPUs while the calling
  thread only waits.
- Change: run one worker loop on the calling thread, spawn at most
  `min(workers, candidates, available_parallelism()) - 1` extra threads,
  and cache the CPU count for the process. Record order, statuses, steps
  and values are unchanged. The request still says `workers: 4`.
- Workload: `parallel` (96 full records, four requested workers), full API
  both sides.
- Expected effect: three fewer thread starts and no oversubscription,
  roughly 1.2-1.5x. Bit-identical results.
- Result: official 0.604 -> 0.514 ms, 1.18x (paired 1.11x); confirmation
  0.626 -> 0.470 ms, paired 1.26x. Kept. Probe output byte-identical for
  `serial`, `parallel` and `domain`; parity passed everywhere.

## Round 9: skip the far bracket evaluation when a floor proves the target is inside

- Profile reasoning after round 8: a vapor-side inverse costs about five
  Gibbs evaluations: one at the 1073.15 K bracket end, 3-4 Newton steps and
  the final state. The far-end value is only used for the range check and
  for the secant start.
- Change: a process-wide table of h and s at 1073.15 K on 64 log-spaced
  pressures (both decrease with pressure at fixed temperature). For a
  pressure in [P_k, P_k+1], the value at P_k+1 less a 1e-10 relative margin
  is a floor; a target below it is inside the bracket, so the exact
  evaluation is skipped. Otherwise the old evaluation and comparison run
  unchanged, so the infeasible classification is identical. The secant
  start uses the table interpolated in ln p when the far end is skipped.
  A unit test scans 20,000 pressures to confirm the floors.
- Workload: `domain` with the matrix API on both sides.
- Expected effect: about one of five evaluations per vapor inverse,
  roughly 1.1-1.18x on the kernel.
- Newton iterates change, so values change in the last bits; run
  `validate.py`.
- Result: official 0.129 -> 0.111 ms, 1.16x (paired 1.14x); confirmation
  0.128 -> 0.116 ms, paired 1.12x. Kept. Instrumented probes (not kept)
  showed every far-end evaluation skipped on `serial` and `domain` with
  unchanged Newton iteration counts. Parity passed everywhere;
  `validate.py` passed (`round09-validation.json`).

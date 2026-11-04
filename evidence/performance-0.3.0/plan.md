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

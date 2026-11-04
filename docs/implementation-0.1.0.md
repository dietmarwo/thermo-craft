# thermo-craft implementation log

3 November 2026. Version 0.1.0. This delivery uses the bounded research
scope recorded below. The independent references and optional comparisons
are identified separately for each increment.

## Increment results

| Increment | Status | Implementation and evidence |
| --- | --- | --- |
| 0 | Reference comparison blocked | The pinned PowerPlant source timed out. The TESPy tutorial was inspected, but TESPy and CoolProp could not be run. A distinct bounded topology and published property reference were selected. |
| 1 | Implemented | Versioned property and plant evaluators, native CLI and installed Python package. Invalid pressure and phase cases are classified. |
| 2 | Implemented with official reference | Original bounded IF97 regions 1, 2 and 4 implementation. Official liquid, vapor and saturation points, wet-state interpolation and SI checks pass. A separate CoolProp run remains open. |
| 3 | Implemented | Closed Rankine pilot with one pump, boiler, turbine and condenser. The simple-cycle audit independently checks pump and turbine work and verifies whole-cycle balance. |
| 4 | Bounded fallback | Two open heaters with two ordered extraction pressures, separately checked mass fractions and heater energy balances. No numerical equivalence to the unavailable original or TESPy is claimed. |
| 5 | Implemented | Cached monomial powers. Five alternating paired runs checked feasibility and efficiency over 360 pressure pairs. Workspaces and result construction are independent of candidate order. |
| 6 | Implemented on bounded topology | Twenty pressure pairs tested, plus native sweep and optional SciPy DE. The accepted design passes cold full-physics balance and exhaust checks. SQP and independent TESPy reevaluation remain open. |
| 7 | Implemented on bounded topology | Optimized worst-case efficiency on three declared thermal scenarios and compared the nominal and robust candidates on three separate stress cases. No dispatch surrogate was necessary. |
| 8 | Local fallback | Prepared, versioned local campaign with hash identity and cancellation/resume evidence. External worker and researcher review remain open. |
| 9 | Implemented for tested platform | Verified source, Rust crate, sdist and wheel. Coverage ends at the declared IF97 and fixed-cycle bounds. |

## Numerical results

The simple cycle reached **34.164%** efficiency. The best nominal regenerative design reached **38.408%** with extraction pressures [300000.0, 2000000.0] Pa. Cached powers reduced median elapsed time by **1.67×** on the 360-case batch. The maximum absolute efficiency change was 3.33e-16.

The optional in-process SciPy differential-evolution demonstration made
48 evaluations and replayed its selected candidate.
It used the packaged example and its own local bounds. The domain-specific
grid and holdout evidence are in `evidence/validation.json`.

## Installed performance and replay

The following are medians of three 96-candidate batch observations,
measured in a clean CPython 3.12 environment with the installed wheel.
The scenarios and candidate inputs are identical within a row pair.
Times include native crossing and compact JSON result conversion.

| Boundary | Time |
| --- | ---: |
| Cold preparation and batch, one worker | 7.455 ms |
| Prepared batch, one worker | 7.380 ms |
| Prepared batch, four workers | 3.925 ms |

The replay test reversed candidate order and changed worker count. It
recovered 12 completed SQLite records across cancellation and retained
21 attempts. This campaign uses a local database and package-build
identity. Cross-machine determinism and distributed worker behavior
were outside the test scope.

## Release evidence

- `cargo fmt`, Clippy with warnings denied and locked Rust release tests passed.
- The native sweep and numerical validation ran against a release build.
- A wheel built from the extracted sdist and installed offline into a fresh
  environment. The wheel target is Linux x86-64, CPython 3.10+ ABI. Actual
  verification used CPython 3.12 on x86_64.
- The standalone Rust crate passed Cargo package verification.
- Model and source manifests are in `docs/`. Raw timing, numerical and
  clean-install results are in `evidence/`.

The source was staged in successive local commits. Each increment above
records its own outcome, while related implementation changes share
commits.

- `4619644` Define versioned evaluation and packaging boundaries
- `fbb54af` Implement bounded domain evaluator and resumable local execution
- `8da8842` Validate model laws and add bounded search and installation examples
- `ef4465b` Prepare source distributions and document validated research scope
- `e6bded9` Canonicalize campaign replay output

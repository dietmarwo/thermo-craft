"""Optimize the extraction pressures with SciPy.

Optimization (SciPy): `differential_evolution` in vectorized mode hands a whole
population to one `score_matrix` call per generation; a Nelder-Mead polish then
refines the winner one candidate at a time. Variables are log10 pressures in
Pa. Failed candidates (status other than complete) get a penalty that grows
with the ordering violation, so the search is pushed back into the feasible
region instead of seeing a flat plateau.

Run: python examples/python/optimize_scipy.py
"""

from collections import Counter

import numpy as np
from scipy.optimize import differential_evolution, minimize

from thermo_craft import Prepared, load_example

case = load_example()
model = case["model"]
cycle = Prepared(model)
bounds = [(np.log10(20e3), np.log10(3e6)), (np.log10(0.2e6), np.log10(7.5e6))]
statuses_seen = Counter()


def penalized(x, scores, statuses):
    """Score for complete rows; 1 + ordering violation (in decades) otherwise."""
    out = np.array(scores)
    for k, status in enumerate(statuses):
        statuses_seen[status] += 1
        if status != "complete":
            low, high = x[k]
            out[k] = 1.0 + max(0.0, low - high)
    return out


def population_objective(xt):
    """SciPy's vectorized call: xt has shape (2, S); return S objective values."""
    x = np.atleast_2d(xt.T)
    scores, statuses, _ = cycle.score_matrix(10.0 ** x)
    return penalized(x, scores, statuses)


result = differential_evolution(
    population_objective, bounds, vectorized=True, updating="deferred",
    popsize=12, maxiter=60, tol=1e-10, seed=7, polish=False,
)
print(f"differential_evolution: {result.nit} generations, {result.nfev} vectorized calls, "
      f"{sum(statuses_seen.values())} candidates")
print(f"  statuses seen: {dict(statuses_seen)}")
print(f"  best low {10 ** result.x[0] / 1e3:.2f} kPa, high {10 ** result.x[1] / 1e6:.4f} MPa, "
      f"efficiency {-result.fun:.7f}")


def single_objective(x):
    return penalized([x], *cycle.score_matrix([10.0 ** x])[:2])[0]


statuses_seen.clear()
polish = minimize(single_objective, result.x, method="Nelder-Mead",
                  options={"xatol": 1e-7, "fatol": 1e-12, "maxiter": 400})
print(f"Nelder-Mead polish: {polish.nfev} evaluations, statuses {dict(statuses_seen)}")
print(f"  best low {10 ** polish.x[0] / 1e3:.2f} kPa, high {10 ** polish.x[1] / 1e6:.4f} MPa, "
      f"efficiency {-polish.fun:.7f}")

# Replay the winner with full metrics, as a design would be inspected.
row = cycle.evaluate((10.0 ** polish.x).tolist())
assert row["status"] == "complete", row
m = row["metrics"]
print(f"Replay: efficiency {m['efficiency']:.7f}, exhaust quality {m['exhaust_quality']:.4f}, "
      f"bleed fractions {m['extractions_low_high'][0]:.4f} / {m['extractions_low_high'][1]:.4f}")
print(f"Packaged example pair {case['parameters']} has efficiency "
      f"{-cycle.score_matrix([case['parameters']])[0][0]:.7f}")

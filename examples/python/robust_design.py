"""Robust extraction pressures across operating scenarios.

Optimization and scenario analysis: choose one extraction pair that maximizes
the worst-case efficiency over four operating scenarios (summer and winter
condenser pressure, new and degraded turbine). Each generation of an fcmaes
CMA-ES search is scored for all scenarios with one `score_matrix` call per
scenario. The robust pair is then compared with each scenario's own optimum.

Run: python examples/python/robust_design.py
"""

import numpy as np
from loguru import logger
from scipy.optimize import Bounds

from fcmaes import cmaes
from thermo_craft import Prepared, load_example

logger.remove()

nominal = load_example()["model"]
scenarios = {
    "winter, new turbine": nominal | {"condenser_pa": 8e3, "turbine_efficiency": 0.88},
    "summer, new turbine": nominal | {"condenser_pa": 25e3, "turbine_efficiency": 0.88},
    "winter, degraded": nominal | {"condenser_pa": 8e3, "turbine_efficiency": 0.83},
    "summer, degraded": nominal | {"condenser_pa": 25e3, "turbine_efficiency": 0.83},
}
prepared = {name: Prepared(model) for name, model in scenarios.items()}
bounds = Bounds([np.log10(20e3), np.log10(0.2e6)], [np.log10(3e6), np.log10(7.5e6)])


def scenario_scores(xs, which):
    """(popsize, scenarios) matrix of -efficiency, NaN where a scenario fails."""
    pressures = 10.0 ** np.atleast_2d(xs)
    return np.column_stack([prepared[name].score_matrix(pressures, workers=2)[0] for name in which])


def optimize(which, seed):
    es = cmaes.Cmaes(bounds, [np.log10(300e3), np.log10(2e6)], input_sigma=0.25, popsize=12,
                     max_evaluations=900, rg=np.random.default_rng(seed),
                     randn=np.random.RandomState(seed).randn)
    best = (np.inf, None)
    while True:
        xs = es.ask()
        worst = scenario_scores(xs, which).max(axis=1)  # worst case = largest -efficiency
        worst[np.isnan(worst)] = 1.0  # any failing scenario disqualifies the pair
        k = int(np.argmin(worst))
        if worst[k] < best[0]:
            best = (worst[k], xs[k].copy())
        if es.tell(worst) != 0:
            return best


robust_score, robust_x = optimize(list(scenarios), seed=3)
print(f"Robust pair: low {10 ** robust_x[0] / 1e3:.1f} kPa, high {10 ** robust_x[1] / 1e6:.3f} MPa, "
      f"worst-case efficiency {-robust_score:.5f}")
print(f"\n{'scenario':>22} {'own optimum':>12} {'robust pair':>12} {'regret':>8}   own pair")
robust = scenario_scores(robust_x, list(scenarios))[0]
for k, name in enumerate(scenarios):
    own_score, own_x = optimize([name], seed=3)
    regret = round(100 * (robust[k] - own_score), 4) + 0.0  # + 0.0 turns -0.0 into 0.0
    print(f"{name:>22} {-own_score:12.5f} {-robust[k]:12.5f} {regret:7.4f}pp"
          f"   {10 ** own_x[0] / 1e3:.0f} kPa / {10 ** own_x[1] / 1e6:.3f} MPa")

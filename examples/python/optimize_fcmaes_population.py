"""Population optimizers from fcmaes evaluating whole generations natively.

Optimization (fcmaes ask/tell): `fcmaes.cmaes.Cmaes` and `fcmaes.de.DE` ask for
a population, the population is scored with one `score_matrix` call using two
native workers (the GIL is released during evaluation), and the penalized
scores are told back. Variables are log10 extraction pressures in Pa.

Run: python examples/python/optimize_fcmaes_population.py
"""

from collections import Counter

import numpy as np
from loguru import logger
from scipy.optimize import Bounds

from fcmaes import cmaes, de
from thermo_craft import Prepared, load_example

logger.remove()  # fcmaes logs through loguru; keep the example output quiet

model = load_example()["model"]
cycle = Prepared(model)
bounds = Bounds([np.log10(20e3), np.log10(0.2e6)], [np.log10(3e6), np.log10(7.5e6)])


def score_population(xs, seen):
    """Penalized objective for a (popsize, 2) array of log10 pressures."""
    xs = np.asarray(xs)  # CMA-ES asks for an array, DE for a list of vectors
    scores, statuses, steps = cycle.score_matrix(10.0 ** xs, workers=2)
    seen.update(statuses)
    ys = np.array(scores)
    failed = np.array([s != "complete" for s in statuses])
    # Infeasible rows: 1 + how far (in decades) the low pressure exceeds the high one.
    ys[failed] = 1.0 + np.maximum(0.0, xs[failed, 0] - xs[failed, 1])
    return ys, sum(steps)


def run(name, optimizer):
    seen, evaluations, steps, generations = Counter(), 0, 0, 0
    best = (np.inf, None)
    while True:
        xs = optimizer.ask()
        ys, used = score_population(xs, seen)
        evaluations += len(ys)
        steps += used
        generations += 1
        k = int(np.argmin(ys))
        if ys[k] < best[0]:
            best = (ys[k], xs[k].copy())
        if optimizer.tell(ys) != 0:
            break
    low, high = 10.0 ** best[1]
    print(f"{name}: {generations} generations, {evaluations} evaluations, "
          f"{steps} logical steps, statuses {dict(seen)}")
    print(f"  best low {low / 1e3:.2f} kPa, high {high / 1e6:.4f} MPa, efficiency {-best[0]:.7f}")
    return best


x0 = np.array([np.log10(300e3), np.log10(2e6)])
# Cmaes draws its normal samples through `randn`; seed it too for a reproducible run.
es = cmaes.Cmaes(bounds, x0, input_sigma=0.3, popsize=16, max_evaluations=1600,
                 stop_fitness=-1.0, rg=np.random.default_rng(11),
                 randn=np.random.RandomState(11).randn)
cma_best = run("fcmaes CMA-ES (ask/tell)", es)

opt = de.DE(2, bounds, popsize=16, rg=np.random.default_rng(11))
# DE has no evaluation limit of its own here: stop after 60 generations.
seen, best, evaluations = Counter(), (np.inf, None), 0
for generation in range(60):
    xs = opt.ask()
    ys, _ = score_population(xs, seen)
    evaluations += len(ys)
    k = int(np.argmin(ys))
    if ys[k] < best[0]:
        best = (ys[k], xs[k].copy())
    if opt.tell(ys) != 0:
        break
low, high = 10.0 ** best[1]
print(f"fcmaes DE (ask/tell): {generation + 1} generations, {evaluations} evaluations, "
      f"statuses {dict(seen)}")
print(f"  best low {low / 1e3:.2f} kPa, high {high / 1e6:.4f} MPa, efficiency {-best[0]:.7f}")

row = cycle.evaluate((10.0 ** cma_best[1]).tolist())
print(f"Replay of the CMA-ES winner: {row['status']}, efficiency {row['metrics']['efficiency']:.7f}, "
      f"exhaust quality {row['metrics']['exhaust_quality']:.4f}")

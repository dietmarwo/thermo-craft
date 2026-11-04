"""Standard fcmaes minimizers with failure penalties.

Optimization (fcmaes minimize): `fcmaes.bitecpp.minimize` (BiteOpt) and
`fcmaes.de.minimize` call a scalar objective once per candidate. The objective
uses a one-row `score_matrix` call, and every status other than complete maps
to a penalty: a graded one for ordering violations, which the optimizer can
descend, and a flat one for physically infeasible cycles. A tighter exhaust
quality limit makes a large part of the box infeasible.

Run: python examples/python/optimize_fcmaes_minimize.py
"""

from collections import Counter

import numpy as np
from loguru import logger
from scipy.optimize import Bounds

from fcmaes import bitecpp, de
from thermo_craft import Prepared, load_example

logger.remove()

nominal = load_example()["model"]
bounds = Bounds([np.log10(20e3), np.log10(0.2e6)], [np.log10(3e6), np.log10(7.5e6)])


def make_objective(model):
    cycle = Prepared(model)
    seen = Counter()

    def objective(x):
        scores, statuses, _ = cycle.score_matrix([10.0 ** np.asarray(x)])
        seen[statuses[0]] += 1
        if statuses[0] == "complete":
            return scores[0]
        low, high = x
        if low >= high:
            return 2.0 + (low - high)  # ordering violation: graded penalty
        return 1.0  # wet exhaust, infeasible heater mix or balance failure

    return cycle, objective, seen


for label, model in [("nominal (exhaust quality >= 0.75)", nominal),
                     ("strict (exhaust quality >= 0.895)", nominal | {"min_exhaust_quality": 0.895})]:
    print(label)
    for name, minimize in [
        ("bitecpp.minimize", lambda f: bitecpp.minimize(f, bounds, max_evaluations=1500,
                                                       rg=np.random.default_rng(5))),
        ("de.minimize", lambda f: de.minimize(f, 2, bounds, popsize=16, max_evaluations=1500,
                                              rg=np.random.default_rng(5))),
    ]:
        cycle, objective, seen = make_objective(model)
        result = minimize(objective)
        low, high = 10.0 ** result.x
        if result.fun < 0:
            row = cycle.evaluate([low, high])
            detail = (f"efficiency {-result.fun:.7f}, exhaust quality "
                      f"{row['metrics']['exhaust_quality']:.4f}")
        else:
            detail = f"no feasible point found (best penalty {result.fun})"
        print(f"  {name:17} {result.nfev:5d} evaluations, statuses {dict(seen)}")
        print(f"  {'':17} low {low / 1e3:8.2f} kPa, high {high / 1e6:.4f} MPa, {detail}")

"""Sensitivity of the regenerative cycle to its design and operating inputs.

Application (sensitivity): at the nominal optimum extraction pair, perturb each
model input by a small relative step, re-prepare the model and report central
difference derivatives and elasticities of thermal efficiency. Then check how
far the nominal pair is from the re-optimized pair when the condenser pressure
changes with cooling-water temperature.

Run: python examples/python/sensitivity.py
"""

import math

from thermo_craft import Prepared, load_example

nominal = load_example()["model"]


def geomspace(a, b, n):
    return [a * (b / a) ** (k / (n - 1)) for k in range(n)]


def optimum(model, center=None, span=2.0, n=21, rounds=3):
    """Shrinking log-grid search for the best extraction pair of one model."""
    prepared = Prepared(model)
    lo, hi = center or (300e3, 2e6)
    for _ in range(rounds):
        rows = [[a, b] for a in geomspace(lo / span, lo * span, n)
                for b in geomspace(hi / span, min(hi * span, 0.99 * model["boiler_pa"]), n)]
        scores, _, _ = prepared.score_matrix(rows, workers=2)
        score, (lo, hi) = min((s, r) for s, r in zip(scores, rows) if not math.isnan(s))
        span = span ** 0.35
    return -score, [lo, hi]


best_efficiency, pair = optimum(nominal)
print(f"Nominal optimum: low {pair[0] / 1e3:.1f} kPa, high {pair[1] / 1e6:.4f} MPa, "
      f"efficiency {best_efficiency:.6f}")


def efficiency(model, parameters):
    scores, statuses, _ = Prepared(model).score_matrix([parameters])
    return -scores[0] if statuses[0] == "complete" else math.nan


print(f"\n{'input':>20} {'value':>12} {'d(eta)/d(input)':>16} {'elasticity':>11}")
for key in ("boiler_pa", "condenser_pa", "inlet_k", "turbine_efficiency", "pump_efficiency"):
    value = nominal[key]
    h = 1e-3 * value
    up = efficiency(nominal | {key: value + h}, pair)
    down = efficiency(nominal | {key: value - h}, pair)
    derivative = (up - down) / (2 * h)
    print(f"{key:>20} {value:12.6g} {derivative:16.4e} {derivative * value / best_efficiency:11.4f}")

# Seasonal condenser pressure: fixed nominal pair versus re-optimized pair.
print(f"\n{'condenser':>10} {'eta(nominal pair)':>18} {'eta(re-optimized)':>18} {'loss':>8}  pair")
losses = []
for condenser in (8e3, 10e3, 15e3, 20e3, 30e3):
    model = nominal | {"condenser_pa": condenser}
    fixed = efficiency(model, pair)
    best, better_pair = optimum(model, center=pair)
    losses.append(100 * (best - fixed))
    print(f"{condenser / 1e3:8.0f}kPa {fixed:18.6f} {best:18.6f} {losses[-1]:7.4f}pp  "
          f"{better_pair[0] / 1e3:.0f} kPa / {better_pair[1] / 1e6:.3f} MPa")
print(f"\nKeeping the nominal pair costs at most {max(losses):.4f} percentage points over this")
print("condenser range, while the condenser pressure itself moves efficiency by "
      f"{100 * (efficiency(nominal | {'condenser_pa': 8e3}, pair) - efficiency(nominal | {'condenser_pa': 30e3}, pair)):.2f} points.")

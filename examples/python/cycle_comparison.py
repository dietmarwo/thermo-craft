"""Simple versus regenerative Rankine cycles across boiler conditions.

Application (scenario comparison): for a matrix of boiler pressures and turbine
inlet temperatures, compare the simple cycle with the two-open-heater cycle at
its best extraction pair (coarse grid, then a refined grid), and report how
the exhaust-quality limit restricts high-pressure, low-temperature designs.

Run: python examples/python/cycle_comparison.py
"""

import math

from thermo_craft import Prepared

base = {
    "kind": "rankine",
    "condenser_pa": 10e3,
    "turbine_efficiency": 0.87,
    "pump_efficiency": 0.8,
    "min_exhaust_quality": 0.86,
}


def geomspace(a, b, n):
    return [a * (b / a) ** (k / (n - 1)) for k in range(n)]


def best_pair(prepared, low_range, high_range, n=24):
    """Best grid point in log-pressure space; returns (efficiency, [low, high]) or None."""
    rows = [[lo, hi] for lo in geomspace(*low_range, n) for hi in geomspace(*high_range, n)]
    scores, _, _ = prepared.score_matrix(rows, workers=2)
    feasible = [(s, r) for s, r in zip(scores, rows) if not math.isnan(s)]
    if not feasible:
        return None
    score, row = min(feasible)
    return -score, row


print(f"Condenser {base['condenser_pa'] / 1e3:.0f} kPa, turbine efficiency "
      f"{base['turbine_efficiency']}, minimum exhaust quality {base['min_exhaust_quality']}")
print(f"{'boiler':>8} {'inlet':>8} | {'simple':>7} {'x_exh':>6} | {'regen':>7} "
      f"{'low':>8} {'high':>8} {'x_exh':>6} | {'gain':>6}")
for boiler in (4e6, 8e6, 12e6, 16e6):
    for inlet in (723.15, 813.15, 873.15):
        model = base | {"boiler_pa": boiler, "inlet_k": inlet}
        simple = Prepared(model | {"extraction": False}).evaluate([])
        if simple["status"] == "complete":
            s = simple["metrics"]
            simple_text = f"{s['efficiency']:7.4f} {s['exhaust_quality']:6.3f}"
        else:
            simple_text = f"{'(' + simple['status'] + ')':>14}"
        regen = Prepared(model | {"extraction": True})
        coarse = best_pair(regen, (20e3, 0.9 * boiler), (50e3, 0.95 * boiler))
        if coarse is None:
            print(f"{boiler / 1e6:6.0f}MPa {inlet:8.2f} | {simple_text} | no feasible extraction pair")
            continue
        _, (lo, hi) = coarse
        efficiency, (lo, hi) = best_pair(regen, (lo / 1.6, lo * 1.6), (hi / 1.6, min(hi * 1.6, 0.99 * boiler)))
        replay = regen.evaluate([lo, hi])["metrics"]
        gain = (efficiency - s["efficiency"]) * 100 if simple["status"] == "complete" else math.nan
        bound = "*" if replay["exhaust_quality"] < base["min_exhaust_quality"] + 0.002 else " "
        print(f"{boiler / 1e6:6.0f}MPa {inlet:8.2f} | {simple_text} | {efficiency:7.4f} "
              f"{lo / 1e3:6.0f}kPa {hi / 1e6:6.2f}MPa {replay['exhaust_quality']:6.3f}{bound}| {gain:5.2f}pp")

print("* exhaust quality at its limit: the constraint, not the heater balance, sets the optimum")

# Why some simple cycles fail: the exhaust is too wet at high pressure and low temperature.
row = Prepared(base | {"boiler_pa": 16e6, "inlet_k": 723.15, "extraction": False}).evaluate([])
print(f"\n16 MPa / 723.15 K simple cycle: {row['status']} - {row['detail']}")
relaxed = Prepared(base | {"boiler_pa": 16e6, "inlet_k": 723.15, "extraction": False,
                           "min_exhaust_quality": 0.0}).evaluate([])
print(f"  with the quality limit removed its exhaust quality would be "
      f"{relaxed['metrics']['exhaust_quality']:.3f}")

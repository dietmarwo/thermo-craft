"""Efficiency map over the two feedwater-heater extraction pressures.

Application (parameter study): evaluate a log-spaced grid of low and high
extraction pressures for the packaged regenerative Rankine cycle with one
`score_matrix` call per chunk, print a text map of thermal efficiency, count
the infeasible region, and replay the best grid point with full metrics.

Run: python examples/python/extraction_map.py
"""

from collections import Counter
import math

from thermo_craft import Prepared, load_example

case = load_example()
model = case["model"]
cycle = Prepared(model)


def geomspace(a, b, n):
    return [a * (b / a) ** (k / (n - 1)) for k in range(n)]


low = geomspace(50e3, 1.5e6, 16)   # Pa
high = geomspace(0.5e6, 6e6, 16)   # Pa
rows = [[lo, hi] for lo in low for hi in high]
scores, statuses, steps = cycle.score_matrix(rows, workers=2)
print(f"{len(rows)} candidates, statuses: {dict(Counter(statuses))}")
print(f"logical steps per complete candidate: {sorted(set(s for s, st in zip(steps, statuses) if st == 'complete'))}")

print("\nThermal efficiency [%] (rows: low extraction, columns: high extraction; '  .' = infeasible)")
print("low\\high " + "".join(f"{hi / 1e6:5.2f}" for hi in high) + "  [MPa]")
for i, lo in enumerate(low):
    cells = []
    for j in range(len(high)):
        score = scores[i * len(high) + j]
        cells.append("    ." if math.isnan(score) else f"{-100 * score:5.1f}")
    print(f"{lo / 1e3:6.0f}kPa" + "".join(cells))

best = min(range(len(rows)), key=lambda k: scores[k] if not math.isnan(scores[k]) else math.inf)
row = cycle.evaluate(rows[best])
m = row["metrics"]
print(f"\nBest grid point: low {rows[best][0] / 1e3:.1f} kPa, high {rows[best][1] / 1e6:.3f} MPa")
print(f"  efficiency           {m['efficiency']:.5f}")
print(f"  bleed fractions      low {m['extractions_low_high'][0]:.4f}, high {m['extractions_low_high'][1]:.4f}")
print(f"  condenser mass flow  {m['condenser_mass_fraction']:.4f} per kg boiler flow")
print(f"  exhaust quality      {m['exhaust_quality']:.4f} (minimum {model['min_exhaust_quality']})")
print(f"  net work             {m['net_work_j_kg'] / 1e3:.2f} kJ/kg, heat in {m['heat_in_j_kg'] / 1e3:.2f} kJ/kg")
print(f"  energy residual      {m['energy_residual_j_kg']:.2e} J/kg")
names = ["turbine inlet", "high bleed", "low bleed", "exhaust", "condensate",
         "low heater out", "high heater out"]
for name, s in zip(names, m["states"]):
    quality = "superheated" if s["quality"] is None else f"x = {s['quality']:.4f}"
    print(f"  {name:16} p {s['p_pa'] / 1e3:8.1f} kPa  T {s['t_k']:7.2f} K  "
          f"h {s['h_j_kg'] / 1e3:8.2f} kJ/kg  {quality}")

# The simple cycle (no extraction) is the reference the heaters improve on.
simple = Prepared(model | {"extraction": False}).evaluate([])
gain = m["efficiency"] - simple["metrics"]["efficiency"]
print(f"\nSimple cycle efficiency {simple['metrics']['efficiency']:.5f}; "
      f"two open heaters add {100 * gain:.2f} percentage points")

# Bounded water and steam cycle model

Public units are pascals, kelvin, joules per kilogram, joules per kilogram
kelvin and cubic metres per kilogram. The property adapter covers
IAPWS IF97 regions 1, 2 and 4 within 1 kPa to 16 MPa and 273.16 K to
1073.15 K. The selected pressure ceiling keeps saturation below the
region-3 boundary. A P/T pair at saturation requires a quality input.
Wet enthalpy, entropy and volume use the mass-fraction lever rule.
Single-phase inverse states use a bounded bisection on temperature.
The property example verifies published values in SI. It covers the
subcooled, superheated, saturation and wet paths.

The Rankine evaluator fixes boiler and condenser pressures and the
superheated turbine inlet temperature. Turbines use an isentropic
reference at the outlet pressure and apply a prescribed efficiency.
Pumps use an incompressible estimate from inlet saturated-liquid
specific volume, pressure rise and efficiency. The simple cycle has
one expansion and one pump. The regenerative variant has two open
feedwater heaters, three expansion stages and three pumps. Mixing
equations determine the two bleed fractions. The two pressures are
explicit candidate parameters in Pa and must be ordered.

All mass fractions refer to boiler mass flow. Positive gross and net
work are useful output. Boiler input and condenser rejection are
reported separately. Whole-cycle and heater residuals, net work and
exhaust quality are checked. The score is minus thermal efficiency.
Infeasible pressure pairs and quality violations have no score. This
fixed topology is a separate research model from the pinned PowerPlant
case and the TESPy tutorial.

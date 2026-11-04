"""Steam property tables from the bounded IF97 model.

Application: build a saturation table and a superheated-steam table, estimate
cp by finite differences, check official IAPWS-IF97 verification points, and
show how out-of-range queries are reported.

Run: python examples/python/property_tables.py
"""

from thermo_craft import Prepared

properties = Prepared({"kind": "property"})

# 1. Saturation table: [p, quality, 0] queries for x = 0 (liquid) and x = 1 (vapor).
pressures = [1e4, 1e5, 1e6, 5e6, 1e7, 1.5e7]
queries = [{"id": f"{p:g}-{x}", "parameters": [p, x, 0.0]} for p in pressures for x in (0.0, 1.0)]
rows = properties.batch(queries)["records"]
print("Saturation table (IF97 region 4 with regions 1 and 2)")
print(f"{'p [kPa]':>9} {'T_sat [K]':>10} {'h_f [kJ/kg]':>12} {'h_g [kJ/kg]':>12} "
      f"{'h_fg [kJ/kg]':>13} {'s_f':>8} {'s_g':>8} {'v_g [m3/kg]':>12}")
for p, liquid, vapor in zip(pressures, rows[0::2], rows[1::2]):
    f, g = liquid["metrics"]["state"], vapor["metrics"]["state"]
    print(f"{p / 1e3:9.1f} {f['t_k']:10.3f} {f['h_j_kg'] / 1e3:12.2f} {g['h_j_kg'] / 1e3:12.2f} "
          f"{(g['h_j_kg'] - f['h_j_kg']) / 1e3:13.2f} {f['s_j_kg_k'] / 1e3:8.4f} "
          f"{g['s_j_kg_k'] / 1e3:8.4f} {g['v_m3_kg']:12.5f}")

# 2. Superheated steam at 1 MPa. The score of a property query is h in J/kg, so
# score_matrix gives enthalpies without JSON; central differences estimate cp.
temperatures = [500.0, 600.0, 700.0, 800.0, 900.0, 1000.0]
step = 0.5
grid = [[1e6, t + d] for t in temperatures for d in (-step, 0.0, step)]
h, statuses, _ = properties.score_matrix(grid)
assert set(statuses) == {"complete"}
states = properties.batch([{"id": str(t), "parameters": [1e6, t]} for t in temperatures])["records"]
print("\nSuperheated steam at 1 MPa")
print(f"{'T [K]':>7} {'h [kJ/kg]':>10} {'s [kJ/kg K]':>12} {'v [m3/kg]':>10} {'cp [kJ/kg K]':>13}")
for k, (t, row) in enumerate(zip(temperatures, states)):
    s = row["metrics"]["state"]
    cp = (h[3 * k + 2] - h[3 * k]) / (2 * step)
    assert h[3 * k + 1] == s["h_j_kg"]
    print(f"{t:7.1f} {s['h_j_kg'] / 1e3:10.2f} {s['s_j_kg_k'] / 1e3:12.4f} {s['v_m3_kg']:10.5f} "
          f"{cp / 1e3:13.4f}")

# 3. Official verification points, IAPWS R7-97(2012) Tables 5 and 15 (h, s, v).
reference = {
    (3e6, 300.0): (115331.273, 392.294792, 0.00100215168),
    (80e6, 300.0): None,  # outside the bounded 16 MPa envelope: reported invalid
    (3e6, 500.0): (975542.239, 2580.41912, 0.00120241800),
    (3500.0, 300.0): (2549911.45, 8522.38967, 39.4913866),
    (3500.0, 700.0): (3335683.75, 10174.9996, 92.3015898),
}
rows = properties.batch([{"id": f"{p:g}/{t:g}", "parameters": [p, t]} for p, t in reference])
print("\nIAPWS-IF97 verification points")
for (point, expected), row in zip(reference.items(), rows["records"]):
    if expected is None:
        print(f"{row['id']:>12}: {row['status']} ({row['detail']})")
        continue
    s = row["metrics"]["state"]
    errors = [abs(s[k] / v - 1) for k, v in zip(("h_j_kg", "s_j_kg_k", "v_m3_kg"), expected)]
    print(f"{row['id']:>12}: max relative error {max(errors):.1e}")
    assert max(errors) < 5e-8

# 4. Queries the model rejects, with their status and detail.
bad = [[3e6, 2000.0], [1e5, 1.2, 0.0], [1e5, 372.7559186113376], [1e5, 0.5, 1.0]]
for row in properties.batch([{"id": str(q), "parameters": q} for q in bad])["records"]:
    print(f"{row['id']:>26}: {row['status']:>8} - {row['detail']}")

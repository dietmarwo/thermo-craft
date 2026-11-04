import math
import sys

from tools import good, run, save

binary=sys.argv[1]
# IAPWS R7-97(2012) Tables 5, 15, 35, transcribed in SI.
refs=[
    ([3e6,300],[115331.273,392.294792,.00100215168]),
    ([3e6,500],[975542.239,2580.41912,.00120241800]),
    ([3500,300],[2549911.45,8522.38967,39.4913866]),
    ([3500,700],[3335683.75,10174.9996,92.3015898]),
]
rows=run(binary,{"kind":"property"},[p for p,_ in refs])
residuals=[]
for row, (_,ref) in zip(rows,refs,strict=True):
    state=good(row)["state"]
    error=[abs(state[k]/v-1) for k,v in zip(["h_j_kg","s_j_kg_k","v_m3_kg"],ref,strict=True)]
    assert max(error)<5e-8,(state,ref,error)
    residuals.append(error)
sat=run(binary,{"kind":"property"},[[p,x,0] for p in [3536.58941,2638897.76,12344314.6] for x in [0,.5,1]])
for offset,t in enumerate([300,500,600]):
    a,b,c=[good(r)["state"] for r in sat[3*offset:3*offset+3]]
    assert abs(a["t_k"]-t)<2e-6
    assert math.isclose(b["h_j_kg"],(a["h_j_kg"]+c["h_j_kg"])/2,rel_tol=1e-14)
    assert math.isclose((c["h_j_kg"]-a["h_j_kg"])/(c["s_j_kg_k"]-a["s_j_kg_k"]),t,rel_tol=1e-4)
assert run(binary,{"kind":"property"},[[1,400],[30e6,800],[10e3,1.1,0]])[2]["status"]=="invalid"
plant={"kind":"rankine","boiler_pa":8e6,"condenser_pa":15e3,"inlet_k":813.15,
       "turbine_efficiency":.88,"pump_efficiency":.8,"min_exhaust_quality":.75}
simple=good(run(binary,plant,[[]])[0])
i,e,f=simple["states"]
assert abs(simple["pump_work_j_kg"]-f["v_m3_kg"]*(i["p_pa"]-f["p_pa"])/plant["pump_efficiency"]) < 1e-8
assert abs(simple["gross_work_j_kg"]-(i["h_j_kg"]-e["h_j_kg"]))<1e-8
assert abs(simple["energy_residual_j_kg"])<1e-6
regen=plant|{"extraction":True}
assert run(binary,regen,[[2e6,1e6]])[0]["status"]=="infeasible"
assert run(binary,regen|{"min_exhaust_quality":1},[[300e3,2e6]])[0]["status"]=="infeasible"
candidates=[[a*1e3,b*1e3] for a in [150,300,500,800,1200] for b in [1500,2000,3000,4000]]
batch=run(binary,regen,candidates,budget={"workers":4})
winner=min((r for r in batch if r["status"]=="complete"),key=lambda r:r["score"])
w=good(winner)
assert abs(w["energy_residual_j_kg"])<1e-6
assert abs(sum(w["extractions_low_high"])+w["condenser_mass_fraction"]-1)<1e-14
assert max(map(abs,w["heater_residuals_j_kg"]))<1e-6
assert batch == run(binary,regen,candidates)
training=[]
for pressure,eta in [(12e3,.87),(18e3,.9),(25e3,.86)]:
    training.append(run(binary,regen|{"condenser_pa":pressure,"turbine_efficiency":eta},candidates))
robust_idx=min(
    (j for j in range(len(candidates)) if all(case[j]["status"]=="complete" for case in training)),
    key=lambda j:max(case[j]["score"] for case in training),
)
stress=[]
for pressure,eta in [(10e3,.88),(22e3,.86),(30e3,.91)]:
    hold=run(binary,regen|{"condenser_pa":pressure,"turbine_efficiency":eta},
             [candidates[int(winner["id"])],candidates[robust_idx]])
    stress.append({"cond_pa":pressure,"eta":eta,
                   "nominal":{"status":hold[0]["status"],"score":hold[0]["score"]},
                   "robust":{"status":hold[1]["status"],"score":hold[1]["score"]}})
save({"model":regen,"parameters":candidates[int(winner["id"])]},{"iapws_relative_errors":residuals,
     "relative_tolerance":5e-8,"simple_efficiency":simple["efficiency"],"bounded_grid_evaluations":len(batch),
     "best_efficiency":w["efficiency"],"winner":candidates[int(winner["id"])],"stress_set":stress,
     "robust_training_winner":candidates[robust_idx],"winner_states":w["states"],"energy_residual_j_kg":w["energy_residual_j_kg"]})

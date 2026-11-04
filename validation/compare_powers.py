"""Same-request comparison of power evaluation strategies."""

import json
from statistics import median
import subprocess
import sys
from time import perf_counter

from tools import ROOT

baseline, candidate = sys.argv[1:]
case = json.loads((ROOT / "models/example.json").read_text())
pairs = [[120_000 + i*50_000,1_500_000+j*200_000] for i in range(20) for j in range(18)]
req = json.dumps({"schema":"thermo-craft.request/0.1","model":case["model"],
                  "candidates":[{"id":str(i),"parameters":p} for i,p in enumerate(pairs)]})
rows = {"powi":[],"cached":[]}
max_error = 0.
for repeat in range(5):
    observed={}
    for label, binpath in [("powi",baseline),("cached",candidate)][::(-1 if repeat%2 else 1)]:
        start=perf_counter()
        r=subprocess.run([binpath,"run","-"],input=req,text=True,capture_output=True,check=False,timeout=90)
        rows[label].append(perf_counter()-start)
        assert r.returncode in (0,2),r.stderr
        observed[label]=json.loads(r.stdout)["records"]
    for old,new in zip(observed["powi"],observed["cached"],strict=True):
        assert old["status"]==new["status"]
        if old["status"]=="complete":
            max_error=max(max_error,abs(old["score"]-new["score"]))
assert max_error<1e-12
(ROOT/"evidence/power-cache.json").write_text(json.dumps({"candidates":len(pairs),"samples_seconds":rows,
    "median_speedup":median(rows["powi"])/median(rows["cached"]),"max_efficiency_delta":max_error},indent=2)+"\n")

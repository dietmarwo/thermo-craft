"""Rankine-cycle adapter; search log10 extraction pressures, minimize -efficiency."""
import sys
from pathlib import Path
import numpy as np

if not (Path(__file__).parent / "support.py").exists():
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "optimization-jobs/tutorials/domain-evaluators"))
from support import search


def configuration(case):
    return list(np.log10([2e4, 2e5])), list(np.log10([3e6, 7.5e6])), list(np.log10(case["parameters"]))


def decode(xs):
    return 10.0 ** np.asarray(xs)


def penalty(x):
    return 1.0 + max(0.0, x[0] - x[1])


def report(records):
    return {name + "_efficiency": row["metrics"]["efficiency"] if row["status"] == "complete" else None
            for name, row in records.items()}


if __name__ == "__main__":
    search(sys.modules[__name__])

"""Pair two compiled copies of examples/performance.rs and check semantic replay."""

import argparse
import json
import math
import os
import statistics
import subprocess


def equal(left, right, key=""):
    if isinstance(left, float) or isinstance(right, float):
        if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
            raise ValueError((key, left, right))
        absolute = 5e-7 if key.removesuffix("[]").endswith("_j_kg") else 1e-10
        if not math.isclose(left, right, rel_tol=5e-10, abs_tol=absolute):
            raise ValueError((key, left, right))
    elif isinstance(left, dict) and isinstance(right, dict) and left.keys() == right.keys():
        for k, value in left.items():
            equal(value, right[k], key + "." + k)
    elif isinstance(left, list) and isinstance(right, list) and len(left) == len(right):
        for a, b in zip(left, right, strict=True):
            equal(a, b, key + "[]")
    elif left != right:
        raise ValueError((key, left, right))


def api_name(scores, matrix):
    return "matrix" if matrix else "scores" if scores else "full"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before")
    parser.add_argument("after")
    parser.add_argument("fixture")
    parser.add_argument("workload", choices=("one", "serial", "parallel", "trace", "invalid", "domain", "domain2"))
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--before-scores", action="store_true")
    parser.add_argument("--after-scores", action="store_true")
    parser.add_argument("--before-matrix", action="store_true")
    parser.add_argument("--after-matrix", action="store_true")
    args = parser.parse_args()
    if args.samples < 1:
        parser.error("--samples must be positive")
    binaries = [args.before, args.after]
    scores = [args.before_scores, args.after_scores]
    matrix = [args.before_matrix, args.after_matrix]
    if any(a and b for a, b in zip(scores, matrix)):
        parser.error("choose scores or matrix mode per side, not both")

    def run(i, *extra):
        env = os.environ.copy()
        env.pop("CRAFT_SCORES", None)
        env.pop("CRAFT_MATRIX", None)
        if scores[i]:
            env["CRAFT_SCORES"] = "1"
        if matrix[i]:
            env["CRAFT_MATRIX"] = "1"
        return subprocess.check_output([binaries[i], args.fixture, args.workload, *extra], env=env)

    probes = [json.loads(run(i, "probe")) for i in range(2)]
    for p in probes:
        p.pop("version")
        if any(scores) or any(matrix):
            for row in p["records"]:
                row["metrics"] = None
        if any(matrix):
            # The matrix API reports status, steps and score only.
            for row in p["records"]:
                row["detail"] = None
    equal(*probes)
    samples = [[], []]
    for i in range(args.samples):
        for j in (0, 1) if i % 2 == 0 else (1, 0):
            samples[j].append(float(run(j)))
    medians = list(map(statistics.median, samples))
    # Each sample index holds one adjacent before/after pair, so this ratio is
    # robust to slow host-speed drift that can split the two medians.
    paired = statistics.median(b / a for b, a in zip(*samples, strict=True))
    print(json.dumps({"workload": args.workload,
                      "before_api": api_name(scores[0], matrix[0]),
                      "after_api": api_name(scores[1], matrix[1]),
                      "before_seconds": samples[0],
                      "after_seconds": samples[1], "medians_seconds": medians,
                      "speedup": medians[0] / medians[1],
                      "paired_median_speedup": paired}, indent=2))


if __name__ == "__main__":
    main()

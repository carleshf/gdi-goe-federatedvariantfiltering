#!/usr/bin/env python3
"""
FEM aggregator task -- the whole central side of the GoE analysis.

Reads the cohort count tables the client task published (goe-counts.<node>.csv,
delivered into this execution's sandbox by the FEM workflow), then does what
snakemake--workflow/orchestrator.py does:

    pool        global allele frequencies and the baseline intersection I0
    search      coarse scan over lambda, then hill climbing on F1
    score       Jaccard / recall / F1 per probed lambda

The one difference is where the per-round filtering runs. The original
orchestrator re-dispatches the node workflow every round, and each node runs
filter_bn on variant_counts/all_samples_counts.csv. That file is byte-for-byte
the round-0 table the node has already published, and filter_bn reads nothing
else apart from global_p, fst and lambda. So the aggregator applies the same
Balding-Nichols filter to the published tables and gets the same passing lists,
without a round trip per probe. That keeps the analysis a fan-in -- clients,
then one aggregator -- which is the only data flow an FEM workflow supports.
No additional data leaves any node.

Outputs, written to --out-dir:
    global_freq.json                              pooled frequencies
    rounds/<r>/<node>_round_<r>_passing.txt       what each node's filter passes
    metrics.json                                  full F1 curve and the best lambda
"""
import argparse
import csv
import glob
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from bn_math import balding_nichols_log_likelihood

EPSILON = 1e-6   # Numerical guard for F1 comparison
COUNTS_RE = re.compile(r"goe-counts\.(.+)\.csv$")


def load_counts(in_dir):
    """{node: [(Variant, AC, AN), ...]} in file order.

    Matches on the file-name suffix rather than exact names: FEM prefixes
    collected files with the sending node's name and strips up to the first
    "_", which for a node name containing "_" leaves part of it behind.
    """
    rows = {}
    for path in sorted(glob.glob(os.path.join(in_dir, "*goe-counts.*.csv"))):
        node = COUNTS_RE.search(os.path.basename(path)).group(1)
        if node in rows:
            sys.exit(f"two count tables for node {node!r} in {in_dir}")
        with open(path, newline='') as fh:
            rows[node] = [(r["Variant"], int(r["AC"]), int(r["AN"]))
                          for r in csv.DictReader(fh)]
    return rows


def pool_counts(rows):
    """Aggregate round-0 counts into global frequencies and the baseline I0.

    Same as orchestrator.pool_counts(): every country runs the same panel, so
    AN is pooled over every cohort, not just the countries that reported the
    variant. See the docstring there for why that decides whether the filter
    works at all.
    """
    cohort_an = {c: max(an for _, _, an in rs) for c, rs in rows.items()}
    total_an = sum(cohort_an.values())

    global_ac, present = {}, {}
    for country, rs in rows.items():
        have = set()
        for variant, ac, an in rs:
            if ac > 0:
                have.add(variant)
            global_ac[variant] = global_ac.get(variant, 0) + ac
        present[country] = have
        print(f"  -> {country}: {len(have)} variants with AC > 0, cohort AN {cohort_an[country]}")

        spread = {an for _, _, an in rs}
        if len(spread) > 1:
            print(f"     note: per-variant AN varies {min(spread)}-{max(spread)}, so the "
                  f"call rate is not uniform; {cohort_an[country]} is an upper bound")

    global_p = {v: ac / total_an for v, ac in global_ac.items()}
    return global_p, len(set.intersection(*present.values()))


def federation_id(countries, global_p):
    """Same hash as orchestrator.federation_id(), so ids are comparable."""
    h = hashlib.sha256()
    h.update(("\n".join(sorted(countries)) + "\n").encode())
    for variant in sorted(global_p):
        h.update(f"{variant}\t{global_p[variant]!r}\n".encode())
    return "f" + h.hexdigest()[:12]


def filter_bn(rows, global_p, fst, ll_thresh):
    """What wrappers/filter_bn/script.py writes for one node's cohort table."""
    passing = []
    for variant, ac, an in rows:
        if ac == 0:
            continue
        p = global_p.get(variant)
        if p is None:
            continue
        if balding_nichols_log_likelihood(ac, an, p, fst) >= ll_thresh:
            passing.append(variant)
    return passing


def score(sets, i0_size):
    """Jaccard / recall / F1 over the variant sets the countries pass."""
    I = set.intersection(*sets.values())
    U = set.union(*sets.values())
    jaccard = len(I) / len(U) if U else 0.0
    recall  = len(I) / i0_size if i0_size > 0 else 0.0
    f1      = 2 * jaccard * recall / (jaccard + recall) if (jaccard + recall) > 0 else 0.0
    return {"f1": f1, "jaccard": jaccard, "recall": recall,
            "intersection": len(I), "union": len(U),
            "per_country": {c: len(s) for c, s in sets.items()}}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in-dir", default="/sandbox",
                    help="where the goe-counts.<node>.csv tables were delivered (default: /sandbox)")
    ap.add_argument("--out-dir", default="/sandbox", help="default: /sandbox")
    ap.add_argument("--fst", type=float, default=0.01, help="Wright's F-statistic")
    ap.add_argument("--ll-min", type=float, default=-50.0, help="lower bound of the lambda range")
    ap.add_argument("--ll-max", type=float, default=0.0, help="upper bound of the lambda range")
    ap.add_argument("--coarse-steps", type=int, default=9,
                    help="thresholds scanned before refining; below 2 disables the scan")
    ap.add_argument("--step-min", type=float, default=0.5, help="convergence criterion")
    ap.add_argument("--lambda-0", type=float, default=-25.0,
                    help="start point, used only when the scan is disabled")
    ap.add_argument("--step-init", type=float, default=5.0,
                    help="initial step, used only when the scan is disabled")
    args = ap.parse_args()

    FST, LL_MIN, LL_MAX = args.fst, args.ll_min, args.ll_max
    STEP_MIN, COARSE_STEPS = args.step_min, args.coarse_steps

    rows = load_counts(args.in_dir)
    if len(rows) < 2:
        sys.exit(f"need count tables from at least 2 nodes in {args.in_dir}, found {sorted(rows)}")
    countries = list(rows)
    os.makedirs(args.out_dir, exist_ok=True)

    # -- Pool: global frequency reference ------------------------------------
    print(f"Pooling allele counts from {len(countries)} nodes...")
    print(f"  countries: {', '.join(countries)}")
    global_p, i0_size = pool_counts(rows)
    print(f"  -> pooled {len(global_p)} variants")
    print(f"  -> baseline intersection I0 = {i0_size} variants")

    fed_id = federation_id(countries, global_p)
    print(f"  -> federation id {fed_id}")

    with open(os.path.join(args.out_dir, "global_freq.json"), "w") as fh:
        json.dump(global_p, fh)

    rnd = 0
    history = []

    def probe(ll_thresh):
        nonlocal rnd
        rnd += 1
        out = os.path.join(args.out_dir, "rounds", str(rnd))
        os.makedirs(out, exist_ok=True)
        sets = {}
        for country, rs in rows.items():
            passing = filter_bn(rs, global_p, FST, ll_thresh)
            with open(os.path.join(out, f"{country}_round_{rnd}_passing.txt"), "w") as fh:
                fh.writelines(v + "\n" for v in passing)
            sets[country] = set(passing)
        metrics = score(sets, i0_size)
        metrics.update({"round": rnd, "ll_thresh": ll_thresh})
        history.append(metrics)
        return metrics

    head = (f"{'Round':>5} | {'lambda':>8} | {'F1':>8} | {'Jaccard':>8} | "
            f"{'Recall':>8} | {'Step':>6} | Outcome")

    def report(m, step, note):
        print(f"{m['round']:>5} | {m['ll_thresh']:>8.2f} | {m['f1']:>8.4f} | "
              f"{m['jaccard']:>8.4f} | {m['recall']:>8.4f} | {step:>6.2f} | {note}")

    # -- Phase 1: scan the whole range so the climb cannot start trapped -----
    if COARSE_STEPS >= 2:
        spacing = (LL_MAX - LL_MIN) / (COARSE_STEPS - 1)
        print(f"\nPhase 1 -- scanning {COARSE_STEPS} thresholds across "
              f"[{LL_MIN:g}, {LL_MAX:g}] (spacing {spacing:g})...")
        print(head)
        print("-" * len(head))

        scanned = []
        for i in range(COARSE_STEPS):
            m = probe(LL_MIN + spacing * i)
            scanned.append(m)
            report(m, spacing, "scan")
        top = max(m["f1"] for m in scanned)
        best = max((m for m in scanned if m["f1"] >= top - EPSILON),
                   key=lambda m: m["ll_thresh"])
        lambda_t, current, step = best["ll_thresh"], best, spacing / 2
        print(f"\nPhase 2 -- refining from lambda={lambda_t:g} (step={step:g})...")
        print(head)
        print("-" * len(head))
    else:
        lambda_t, step = args.lambda_0, args.step_init
        print(f"\nRefining from lambda={lambda_t:g} (step={step:g}), scan disabled...")
        print(head)
        print("-" * len(head))
        current = probe(lambda_t)
        best = current
        report(current, step, "init")

    direction = 1

    while step > STEP_MIN:
        lambda_new = min(LL_MAX, max(LL_MIN, lambda_t + direction * step))
        m = probe(lambda_new)
        arrow = "->" if direction > 0 else "<-"
        if m["f1"] > current["f1"] + EPSILON:
            lambda_t, current = lambda_new, m
            if m["f1"] > best["f1"]:
                best = m
            report(m, step, f"{arrow} accept")
        else:
            direction *= -1
            step /= 2
            report(m, step, f"{arrow} backtrack")

    print("-" * len(head))
    print(f"\nConverged after {rnd} rounds.")
    print(f"Optimal threshold: lambda* = {best['ll_thresh']:.2f}  (F1 = {best['f1']:.4f})")
    print(f"  Jaccard {best['jaccard']:.4f} | recall {best['recall']:.4f} | "
          f"intersection {best['intersection']} variants")

    if best["recall"] >= 1.0 - EPSILON:
        print("\n  WARNING: lambda* filters nothing (recall = 1.000) -- F1 is")
        print("  maximised by keeping every variant, so this is a degenerate")
        print("  optimum. Check the log-likelihood spread against the search")
        print("  range, and whether F1 is the right objective for this cohort.")
    for country, n in best["per_country"].items():
        print(f"  {country}: {n} variants passing")

    out = os.path.join(args.out_dir, "metrics.json")
    with open(out, "w") as fh:
        json.dump({"federation_id": fed_id, "fst": FST, "countries": countries,
                   "baseline_intersection": i0_size, "rounds": rnd,
                   "best": best, "history": history}, fh, indent=2)
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()

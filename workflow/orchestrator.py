"""
Central node -- federated round driver.

Runs the node-local workflow (Snakefile) at every participating country,
collects only what each country publishes, aggregates those partial results,
and derives the parameters for the next round. Repeats until convergence.

    Round 0      Each country publishes its own aggregated allele counts.
                 Central pools them into global allele frequencies and fixes
                 the baseline intersection I0 (the recall denominator).

    Round 1..N   Central broadcasts the pooled frequencies plus a threshold
                 lambda. Each country filters its own variants locally and
                 publishes the ones that pass. Central scores Jaccard /
                 recall / F1 and picks the next lambda by hill climbing:
                 step toward 0 while F1 improves, otherwise reverse and
                 halve the step.

    Converged    when step <= STEP_MIN.

Each round is driven by passing the round parameters to snakemake as --config
flags, so nothing has to be staged into the country's working directory. Those
parameters and the country's own VCFs are the workflow's only inputs.

Usage:
    python orchestrator.py

    SNAKEMAKE=/path/to/snakemake python orchestrator.py
"""
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys

ROOT       = os.path.dirname(os.path.abspath(__file__))
SNAKEFILE  = os.path.join(ROOT, "Snakefile")
NODES_ROOT = os.path.join(ROOT, "nodes")
CENTRAL    = os.path.join(ROOT, "central")


COUNTRIES = [c.strip() for c in
             os.environ.get("COUNTRIES", "Spain,Germany,Czechia").split(",") if c.strip()]

SNAKEMAKE = os.environ.get("SNAKEMAKE") or shutil.which("snakemake") or "snakemake"
CORES     = int(os.environ.get("CORES", 4))
USE_CONDA = os.environ.get("USE_CONDA", "") not in ("", "0", "false")


def setting(name, default):
    """Search constant, overridable from the environment for recalibration.

    The usable lambda range depends on cohort size: log-likelihoods scale with
    AN, so a range tuned for thousands of samples is all plateau for dozens.
    Check the spread before trusting the defaults.
    """
    return type(default)(os.environ.get(name, default))


FST       = setting("FST",       0.01)   # Wright's F-statistic
LL_MIN    = setting("LL_MIN",  -50.0)    # Lower bound of the lambda search range
LL_MAX    = setting("LL_MAX",    0.0)    # Upper bound of the lambda search range
LAMBDA_0  = setting("LAMBDA_0", -25.0)   # Start point when the scan is disabled
STEP_INIT = setting("STEP_INIT",  5.0)   # Step size when the scan is disabled
STEP_MIN  = setting("STEP_MIN",   0.5)   # Convergence criterion
EPSILON   = 1e-6                         # Numerical guard for F1 comparison
COARSE_STEPS = setting("COARSE_STEPS", 9)


def federation_id(global_p):
    """Short content hash identifying this federation generation.

    Derived from the participating countries and the pooled frequencies they
    produced, so it changes when a country joins or leaves AND when any
    country's own data changes. Round results are stored under it, so a new
    generation cannot reuse the previous one's filtering: there is simply
    nothing at those paths yet.

    This replaces relying on the frequency file getting a newer timestamp.
    Timestamps survive being copied, rsynced or restored from a backup, and
    snakemake's mtime trigger can be narrowed away by a profile -- either way
    the result would be a silently stale round. A path that differs cannot go
    stale. Re-running the same membership over unchanged data yields the same
    id and correctly reuses the earlier results.
    """
    h = hashlib.sha256()
    h.update(("\n".join(sorted(COUNTRIES)) + "\n").encode())
    for variant in sorted(global_p):
        h.update(f"{variant}\t{global_p[variant]!r}\n".encode())
    # Leading letter on purpose: this id travels as a --config value, and those
    # are YAML-parsed. An all-digit hash would come back as an int (losing any
    # leading zero) and one like "1e5000000000" would come back as infinity.
    return "f" + h.hexdigest()[:12]


def round_dir(fed_id, rnd):
    d = os.path.join(CENTRAL, fed_id, "rounds", str(rnd))
    os.makedirs(d, exist_ok=True)
    return d


def counts_dir():
    """Per-country counts are membership-independent, so they sit outside a
    generation directory and are collected once."""
    d = os.path.join(CENTRAL, "counts")
    os.makedirs(d, exist_ok=True)
    return d


def dispatch(rnd, params, deliverable, landing):
    """Run one round of the node-local workflow everywhere, then collect.

    Returns {country: path to the deliverable as landed on the central node}.
    """
    collected = {}
    for country in COUNTRIES:
        node_dir = os.path.join(NODES_ROOT, country)

        # Passed as flags rather than written to a config.json, so a node that
        # cannot have files staged into it still runs. The node reads its own
        # sample list off its own data directory, so no sample identifiers are
        # sent. --config goes last: it takes a variable number of values and
        # would otherwise swallow whatever followed.
        cmd = [SNAKEMAKE, "-s", SNAKEFILE, "-d", node_dir,
               "--cores", str(CORES)]
        if USE_CONDA:
            cmd.append("--use-conda")
        cmd += ["--config"] + [f"{k}={v}" for k, v in params.items()]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            output = (proc.stdout or "") + (proc.stderr or "")
            sys.stderr.write(f"\n----- {country}, round {rnd}: "
                             f"snakemake exited {proc.returncode} -----\n")
            sys.stderr.write(" ".join(cmd) + "\n\n")
            sys.stderr.write(output if output.strip()
                             else "(snakemake produced no output)\n")
            sys.stderr.write(f"----- end {country}, round {rnd} -----\n")
            raise SystemExit(f"round {rnd}: workflow failed at {country}")

        landed = os.path.join(landing, f"{country}_{os.path.basename(deliverable)}")
        shutil.copyfile(os.path.join(node_dir, deliverable), landed)
        collected[country] = landed
    return collected


def pool_counts(collected):
    """Aggregate round-0 counts into global frequencies and the baseline I0.

    Every country runs the same panel, so a variant missing from a country's
    counts means that country was sequenced at that site and saw no alt allele
    -- not that the site was never assayed. AN is therefore pooled over every
    cohort, not just the countries that reported the variant.

    That distinction decides whether the filter works at all. Pooling AN over
    reporting countries only gives a variant private to one country a global
    frequency identical to its own, which the Balding-Nichols likelihood scores
    as a perfect fit -- so singletons become the *last* thing the filter drops
    and concordant variants the first, and F1 ends up maximised by filtering
    nothing. Shared variants are unaffected either way.

    If countries ever run different panels, this becomes wrong: absence would
    then genuinely mean "not assayed", and AN would have to be pooled over the
    callable set per variant instead.
    """
    rows = {}
    for country, path in collected.items():
        with open(path, newline='') as fh:
            rows[country] = [(r["Variant"], int(r["AC"]), int(r["AN"]))
                             for r in csv.DictReader(fh)]

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


def score(collected, i0_size):
    """Jaccard / recall / F1 over the variant sets the countries published."""
    sets = {}
    for country, path in collected.items():
        with open(path) as fh:
            sets[country] = set(fh.read().split())

    I = set.intersection(*sets.values())
    U = set.union(*sets.values())
    jaccard = len(I) / len(U) if U else 0.0
    recall  = len(I) / i0_size if i0_size > 0 else 0.0
    f1      = 2 * jaccard * recall / (jaccard + recall) if (jaccard + recall) > 0 else 0.0
    return {"f1": f1, "jaccard": jaccard, "recall": recall,
            "intersection": len(I), "union": len(U),
            "per_country": {c: len(s) for c, s in sets.items()}}


def main():
    os.makedirs(CENTRAL, exist_ok=True)

    # -- Round 0: collect counts, build the global frequency reference --------
    print(f"Round 0 -- collecting allele counts from {len(COUNTRIES)} countries...")
    print(f"  countries: {', '.join(COUNTRIES)}")
    collected = dispatch(0, {"round": 0, "fst": FST, "ll_thresh": LAMBDA_0},
                         "federated_results/round_0_counts.csv", counts_dir())
    global_p, i0_size = pool_counts(collected)
    print(f"  -> pooled {len(global_p)} variants")
    print(f"  -> baseline intersection I0 = {i0_size} variants")


    fed_id = federation_id(global_p)
    fed_dir = os.path.join(CENTRAL, fed_id)
    os.makedirs(fed_dir, exist_ok=True)
    print(f"  -> federation id {fed_id}")

    freq_file = os.path.join(fed_dir, "global_freq.json")
    with open(freq_file, "w") as fh:
        json.dump(global_p, fh)

    rnd = 0
    history = []

    def probe(ll_thresh):
        nonlocal rnd
        rnd += 1
        collected = dispatch(rnd, {"round": rnd, "fst": FST,
                                   "ll_thresh": ll_thresh,
                                   "global_freq": freq_file,
                                   "fed_id": fed_id},
                             f"federated_results/{fed_id}/round_{rnd}_passing.txt",
                             round_dir(fed_id, rnd))
        metrics = score(collected, i0_size)
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
        lambda_t, step = LAMBDA_0, STEP_INIT
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
    print(f"\nConverged after {rnd} rounds ({rnd * len(COUNTRIES)} country workflow runs).")
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

    out = os.path.join(fed_dir, "metrics.json")
    with open(out, "w") as fh:
        json.dump({"federation_id": fed_id, "fst": FST, "countries": COUNTRIES,
                   "baseline_intersection": i0_size, "rounds": rnd,
                   "best": best, "history": history}, fh, indent=2)
    print(f"\nWrote {out}")

    index_file = os.path.join(CENTRAL, "federations.json")
    index = {}
    if os.path.exists(index_file):
        with open(index_file) as fh:
            index = json.load(fh)
    index[fed_id] = {"countries": COUNTRIES, "rounds": rnd,
                     "baseline_intersection": i0_size,
                     "best_ll_thresh": best["ll_thresh"], "best_f1": best["f1"]}
    with open(index_file, "w") as fh:
        json.dump(index, fh, indent=2)
    print(f"Wrote {index_file} ({len(index)} generation(s) recorded)")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
FEM client task -- publish this node's cohort allele counts.

Runs the node-local Snakemake workflow (round 0: extract_counts ->
aggregate_counts -> publish_counts) on the node's own VCFs and places exactly
one file in the output directory:

    goe-counts.<node>.csv       Variant, CHROM, POS, AC, AN for the whole cohort

Everything else -- per-sample count tables, Snakemake metadata, rule logs --
is written to a private working directory inside the container and discarded
with it. That matters under FEM: after the task finishes, every file in the
execution sandbox is listed and later shipped to the storage node, and so is
this container's stdout (FEM captures it into the sandbox as a log file). So
nothing individual-level may end up in either place. On success this script
prints only cohort-level totals.

The node name is embedded in the file name because FEM renames collected files
<node>_<file> and then strips everything up to the first "_" on the storage
node, so without it the countries' files would collide.

Usage:
    goe-client --node Spain [--data-dir /data] [--out-dir /sandbox] [--cores 1]
"""
import argparse
import csv
import os
import re
import shutil
import subprocess
import sys

SNAKEFILE = "/opt/goe/Snakefile"
DELIVERABLE = "federated_results/round_0_counts.csv"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--node", required=True,
                    help="this node's name; must match its FEM node name")
    ap.add_argument("--data-dir", default="/data",
                    help="directory holding <sample>.vcf.gz (default: /data)")
    ap.add_argument("--out-dir", default="/sandbox",
                    help="FEM execution sandbox as mounted in the container (default: /sandbox)")
    ap.add_argument("--work-dir", default="/tmp/goe-work",
                    help="private working directory, never published (default: /tmp/goe-work)")
    ap.add_argument("--cores", type=int, default=1)
    args = ap.parse_args()

    if not re.fullmatch(r"[A-Za-z0-9._-]+", args.node):
        sys.exit(f"--node {args.node!r}: use letters, digits, '.', '_' or '-' only")
    if not os.path.isdir(args.data_dir):
        sys.exit(f"--data-dir {args.data_dir!r} does not exist")

    work = os.path.abspath(args.work_dir)
    os.makedirs(work, exist_ok=True)
    log_path = os.path.join(work, "snakemake.log")

    # fst and ll_thresh are required by the Snakefile's config check but not
    # read in round 0.
    cmd = ["snakemake", "-s", SNAKEFILE, "-d", work, "--cores", str(args.cores),
           "--config", "round=0", "fst=0.01", "ll_thresh=0",
           f"data_dir={os.path.abspath(args.data_dir)}"]

    with open(log_path, "w") as log:
        proc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT)

    if proc.returncode != 0:
        # Only on failure: the tail may name samples, but without it a failed
        # run cannot be diagnosed.
        with open(log_path) as log:
            tail = log.readlines()[-40:]
        sys.stderr.write("".join(tail))
        sys.exit(f"snakemake exited {proc.returncode}")

    os.makedirs(args.out_dir, exist_ok=True)
    published = os.path.join(args.out_dir, f"goe-counts.{args.node}.csv")
    shutil.copyfile(os.path.join(work, DELIVERABLE), published)

    with open(published, newline="") as fh:
        rows = list(csv.DictReader(fh))
    cohort_an = max((int(r["AN"]) for r in rows), default=0)
    print(f"[goe-client] node={args.node} variants={len(rows)} "
          f"cohort_AN={cohort_an} -> {os.path.basename(published)}")


if __name__ == "__main__":
    main()

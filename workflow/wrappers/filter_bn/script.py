######################################
# wrapper for rule: filter_bn
######################################
import os
import sys
import csv
import json
from snakemake.shell import shell

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from bn_math import balding_nichols_log_likelihood

log_filename = str(snakemake.log)

f = open(log_filename, 'wt')
f.write("\n##\n## wrapper: filter_bn \n##\n")
f.close()

shell.executable("/bin/bash")

fst = float(snakemake.params.fst)
ll_thresh = float(snakemake.params.ll_thresh)

# The central node's pooled allele frequencies. This is the only thing from
# outside the node that the filter sees -- no other node's counts are read.
with open(str(snakemake.input.global_freq)) as gf:
    global_p = json.load(gf)
if "global_p" in global_p:
    global_p = global_p["global_p"]

tested = 0
passing = 0
with open(str(snakemake.input.counts), newline='') as cf, \
     open(str(snakemake.output.passing), "w") as out:
    for row in csv.DictReader(cf):
        ac, an = int(row["AC"]), int(row["AN"])
        if ac == 0: continue
        p = global_p.get(row["Variant"])
        if p is None: continue
        tested += 1
        if balding_nichols_log_likelihood(ac, an, p, fst) >= ll_thresh:
            passing += 1
            out.write(row["Variant"] + "\n")

f = open(log_filename, 'at')
f.write("## FST: " + str(fst) + "\n")
f.write("## LL_THRESH: " + str(ll_thresh) + "\n")
f.write("## GLOBAL_FREQ: " + str(snakemake.input.global_freq) + "\n")
f.write("## TESTED: " + str(tested) + "\n")
f.write("## PASSING: " + str(passing) + "\n")
f.close()

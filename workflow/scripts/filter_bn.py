"""Country-side Balding-Nichols filter for one round.

Reads the country's own aggregated counts plus the global allele frequencies
broadcast by the central node, and writes the variants that pass. No other
country's data is read -- params.json is the only external input, which is
what makes this safe to run behind a country's firewall.

usage: filter_bn.py <local_counts.csv> <params.json> <out_passing.txt>
"""
import sys, csv, json
from bn_math import balding_nichols_log_likelihood

if len(sys.argv) != 4:
    sys.exit("usage: filter_bn.py <local_counts.csv> <params.json> <out_passing.txt>")

local_csv, params_file, out_txt = sys.argv[1], sys.argv[2], sys.argv[3]

with open(params_file) as pf:
    params = json.load(pf)
fst, ll_thresh, global_p = float(params["fst"]), float(params["ll_thresh"]), params["global_p"]

with open(local_csv, newline='') as cf, open(out_txt, "w") as out:
    for row in csv.DictReader(cf):
        ac, an = int(row["AC"]), int(row["AN"])
        if ac == 0: continue
        p = global_p.get(row["Variant"])
        if p is None: continue
        if balding_nichols_log_likelihood(ac, an, p, fst) >= ll_thresh:
            out.write(row["Variant"] + "\n")

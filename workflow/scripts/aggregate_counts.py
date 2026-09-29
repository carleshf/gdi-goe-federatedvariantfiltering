"""Sum per-sample allele counts into one country-level counts table.

Stays inside the country: the per-sample rows are individual-level, only the
summed table is a candidate for publication.

usage: aggregate_counts.py <out_counts.csv> <in_counts.csv> [<in_counts.csv> ...]
"""
import sys, csv

if len(sys.argv) < 3:
    sys.exit("usage: aggregate_counts.py <out_counts.csv> <in_counts.csv> [...]")

out_csv, in_csvs = sys.argv[1], sys.argv[2:]

aggregated = {}
for path in in_csvs:
    with open(path, newline='') as cf:
        for row in csv.DictReader(cf):
            vk = row["Variant"]
            if vk not in aggregated:
                aggregated[vk] = {"CHROM": row["CHROM"], "POS": row["POS"], "AC": 0, "AN": 0}
            aggregated[vk]["AC"] += int(row["AC"])
            aggregated[vk]["AN"] += int(row["AN"])

with open(out_csv, "w", newline='') as cf:
    writer = csv.writer(cf)
    writer.writerow(["Variant", "CHROM", "POS", "AC", "AN"])
    for k in sorted(aggregated.keys(), key=lambda k: (aggregated[k]["CHROM"], int(aggregated[k]["POS"]))):
        writer.writerow([k, aggregated[k]["CHROM"], aggregated[k]["POS"], aggregated[k]["AC"], aggregated[k]["AN"]])

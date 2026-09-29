######################################
# wrapper for rule: aggregate_counts
######################################
import os
import csv
from snakemake.shell import shell

log_filename = str(snakemake.log)

f = open(log_filename, 'wt')
f.write("\n##\n## wrapper: aggregate_counts \n##\n")
f.close()

shell.executable("/bin/bash")

aggregated = {}
for path in snakemake.input.counts:
    with open(str(path), newline='') as cf:
        for row in csv.DictReader(cf):
            vk = row["Variant"]
            if vk not in aggregated:
                aggregated[vk] = {"CHROM": row["CHROM"], "POS": row["POS"], "AC": 0, "AN": 0}
            aggregated[vk]["AC"] += int(row["AC"])
            aggregated[vk]["AN"] += int(row["AN"])

with open(str(snakemake.output.counts), "w", newline='') as cf:
    writer = csv.writer(cf)
    writer.writerow(["Variant", "CHROM", "POS", "AC", "AN"])
    for k in sorted(aggregated.keys(), key=lambda k: (aggregated[k]["CHROM"], int(aggregated[k]["POS"]))):
        writer.writerow([k, aggregated[k]["CHROM"], aggregated[k]["POS"],
                         aggregated[k]["AC"], aggregated[k]["AN"]])

f = open(log_filename, 'at')
f.write("## SAMPLES: " + str(len(snakemake.input.counts)) + "\n")
f.write("## OUTPUT: " + str(snakemake.output.counts) + "\n")
f.write("## VARIANTS: " + str(len(aggregated)) + "\n")
f.close()

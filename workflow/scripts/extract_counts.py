import sys, gzip, csv

def parse_vcf_for_counts(file_path):
    variants = {}
    open_func = gzip.open if file_path.endswith(".gz") else open
    with open_func(file_path, "rt") as f:
        for line in f:
            if line.startswith("#"): continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 10 or parts[4] in ("<NON_REF>", "."): continue
            chrom, pos, ref, alt_field = parts[0], parts[1], parts[3], parts[4]
            format_keys = parts[8].split(":")
            if "GT" not in format_keys: continue
            gt_idx = format_keys.index("GT")
            alt_ac, an = {}, 0
            for sample in parts[9:]:
                gt_fields = sample.split(":")
                if gt_idx >= len(gt_fields): continue
                alleles = gt_fields[gt_idx].replace("|", "/").split("/")
                called = [a for a in alleles if a != "."]
                if not called: continue
                an += len(called)
                for a in called:
                    alt_ac[a] = alt_ac.get(a, 0) + 1
            if an == 0: continue
            for i, alt in enumerate(alt_field.split(","), start=1):
                if alt in ("<NON_REF>", "*", "."): continue
                vk = f"{chrom}:{pos}:{ref}:{alt}"
                if vk not in variants: variants[vk] = {"CHROM": chrom, "POS": pos, "AC": 0, "AN": 0}
                variants[vk]["AC"] += alt_ac.get(str(i), 0)
                variants[vk]["AN"] += an
    return variants

if len(sys.argv) != 3:
    sys.exit("usage: extract_counts.py <sample.vcf[.gz]> <out_counts.csv>")

vcf_file, out_csv = sys.argv[1], sys.argv[2]
counts = parse_vcf_for_counts(vcf_file)

with open(out_csv, "w", newline='') as cf:
    writer = csv.writer(cf)
    writer.writerow(["Variant", "CHROM", "POS", "AC", "AN"])
    for k in sorted(counts.keys(), key=lambda k: (counts[k]["CHROM"], int(counts[k]["POS"]))):
        writer.writerow([k, counts[k]["CHROM"], counts[k]["POS"], counts[k]["AC"], counts[k]["AN"]])

import sys, os, json, pandas as pd

csv_files, txt_files, out_json = sys.argv[1:4], sys.argv[4:7], sys.argv[7]
baseline_sets = [(set(pd.read_csv(cf)[pd.read_csv(cf)["AC"]>0]["Variant"]) if os.path.exists(cf) else set()) for cf in csv_files]
I_0_size = len(baseline_sets[0] & baseline_sets[1] & baseline_sets[2]) if len(baseline_sets)==3 else 0

filtered_sets = [(set(open(tf).read().splitlines()) if os.path.exists(tf) else set()) for tf in txt_files]
I = filtered_sets[0] & filtered_sets[1] & filtered_sets[2]
U = filtered_sets[0] | filtered_sets[1] | filtered_sets[2]

jaccard = len(I) / len(U) if len(U) > 0 else 0.0
recall = len(I) / I_0_size if I_0_size > 0 else 0.0
f1 = 2.0 * (jaccard * recall) / (jaccard + recall) if (jaccard + recall) > 0.0 else 0.0

with open(out_json, "w") as f:
    json.dump({"Spain_variants": len(filtered_sets[0]), "Germany_variants": len(filtered_sets[1]), "Czechia_variants": len(filtered_sets[2]), "Intersection": len(I), "Baseline_Intersection": I_0_size, "Jaccard": jaccard, "Recall": recall, "F1": f1}, f)

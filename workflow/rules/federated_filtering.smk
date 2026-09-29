##### Per-sample allele counts #####
# Individual-level. Stays on the node, never published.

rule extract_counts:
    input:  vcf = os.path.join(DATA_DIR, "{sample}.vcf.gz")
    output: counts = "variant_counts/{sample}.csv"
    log:    "logs/extract_counts/{sample}.log"
    threads: 1
    conda:  "../wrappers/extract_counts/env.yaml"
    script: "../wrappers/extract_counts/script.py"

rule aggregate_counts:
    input:  counts = expand("variant_counts/{sample}.csv", sample = sample_tab.sample_name)
    output: counts = "variant_counts/all_samples_counts.csv"
    log:    "logs/aggregate_counts/all_samples.log"
    threads: 1
    conda:  "../wrappers/aggregate_counts/env.yaml"
    script: "../wrappers/aggregate_counts/script.py"

rule publish_counts:
    input:  counts = "variant_counts/all_samples_counts.csv"
    output: counts = "federated_results/round_{round}_counts.csv"
    log:    "logs/publish_counts/round_{round}.log"
    threads: 1
    shell:  "cp {input.counts} {output.counts} 2> {log}"

rule filter_bn:
    input:  counts = "variant_counts/all_samples_counts.csv",
            global_freq = lambda wildcards: global_freq
    output: passing = "federated_results/{fed}/round_{round}_passing.txt"
    log:    "logs/filter_bn/{fed}/round_{round}.log"
    threads: 1
    params: fst = fst,
            ll_thresh = ll_thresh
    conda:  "../wrappers/filter_bn/env.yaml"
    script: "../wrappers/filter_bn/script.py"

# Part 1 - GoE Workflow Description

The workflow in [`workflow/`](../workflow/) runs a **federated
search for a variant-filtering threshold**. Each country keeps its genotypes and
publishes only aggregates. A central node pools those aggregates and runs
repeated rounds to find the log-likelihood threshold λ that gives the best
cross-country agreement on which variants are called.

The code splits cleanly into two roles:

- **Client / trainer side:**
  [`Snakefile`](../workflow/Snakefile),
  [`rules/federated_filtering.smk`](../workflow/rules/federated_filtering.smk)
  and [`wrappers/`](../workflow/wrappers/). The same Snakefile runs
  unchanged at every country.
- **Server / aggregator side:**
  [`orchestrator.py`](../workflow/orchestrator.py), a plain Python 3
  script that uses only the standard library.

## How a run works

```
            CENTRAL (orchestrator.py)                      COUNTRY NODE (Snakefile), ×N
 Round 0    dispatch(round=0) ───────────────────────────▶ extract_counts (per sample)
                                                           aggregate_counts (cohort AC/AN)
            ◀─────────────── round_0_counts.csv ────────── publish_counts
            pool_counts → global_p, baseline I₀
            federation_id(countries, global_p) → fed_id
            write central/<fed_id>/global_freq.json

 Round 1..N dispatch(round=r, λ, global_freq, fed_id) ───▶ filter_bn (Balding–Nichols LL ≥ λ)
            ◀──────────── round_r_passing.txt ─────────── (list of variant IDs)
            score → Jaccard, recall, F1
            choose next λ (coarse scan, then hill-climb)
            repeat until step ≤ STEP_MIN
            write metrics.json and federations.json
```

The node decides what to build from `round` alone:

- **Round 0** builds `federated_results/round_0_counts.csv`.
- **Round ≥ 1** builds `federated_results/<fed_id>/round_<r>_passing.txt`.

## Client / trainer steps (run at each country)

| Rule | What it does | Output | Leaves the node? |
|---|---|---|---|
| `extract_counts` | Parses each `genomic_varcalls/<sample>.vcf.gz` and counts alt alleles (`AC`) and called alleles (`AN`) per variant | `variant_counts/<sample>.csv` | **No** (per-person data) |
| `aggregate_counts` | Adds up `AC` and `AN` over all samples in the cohort | `variant_counts/all_samples_counts.csv` | No |
| `publish_counts` (round 0) | Copies the cohort table into the deliverable folder | `federated_results/round_0_counts.csv` | **Yes**: cohort-level `AC`/`AN` per variant |
| `filter_bn` (round ≥ 1) | For each local variant with `AC > 0`, computes the Balding–Nichols beta-binomial log-likelihood of the local `AC`/`AN` given the central `global_p` and `fst`, and keeps the variant if the score is ≥ λ ([`bn_math.py`](../workflow/wrappers/filter_bn/bn_math.py)) | `federated_results/<fed_id>/round_<r>_passing.txt` | **Yes**: a list of variant IDs |

Samples are discovered automatically from `<data_dir>/*.vcf.gz`, so sample IDs
never have to be sent to the node. The per-sample counting runs only once; in
later rounds only `filter_bn` runs again, because the cohort table already
exists.

## Server / aggregator steps (`orchestrator.py`)

1. **`dispatch()`**: runs
   `snakemake -s Snakefile -d nodes/<Country> --config …` for each country in
   turn, then copies back the deliverable. The transport is currently just a
   shared filesystem.
2. **`pool_counts()`** (after round 0):
   - Computes `global_p = ΣAC / ΣAN`. `AN` is summed over **every** cohort,
     because the code assumes all countries run the same panel.
   - Computes the baseline `I₀`: the variants with `AC > 0` in all countries.
3. **`federation_id()`**: hashes the country list and `global_p` into an ID
   such as `f244330a464d9`. Round results are stored under this ID, so a change
   in membership or data automatically gives fresh paths.
4. **`score()`** (after each round ≥ 1), using the intersection `I` and union
   `U` of the passing lists:
   - `Jaccard = |I| / |U|`
   - `recall = |I| / |I₀|`
   - `F1` is their harmonic mean.
5. **λ search**:
   - Phase 1 is a coarse scan: `COARSE_STEPS` evenly spaced values of λ over
     `[LL_MIN, LL_MAX]`.
   - Phase 2 is a hill climb from the best of those. It keeps stepping while F1
     improves; otherwise it reverses direction and halves the step. It stops
     when `step ≤ STEP_MIN`.
6. **Outputs**: `central/<fed_id>/global_freq.json`,
   `central/<fed_id>/metrics.json` (full history plus the best λ) and
   `central/federations.json`. A warning is printed if the best λ has
   `recall = 1`, meaning it filters nothing.

## Parameters

**Node workflow** (`--config key=value`, or an optional `config.json` in the
node directory):

| Key | Required | Notes |
|---|---|---|
| `round` | always | `0` publishes counts; `≥ 1` publishes the passing variants |
| `fst` | always | Wright's F_ST, used in the Balding–Nichols model |
| `ll_thresh` | always | λ for this round (required even in round 0, where it is not used) |
| `global_freq` | round ≥ 1 | Path to the central `global_freq.json` |
| `fed_id` | optional | Defaults to `adhoc`; sets the output subfolder |
| `data_dir` | optional | Defaults to `genomic_varcalls` |
| `samples` | optional | A list or a `{key: {sample_name: …}}` block; otherwise discovered from `data_dir` |

Example, running round 1 at one node:

```bash
cd workflow/nodes/Spain
snakemake -s ../../Snakefile --cores 4 \
  --config round=1 fst=0.01 ll_thresh=-9.375 \
          global_freq=/path/global_freq.json fed_id=f244330a464d9
```

**Orchestrator** (environment variables):

| Variable | Default | Meaning |
|---|---|---|
| `COUNTRIES` | `Spain,Germany,Czechia` | Participating countries |
| `SNAKEMAKE` | `which snakemake` | Snakemake binary |
| `CORES` | `4` | Cores per country run |
| `USE_CONDA` | off | Pass `--use-conda` to Snakemake |
| `FST` | `0.01` | Wright's F_ST |
| `LL_MIN`, `LL_MAX` | `-50.0`, `0.0` | λ search range |
| `COARSE_STEPS` | `9` | Thresholds scanned before refining; below 2 disables the scan |
| `STEP_MIN` | `0.5` | Convergence criterion |
| `LAMBDA_0`, `STEP_INIT` | `-25.0`, `5.0` | Start point and step, used only when the scan is disabled |

The last recorded run
([`central/federations.json`](../workflow/central/federations.json))
took 13 rounds and found λ\* = −9.375 with F1 = 0.857 and `I₀` = 391.

## Notes

- **Data crossing borders.** Only two kinds of data move:
  - node → central: cohort `AC`/`AN` tables and lists of variant IDs
  - central → node: `global_p` and λ

  Genotypes and per-sample tables stay local. Cohort-level counts can still be
  sensitive, for example for rare variants in small cohorts, which matters for
  privacy review.
- **λ range and cohort size.** The log-likelihood grows with `AN`, so the λ
  range has to be calibrated to cohort size. At 60 samples per country the
  useful range is about [−15, −5].
- **Missing `config.json` template.** The workflow's own README lists a
  `config.json` template, but no such file exists. That is harmless, because
  every setting can be passed as a flag.
- **Legacy scripts.** `scripts/` holds old copies of the wrapper code; only
  `make_mock_data.py` is still used.
- **Snakemake version.** `min_version("5.18.0")` is left over from an earlier
  version. The workflow has only been tested on Snakemake 9.23.1, and it needs
  `pandas` for building the sample table.

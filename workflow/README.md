# Federated Variant Filtering

Cross-border variant concordance filtering in which no country's genotypes ever
leave its own machine.

Each participating country runs the same Snakemake workflow on its own private
VCFs and publishes only aggregate results. A central node pools those
aggregates, derives a new parameter, and asks every country to run again. This
repeats until the search converges.

Currently configured for three countries — **Spain**, **Germany** and
**Czechia** — running on simulated data over a shared panel.

## The method

Each country holds per-sample VCFs. The quantity of interest is a
log-likelihood threshold λ that maximises cross-country concordance of called
variants.

**Round 0.** Every country counts alternate alleles across its own cohort and
publishes one aggregate table: `AC` and `AN` per variant. The central node
pools these into global allele frequencies `global_p`, and records the
three-way intersection of variants with `AC > 0` as the baseline `I₀`.

**Rounds 1..N.** The central node broadcasts `global_p` and a candidate λ.
Each country scores its own variants against the pooled frequency with a
Balding–Nichols beta-binomial likelihood and publishes the list of variants
that clear λ. The central node computes

- `Jaccard = |I| / |U|` — three-way concordance
- `recall  = |I| / |I₀|` — retention against the unfiltered baseline
- `F1` — their harmonic mean

then picks the next λ. It first scans the whole range coarsely, then refines by
hill climbing: step toward 0 while F1 improves, otherwise reverse direction and
halve the step. Convergence is `step <= STEP_MIN`.

Only two kinds of data cross a border: the aggregate `AC`/`AN` tables, and
lists of variant identifiers. Individual genotypes and per-sample count tables
stay inside the country.

## Requirements

- **Snakemake**, with `pyyaml` and `pandas` available to it. Verified on
  **9.23.1** only. The `Snakefile` declares `min_version("5.18.0")`, which is a
  leftover and understates what has actually been tested.
- **Python 3.9+** for the orchestrator (standard library only).
- The workflow wrappers are standard-library only — no `numpy`, `scipy` or
  `pandas`. `pandas` is needed only by the `Snakefile` itself, to build the
  sample table.

On the CEITEC dev machine this repo was built on, the `conda` **base**
environment cannot run this: its `numpy` is broken (missing
`libgfortran.5.dylib`) and its `snakemake` aborts at startup because
`parse_config` imports `yaml`, which is not installed. Use an environment that
works and point `SNAKEMAKE` at it:

```bash
export SNAKEMAKE=~/miniforge3/envs/pudu/bin/snakemake
```

`shutil.which("snakemake")` resolves to the broken base-env binary, so
**setting `SNAKEMAKE` explicitly is currently required.**

## Running it

### The whole federation

```bash
python3 scripts/make_mock_data.py 60 400 60      # simulated data, first time only

SNAKEMAKE=~/miniforge3/envs/pudu/bin/snakemake \
  python3 orchestrator.py
```

Roughly 85 seconds for 3 countries × 60 samples: 13 rounds, 39 workflow runs.

### One country, by hand

A country needs only its own VCFs. Everything else arrives as flags, so
**nothing has to be staged into the node** — no config file required:

```bash
cd nodes/Spain

# round 0: publish allele counts
snakemake -s ../../Snakefile --cores 4 \
  --config round=0 fst=0.01 ll_thresh=-10.0

# any later round: filter against the central node's frequencies
snakemake -s ../../Snakefile --cores 4 \
  --config round=1 fst=0.01 ll_thresh=-9.375 \
          global_freq=/path/to/global_freq.json fed_id=f244330a464d9
```

The round number decides what gets produced, so no target argument is needed.
A country joining late does not replay earlier rounds — asking for any round
builds the local counts first if they are not there yet.

If a `config.json` *is* present in the working directory it is loaded, and
`--config` overrides individual keys on top of it. Both paths work.

## Layout

```
Snakefile                          node-side workflow; the same file runs everywhere
rules/federated_filtering.smk      the four rules
wrappers/<step>/script.py          per-rule implementation (+ env.yaml)
wrappers/filter_bn/bn_math.py      Balding-Nichols likelihood
config.json                        per-node config template
orchestrator.py                    central node: rounds, aggregation, convergence
scripts/make_mock_data.py          generates the simulated per-country data

nodes/<Country>/
  genomic_varcalls/<sample>.vcf.gz   private input, never leaves the node
  variant_counts/                    per-sample and cohort counts, stays local
  federated_results/                 what the central node collects
  logs/                              per-rule logs

central/
  counts/<Country>_round_0_counts.csv    pooled once, membership-independent
  <fed_id>/global_freq.json              frequencies broadcast to the countries
  <fed_id>/rounds/<r>/                   collected round results
  <fed_id>/metrics.json                  full F1 curve and the best threshold
  federations.json                       index of every generation run
```

## Configuration

Every setting can be given either as a `--config key=value` flag or in a
`config.json` in the working directory. The file is optional; if present it is
loaded first and flags override it.

| key | required | meaning |
|---|---|---|
| `round` | yes | `0` publishes allele counts; `≥1` publishes passing variants |
| `fst` | yes | Wright's F-statistic (population differentiation) |
| `ll_thresh` | yes | this round's λ |
| `global_freq` | from round 1 | path to the central node's pooled frequencies |
| `fed_id` | no | federation generation (see below); defaults to `adhoc` |
| `samples` | no | sample list; discovered from `data_dir` if omitted |
| `data_dir` | no | where this node's VCFs live; defaults to `genomic_varcalls` |
| `task_name`, `entity_name` | no | run identity for traceability; not read by the workflow |

**Samples are discovered, not configured.** With no `samples` given, the
workflow lists `<data_dir>/*.vcf.gz` and uses those names. That needs nothing
staged and means sample identifiers never have to travel. If you do want to
supply them, either form works:

- a `config.json` block — `{"Spain_001": {"sample_name": "Spain_001"}, ...}`;
  keys are free-form, only `sample_name` is read, so numeric database IDs are fine
- a flag — `--config samples="[Spain_001, Spain_002]"`

### A note on `--config` values

They are parsed as **YAML**, not taken as strings. Numbers arrive as numbers
(`ll_thresh=-9.375` becomes a float), which is convenient, but it also means a
value that merely *looks* numeric gets converted: `012345678901` arrives as the
integer `12345678901` with the leading zero gone, and `1e5000000000` arrives as
infinity. This is why `federation_id()` prefixes its hash with `f` — a
federation id has to survive the trip as an exact string, and a bare 12-char
hex hash could occasionally be all digits.

The orchestrator's search is tuned through the environment:

| variable | default | meaning |
|---|---|---|
| `COUNTRIES` | `Spain,Germany,Czechia` | participating countries |
| `SNAKEMAKE` | `which snakemake` | snakemake binary (see Requirements) |
| `CORES` | `4` | cores per country run |
| `USE_CONDA` | off | pass `--use-conda` to snakemake |
| `FST` | `0.01` | Wright's F-statistic |
| `LL_MIN`, `LL_MAX` | `-50.0`, `0.0` | λ search range |
| `COARSE_STEPS` | `9` | thresholds scanned before refining; `0` disables the scan |
| `STEP_MIN` | `0.5` | convergence criterion |
| `LAMBDA_0`, `STEP_INIT` | `-25.0`, `5.0` | start point and step, used only when the scan is disabled |

## Adding or removing a country

Set `COUNTRIES` and re-run:

```bash
COUNTRIES="Spain,Germany,Czechia,Portugal" \
SNAKEMAKE=~/miniforge3/envs/pudu/bin/snakemake python3 orchestrator.py
```

Everything that depends on the pooled frequencies is recomputed, and nothing
that does not is touched. This is enforced structurally rather than by
timestamps. `federation_id()` hashes the country list together with the pooled
frequencies into a short id, and all round results live under it:

- A country joining or leaving, **or any country changing its own data**, yields
  a different id and therefore a fresh set of paths. There is nothing at those
  paths to reuse, so no round can be silently stale.
- Re-running the same membership over unchanged data yields the same id and
  correctly reuses the previous results.
- Per-sample counts sit outside the generation directory, so adding a country
  never re-parses anyone's VCFs.

Old generations are kept rather than overwritten, and `central/federations.json`
records which membership produced which result:

```
244330a464d9  Spain,Germany,Czechia   rounds=13  lambda*= -9.38  F1=0.8571
```

## Things to know before trusting a result

**The λ range must be calibrated to cohort size.** Log-likelihoods scale with
`AN`, so a range tuned for thousands of samples is entirely plateau for dozens.
At 60 samples per country the discriminating region is roughly λ ∈ [−15, −5];
the default `[-50, 0]` works but spends most of its scan in the flat region. At
6 samples per country the whole likelihood spread was [−4, −1] and no setting
in the default range distinguished anything.

**A degenerate optimum is reported explicitly.** F1 as defined can be maximised
by filtering nothing at all: `recall = |I|/|I₀| = 1` exactly when no baseline
variant is removed. If the best threshold has `recall = 1.000`, the orchestrator
prints a `WARNING` — the answer is a statement about the objective, not an
operating point worth acting on.

**Pooling assumes a shared panel.** `pool_counts()` treats a variant absent
from a country's table as *sequenced there, no alternate allele seen*, and
pools `AN` over every cohort. This matters more than it looks: pooling `AN` over
only the reporting countries gives a variant private to one country a global
frequency identical to its own, which the likelihood scores as a perfect fit —
so singletons become the last thing the filter drops and concordant variants the
first, and F1 ends up maximised by doing nothing. If countries ever run
*different* panels, absence genuinely means "not assayed" and this inverts:
`AN` would then have to be pooled over the callable set per variant.

Cohort size is taken as `max(AN)` in each published table. With a uniform call
rate that is exact; if a country's per-variant `AN` varies, the orchestrator
says so and treats the value as an upper bound.

## Known limitations

**Transport is a shared filesystem.** The orchestrator drives each country with
`snakemake -d nodes/<Country>` and copies deliverables by file. The workflow
itself assumes nothing about this — a real country runs the same file on its own
machine and returns its deliverable by whatever means it likes — but the
orchestrator would need a real transport.

**`scripts/` holds superseded copies.** `extract_counts.py`,
`aggregate_counts.py`, `filter_bn.py` and `bn_math.py` predate the move to
`wrappers/` and are no longer referenced by the workflow;
`scripts/evaluate_metrics.py` was replaced by `score()` in the orchestrator and
is the last file importing `pandas`. Only `scripts/make_mock_data.py` is live.

## Simulated data

```bash
python3 scripts/make_mock_data.py [n_samples] [n_shared] [n_private]
```

Defaults to 6 samples, 300 shared and 40 private variants per country; the runs
quoted here used `60 400 60`. All countries share one pool of variants at a
common underlying frequency, each drifts away from it, and each carries variants
nobody else has — which is what gives the filter something to distinguish. The
seed is fixed, so runs are reproducible.

This script would not exist on a real central node: the data would already be
inside each country and would never move.

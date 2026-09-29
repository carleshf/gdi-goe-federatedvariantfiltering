# GoE federated comparison on FEM

Container packaging of the GoE federated variant filtering workflow
([`workflow/`](workflow/), described in
[`docs/workflow-description.md`](docs/workflow-description.md)) for the
Federated Execution Manager
([`fem-orchestrator`](https://gitlab.bsc.es/fl/fem-orchestrator),
[`fem-client`](https://gitlab.bsc.es/fl/fem-client)). It produces the same analysis, with the same
λ\*, F1 and per-round passing lists, as `orchestrator.py`.

| Image | Runs on | FEM tool | Does |
|---|---|---|---|
| `goe-fedcomp-client` | every data node | `goe-counts` | Runs the unchanged Snakemake workflow (round 0) on the node's VCFs and publishes `goe-counts.<node>.csv` (cohort `AC`/`AN` per variant) |
| `goe-fedcomp-aggregator` | the central / storage node only | `goe-aggregate` | Pools frequencies, runs the coarse scan and hill climb, scores each λ and writes `global_freq.json`, `rounds/` and `metrics.json` |

## Why two steps instead of 13 rounds

An FEM workflow is a sequence of tools. When a tool depends on another, the
orchestrator collects the earlier tool's output files from every node and
delivers them to **one** storage node (`workflow_storage_node`). Files only flow
inward, and there is no loop. The original protocol needs the opposite
direction in every round, because the central `global_freq.json` and λ go back
to every country.

That round trip turns out to be unnecessary. In rounds ≥ 1 each node runs
`filter_bn` on `variant_counts/all_samples_counts.csv`. That file is the
round-0 table the node has already published, and `filter_bn` reads nothing
else apart from `global_p`, `fst` and λ. So the aggregator applies the same
filter to the published tables and gets the same passing lists. The outcome:

- The results are identical. [`test_local.sh`](test_local.sh) checks
  `metrics.json` field by field against the reference run, and all 39
  reference passing lists and `global_freq.json` also match.
- Clients run once rather than once per round.
- No additional data leaves a node. Only the cohort `AC`/`AN` table crosses
  the border, which was already the case in round 0.

## Files

```
workflow/                                 the Snakemake workflow and original orchestrator.py
docs/workflow-description.md              how the workflow works (server vs client steps)
client/Dockerfile, goe_client.py          client image (build context: repo root)
aggregator/Dockerfile, goe_aggregate.py   aggregator image (build context: repo root)
fem/task-goe-counts.json                  FEM task documents (docs/schemas/task.json)
fem/task-goe-aggregate.json
fem/tool-goe-counts.json                  FEM tool documents (tasks + single_node)
fem/tool-goe-aggregate.json
fem/workflow-goe-fedcomp.json             body for POST /workflows/run-workflow/
push_images.sh                            build and push both images
test_local.sh                             end-to-end check without FEM
```

## Build and test

```bash
# from the repository root
docker build -f client/Dockerfile     -t goe-fedcomp-client .
docker build -f aggregator/Dockerfile -t goe-fedcomp-aggregator .

bash test_local.sh
```

`test_local.sh` first generates the simulated node data if it is missing
(`workflow/scripts/make_mock_data.py 60 400 60`, fixed seed). It then runs one client container per country as a non-root user,
with the data mounted read-only. It then copies the sandboxes to a central
directory the way FEM does, runs the aggregator, and compares the result with
`workflow/central/f244330a464d9/metrics.json`.

## Deploying on FEM

1. Push both images to the GitLab project `fl/gdi-goe-federatedvariantfiltering`,
   as `.../goe-fedcomp-client` and `.../goe-fedcomp-aggregator`:
   ```bash
   docker login registry.gitlab.bsc.es
   bash push_images.sh                # TAG=... to change the version (default 0.1.0)
   ```
   Then copy the digests the script prints into `image.hash` in
   `fem/task-*.json`. If the tag changes, update `image.tag` there too.
2. Insert the task documents and tool documents into the orchestrator's
   `tasks` and `tools` collections.
3. In `fem/workflow-goe-fedcomp.json`:
   - Replace `CENTRAL` with the FEM node name of the aggregation node. It must
     be both `workflow_storage_node` and the node with the `server` role.
   - Make the keys under `execution_nodes` and `per_role` match your
     registered node names. Each client's `{"node": …}` value becomes part of
     its output file name.
4. Start the run: `POST /workflows/run-workflow/` with the workflow JSON as a
   plain-text body.

### Assumptions to check against your site's launcher

The site launcher (`json_launcher` in `fem-client/config/config.py`, which is
not in this repository) decides how the container is started. The defaults
here assume the following:

- **Node VCFs** are mounted at `/data`, as `<sample>.vcf.gz` at the top level.
  Otherwise, pass `input` per node in `per_role`.
- **Execution sandbox** is reachable at `%%sandbox_execution%%`, which
  fem-client resolves to its sandbox path (`/sandbox` with the Docker launcher).
  Otherwise, override `output` (client), or `input` and `output` (aggregator).
- **Container command:** the container is started with the task command and
  no entrypoint override. Neither image defines an `ENTRYPOINT`. Both images
  work when run as an arbitrary host uid.

The FEM behaviours this design relies on come from reading
`fem-orchestrator/api/services/workflow_service.py`:

- **Placeholder server client.** A workflow tool must list at least one
  `client` node even when its only task is `single_node`. That's why `CENTRAL`
  has both roles for `goe-aggregate`, but only the server task runs.
- **File renaming.** Collected files are renamed `<node>_<file>`, then cut
  back at the first `_`. The node name is therefore embedded after the first
  `_`, as `goe-counts.<node>.csv`, so files from different countries can't
  overwrite each other.
- **What gets shipped.** Everything in a client's execution sandbox is shipped
  to the storage node, including the container's captured stdout. The client
  therefore keeps per-sample tables and Snakemake logs in a private directory
  inside the container, and on success prints only cohort totals. If
  Snakemake fails, the last 40 lines of its log are printed, and those can
  name samples.

## Execution examples

### Client: `goe-counts` (every data node)

| | Argument | Default | Content |
|---|---|---|---|
| **Input** | `input` (`--data-dir`) | `/data` | The node's `<sample>.vcf.gz` files, read-only |
| **Output** | `output` (`--out-dir`) | `%%sandbox_execution%%` | Exactly one file, `goe-counts.<node>.csv` |
| Parameter | `node` (`--node`) | none, required | The node's FEM name; it becomes part of the output file name |
| Parameter | `cores` (`--cores`) | `2` | Snakemake cores |

Task command ([`fem/task-goe-counts.json`](fem/task-goe-counts.json)):

```json
"command": {
  "base": "goe-client",
  "args": [
    { "id": "input",  "type": "str", "default_value": "/data",                 "position": 1, "prefix": "--data-dir", "separate": true, "required": true  },
    { "id": "output", "type": "str", "default_value": "%%sandbox_execution%%", "position": 2, "prefix": "--out-dir",  "separate": true, "required": true  },
    { "id": "node",   "type": "str", "default_value": "",                      "position": 3, "prefix": "--node",     "separate": true, "required": true  },
    { "id": "cores",  "type": "int", "default_value": 2,                       "position": 4, "prefix": "--cores",    "separate": true, "required": false }
  ]
}
```

`node` has no default, so each node's value comes from the workflow:

```json
"per_role": {
  "Spain":   { "node": "Spain" },
  "Germany": { "node": "Germany" },
  "Czechia": { "node": "Czechia" }
}
```

Command run at Spain, and the resulting sandbox:

```
goe-client --data-dir /data --out-dir /sandbox --node Spain

/sandbox/
└── goe-counts.Spain.csv        Variant,CHROM,POS,AC,AN
                                1:100000:A:G,1,100000,53,120
                                ...
```

### Aggregator: `goe-aggregate` (central node)

| | Argument | Default | Content |
|---|---|---|---|
| **Input** | `input` (`--in-dir`) | `%%sandbox_execution%%` | `goe-counts.<node>.csv` from every client, delivered by FEM before the task starts |
| **Output** | `output` (`--out-dir`) | `%%sandbox_execution%%` | `metrics.json`, `global_freq.json`, `rounds/<r>/<node>_round_<r>_passing.txt` |
| Parameter | `fst` (`--fst`) | `0.01` | Wright's F_ST |
| Parameter | `ll_min`, `ll_max` | `-50.0`, `0.0` | λ search range; must suit the cohort size (see [`docs/workflow-description.md`](docs/workflow-description.md)) |
| Parameter | `coarse_steps` | `9` | Thresholds scanned before refining; below 2 disables the scan |
| Parameter | `step_min` | `0.5` | Convergence criterion |
| Parameter | `lambda_0`, `step_init` | `-25.0`, `5.0` | Start point and step, only when the scan is disabled |

Task command ([`fem/task-goe-aggregate.json`](fem/task-goe-aggregate.json)):

```json
"command": {
  "base": "goe-aggregate",
  "args": [
    { "id": "input",        "type": "str",   "default_value": "%%sandbox_execution%%", "position": 1, "prefix": "--in-dir",       "separate": true, "required": true  },
    { "id": "output",       "type": "str",   "default_value": "%%sandbox_execution%%", "position": 2, "prefix": "--out-dir",      "separate": true, "required": true  },
    { "id": "fst",          "type": "float", "default_value": 0.01,                    "position": 3, "prefix": "--fst",          "separate": true, "required": true  },
    { "id": "ll_min",       "type": "float", "default_value": -50.0,                   "position": 4, "prefix": "--ll-min",       "separate": true, "required": false },
    { "id": "ll_max",       "type": "float", "default_value": 0.0,                     "position": 5, "prefix": "--ll-max",       "separate": true, "required": false },
    { "id": "coarse_steps", "type": "int",   "default_value": 9,                       "position": 6, "prefix": "--coarse-steps", "separate": true, "required": false },
    { "id": "step_min",     "type": "float", "default_value": 0.5,                     "position": 7, "prefix": "--step-min",     "separate": true, "required": false },
    { "id": "lambda_0",     "type": "float", "default_value": -25.0,                   "position": 8, "prefix": "--lambda-0",     "separate": true, "required": false },
    { "id": "step_init",    "type": "float", "default_value": 5.0,                     "position": 9, "prefix": "--step-init",    "separate": true, "required": false }
  ]
}
```

Parameters come from the workflow's `per_role.server`:

```json
"per_role": {
  "server": { "fst": 0.01, "ll_min": -50.0, "ll_max": 0.0, "coarse_steps": 9, "step_min": 0.5 }
}
```

Command run at the central node, and the resulting sandbox:

```
goe-aggregate --in-dir /sandbox --out-dir /sandbox --fst 0.01 --ll-min -50.0 --ll-max 0.0 --coarse-steps 9 --step-min 0.5

/sandbox/
├── goe-counts.Spain.csv          inputs, delivered by FEM
├── goe-counts.Germany.csv
├── goe-counts.Czechia.csv
├── global_freq.json              pooled allele frequency per variant
├── metrics.json                  the result: best λ, F1, Jaccard, recall, full history
└── rounds/
    ├── 1/Spain_round_1_passing.txt
    ├── 1/Germany_round_1_passing.txt
    ├── ...
    └── 13/Czechia_round_13_passing.txt
```

`metrics.json` (abridged, from the simulated data):

```json
{
  "federation_id": "f244330a464d9",
  "countries": ["Czechia", "Germany", "Spain"],
  "baseline_intersection": 391,
  "rounds": 13,
  "best": { "ll_thresh": -9.375, "f1": 0.8571, "jaccard": 0.7559, "recall": 0.9898,
            "intersection": 387, "per_country": { "Czechia": 435, "Germany": 432, "Spain": 432 } },
  "history": [ ... ]
}
```

### The same runs without FEM

The two `docker run` commands FEM's launcher effectively performs:

```bash
# client, at each node
docker run --rm \
  -v /path/to/Spain/genomic_varcalls:/data:ro \
  -v /path/to/sandbox:/sandbox \
  registry.gitlab.bsc.es/fl/gdi-goe-federatedvariantfiltering/goe-fedcomp-client:0.1.0 \
  goe-client --data-dir /data --out-dir /sandbox --node Spain

# aggregator, at the central node, after copying every goe-counts.<node>.csv into its sandbox
docker run --rm \
  -v /path/to/central-sandbox:/sandbox \
  registry.gitlab.bsc.es/fl/gdi-goe-federatedvariantfiltering/goe-fedcomp-aggregator:0.1.0 \
  goe-aggregate --in-dir /sandbox --out-dir /sandbox --fst 0.01
```

Both task commands set `base` to the program name, because neither image
defines an `ENTRYPOINT`. If your launcher expects `"base": ""` and relies on
the image's entrypoint, the images need an `ENTRYPOINT` added and rebuilding.

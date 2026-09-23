# GoE federated comparison on FEM

Container packaging of [`snakemake--workflow/`](../snakemake--workflow/) for the
Federated Execution Manager ([`fem-orchestrator`](../fem-orchestrator/),
[`fem-client`](../fem-client/)). It produces the same analysis, with the same
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
client/Dockerfile, goe_client.py          client image (build context: repo root)
aggregator/Dockerfile, goe_aggregate.py   aggregator image (build context: repo root)
fem/task-goe-counts.json                  FEM task documents (docs/schemas/task.json)
fem/task-goe-aggregate.json
fem/tool-goe-counts.json                  FEM tool documents (tasks + single_node)
fem/tool-goe-aggregate.json
fem/workflow-goe-fedcomp.json             body for POST /workflows/run-workflow/
test_local.sh                             end-to-end check without FEM
```

## Build and test

```bash
# from the repository root
docker build -f goe-fem/client/Dockerfile     -t goe-fedcomp-client .
docker build -f goe-fem/aggregator/Dockerfile -t goe-fedcomp-aggregator .

bash goe-fem/test_local.sh
```

`test_local.sh` runs one client container per country as a non-root user,
with the data mounted read-only. It then copies the sandboxes to a central
directory the way FEM does, runs the aggregator, and compares the result with
`snakemake--workflow/central/f244330a464d9/metrics.json`.

## Deploying on FEM

1. Push both images to your registry. Then, in `fem/task-*.json`, fill in
   `image.repository` (currently `REGISTRY`), `image.tag` and `image.hash`.
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
  Otherwise, pass `data_dir` per node in `per_role`.
- **Execution sandbox** is mounted at `/sandbox`. Otherwise, pass `out_dir`
  (client), or `in_dir` and `out_dir` (aggregator).
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

## Parameters

Client (`goe-counts`): `node` is required. `data_dir`, `out_dir` and `cores`
are optional.

Aggregator (`goe-aggregate`, via `per_role.server`): `fst`, `ll_min`,
`ll_max`, `coarse_steps`, `step_min`, `lambda_0`, `step_init`, `in_dir` and
`out_dir`. These mirror the orchestrator's environment variables, with the
same defaults. The λ range still has to suit the cohort size (see Part 1 in
the top-level README).

#!/usr/bin/env bash
# Run the FEM task images locally, moving files the way an FEM workflow does,
# and compare the result with the reference run of orchestrator.py.
#
#   bash test_local.sh
#
# Generates the simulated node data first if it is missing.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")" && pwd)
WF="$ROOT/workflow"
RUN="$ROOT/test-run"
NODES=${NODES:-"Spain Germany Czechia"}
REFERENCE=${REFERENCE:-"$WF/central/f244330a464d9/metrics.json"}
USER_FLAG="--user $(id -u):$(id -g)"

# Same parameters and fixed seed as the reference run.
if [ ! -d "$WF/nodes" ]; then
  python3 "$WF/scripts/make_mock_data.py" 60 400 60
fi

docker build -q -f "$ROOT/client/Dockerfile"     -t goe-fedcomp-client     "$ROOT" >/dev/null
docker build -q -f "$ROOT/aggregator/Dockerfile" -t goe-fedcomp-aggregator "$ROOT" >/dev/null

rm -rf "$RUN"
mkdir -p "$RUN/central"

# Tool 1: goe-counts, once per client node. Data read-only, sandbox writable.
for node in $NODES; do
  mkdir -p "$RUN/$node"
  docker run --rm $USER_FLAG \
    -v "$WF/nodes/$node/genomic_varcalls:/data:ro" \
    -v "$RUN/$node:/sandbox" \
    goe-fedcomp-client goe-client --node "$node" --cores 4
done

# FEM transfer: each file goes to the storage node as <node>_<file>, which the
# workflow service then strips back to <file>. Only the sandbox is collected.
for node in $NODES; do
  for f in "$RUN/$node"/*; do
    cp "$f" "$RUN/central/$(basename "$f")"
  done
done

# Tool 2: goe-aggregate on the storage node.
docker run --rm $USER_FLAG -v "$RUN/central:/sandbox" \
  goe-fedcomp-aggregator goe-aggregate --fst 0.01

echo
echo "Client sandboxes hold only:"; for node in $NODES; do ls "$RUN/$node"; done

python3 - "$RUN/central/metrics.json" "$REFERENCE" <<'PY'
import json, sys
new, ref = (json.load(open(p)) for p in sys.argv[1:3])
keys = ["federation_id", "fst", "baseline_intersection", "rounds", "best", "history"]
diff = [k for k in keys if new[k] != ref[k]]
print("\nIdentical to reference:" if not diff else "\nDIFFERS from reference in: " + ", ".join(diff),
      sys.argv[2])
sys.exit(1 if diff else 0)
PY

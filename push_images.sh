#!/usr/bin/env bash
# Build both GoE FEM images and push them to the BSC GitLab registry, as two
# images under the GitLab project fl/gdi-goe-federatedvariantfiltering
#
#   docker login registry.gitlab.bsc.es      # once; GitLab user + password or token
#   bash push_images.sh                      # from anywhere
#
# Override with REGISTRY=... TAG=... PUSH=0 (build and tag only).
set -euo pipefail

ROOT=$(cd "$(dirname "$0")" && pwd)
REGISTRY=${REGISTRY:-registry.gitlab.bsc.es/fl/gdi-goe-federatedvariantfiltering}
TAG=${TAG:-0.1.0}
PUSH=${PUSH:-1}

for image in client aggregator; do
  name="$REGISTRY/goe-fedcomp-$image"
  docker build --platform linux/amd64 \
    -f "$ROOT/$image/Dockerfile" \
    -t "$name:$TAG" -t "$name:latest" "$ROOT"
  if [ "$PUSH" = 1 ]; then
    docker push "$name:$TAG"
    docker push "$name:latest"
    # The digest FEM expects in the task's image.hash
    echo "$name:$TAG -> $(docker inspect --format '{{index .RepoDigests 0}}' "$name:$TAG")"
  fi
done

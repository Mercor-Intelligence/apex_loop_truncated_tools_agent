#!/usr/bin/env bash
#
# Build the three images a Harbor dataset needs: world sidecar, agent, verifier.
# Run from the archipelago repo root:
#
#   bash harbor/build_images.sh [tag]
#
# One set of images serves every world and every task — world data is mounted
# per trial, not baked — so this runs once, not per world.
#
set -euo pipefail

TAG="${1:-${HARBOR_IMAGE_TAG:-latest}}"
PREFIX="${HARBOR_IMAGE_PREFIX:-archipelago-harbor}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

BASE_IMAGE="archipelago-environment:base-${TAG}"
WORLD_IMAGE="${PREFIX}-world:${TAG}"
AGENT_IMAGE="${PREFIX}-agent:${TAG}"
VERIFIER_IMAGE="${PREFIX}-verifier:${TAG}"

cd "$ROOT"

echo "==> environment base ($BASE_IMAGE)"
docker build -t "$BASE_IMAGE" -f environment/Dockerfile .

echo "==> world sidecar ($WORLD_IMAGE)"
docker build --build-arg "BASE_IMAGE=$BASE_IMAGE" \
    -t "$WORLD_IMAGE" -f harbor/Dockerfile.world .

echo "==> agent ($AGENT_IMAGE)"
docker build -t "$AGENT_IMAGE" -f harbor/Dockerfile.agent .

echo "==> verifier ($VERIFIER_IMAGE)"
docker build -t "$VERIFIER_IMAGE" -f harbor/Dockerfile.verifier .

# Harbor's teardown runs `compose down --rmi all`, which would delete images that
# every later trial needs. The -keep aliases are what survive it.
for image in "$WORLD_IMAGE" "$AGENT_IMAGE" "$VERIFIER_IMAGE"; do
    docker tag "$image" "${image%:*}-keep:${TAG}"
done

echo
echo "Built:"
printf '  %s\n' "$WORLD_IMAGE" "$AGENT_IMAGE" "$VERIFIER_IMAGE"

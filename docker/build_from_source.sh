#!/usr/bin/env bash
# docker/build_from_source.sh - FALLBACK: build iota, iota-node, iota-localnet from the v1.33.1
# source commit pinned in fogbed_iota/genesis/IOTA_RELEASE.json into docker/bins/.
#
# Use docker/fetch_binaries.sh instead whenever the official asset runs on your platform.
# A source build is NOT bit-identical to the official asset (different build host), so the
# per-binary sha256 pins cannot match; build the image with --build-arg VERIFY_SHA256=false.
# `--version` (which embeds the commit) is still enforced by Dockerfile.local.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST="${ROOT}/fogbed_iota/genesis/IOTA_RELEASE.json"
COMMIT="$(jq -r .commit_sha "${MANIFEST}")"
RUST_IMAGE="${RUST_IMAGE:-rust:$(jq -r .rust_toolchain "${MANIFEST}")-bookworm}"

mkdir -p "${ROOT}/docker/bins"
rm -f "${ROOT}/docker/bins/"{iota,iota-node,iota-localnet}

echo ">> building IOTA @ ${COMMIT} with ${RUST_IMAGE} (this takes a long time and several GB of RAM/disk)"
DOCKER_BUILDKIT=1 docker build \
  -f "${ROOT}/docker/Dockerfile.build" \
  --target export \
  --build-arg RUST_IMAGE="${RUST_IMAGE}" \
  --build-arg IOTA_COMMIT="${COMMIT}" \
  --build-arg GIT_REVISION="${COMMIT:0:12}" \
  --output "type=local,dest=${ROOT}/docker/bins" \
  "${ROOT}/docker"

{
  echo "IOTA $(jq -r .release_tag "${MANIFEST}") built from source $(date -u +%FT%TZ)"
  echo "commit  ${COMMIT}"
  echo "builder ${RUST_IMAGE}"
  (cd "${ROOT}/docker/bins" && sha256sum iota iota-node iota-localnet)
} | tee "${ROOT}/docker/bins/PROVENANCE.txt"

echo ">> next: docker build -f docker/Dockerfile.local --build-arg VERIFY_SHA256=false -t iota-dev:latest ."

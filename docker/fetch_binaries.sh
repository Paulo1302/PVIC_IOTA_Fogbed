#!/usr/bin/env bash
# docker/fetch_binaries.sh - ingest the official IOTA v1.33.1 release binaries into docker/bins/.
#
# Downloads ONE pinned release asset (linux-x86_64), verifies it against the sha256 pinned in
# fogbed_iota/genesis/IOTA_RELEASE.json, extracts `iota`, `iota-node` and `iota-localnet` from
# that single archive (same release, arch and build), verifies each binary's sha256 and
# `--version`, and writes docker/bins/PROVENANCE.txt.
#
# Offline use: IOTA_ASSET_TARBALL=/path/to/iota-v1.33.1-linux-x86_64.tgz ./docker/fetch_binaries.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST="${ROOT}/fogbed_iota/genesis/IOTA_RELEASE.json"
BINS="${ROOT}/docker/bins"
CACHE="${BINS}/.download"
WANTED=(iota iota-node iota-localnet)

command -v jq >/dev/null || { echo "ERROR: jq is required" >&2; exit 1; }
[[ -r "${MANIFEST}" ]] || { echo "ERROR: ${MANIFEST} not found" >&2; exit 1; }

[[ "$(uname -s)" == "Linux" && "$(uname -m)" == "x86_64" ]] || \
  echo "WARN: host is $(uname -s)/$(uname -m); the pinned asset is linux/x86_64 (fine for Docker builds, binaries only run on matching hosts)" >&2

TAG="$(jq -r .release_tag "${MANIFEST}")"
URL="$(jq -r .asset.url "${MANIFEST}")"
ASSET="$(jq -r .asset.name "${MANIFEST}")"
ASSET_SHA="$(jq -r .asset.sha256 "${MANIFEST}")"
VERSION_STRING="$(jq -r .version_string "${MANIFEST}")"

mkdir -p "${BINS}" "${CACHE}"
TARBALL="${IOTA_ASSET_TARBALL:-${CACHE}/${ASSET}}"

sha_of() { sha256sum "$1" | awk '{print $1}'; }

if [[ -f "${TARBALL}" && "$(sha_of "${TARBALL}")" == "${ASSET_SHA}" ]]; then
  echo ">> using cached ${TARBALL} (sha256 verified)"
else
  [[ -z "${IOTA_ASSET_TARBALL:-}" ]] || { echo "ERROR: ${TARBALL} missing or sha256 mismatch" >&2; exit 1; }
  echo ">> downloading ${URL}"
  curl -fL --retry 3 -o "${TARBALL}.part" "${URL}"
  mv "${TARBALL}.part" "${TARBALL}"
fi

ACTUAL="$(sha_of "${TARBALL}")"
if [[ "${ACTUAL}" != "${ASSET_SHA}" ]]; then
  echo "ERROR: asset sha256 mismatch" >&2
  echo "  expected ${ASSET_SHA}" >&2
  echo "  actual   ${ACTUAL}" >&2
  rm -f "${CACHE}/${ASSET}"
  exit 1
fi
echo ">> asset sha256 OK (${ASSET_SHA})"

# Remove anything left from another release before extracting (never mix versions).
rm -f "${BINS}/iota" "${BINS}/iota-node" "${BINS}/iota-localnet"
tar -xzf "${TARBALL}" -C "${BINS}" --strip-components=1 "${WANTED[@]/#/./}"
chmod 0755 "${BINS}/"{iota,iota-node,iota-localnet}

{
  echo "IOTA release ${TAG} - ingested $(date -u +%FT%TZ)"
  echo "asset      ${ASSET}"
  echo "asset-sha  ${ASSET_SHA}"
  echo "source     ${URL}"
  echo "commit     $(jq -r .commit_sha "${MANIFEST}")"
  echo "platform   $(jq -r '.target.os + "/" + .target.arch' "${MANIFEST}")"
} > "${BINS}/PROVENANCE.txt"

for b in "${WANTED[@]}"; do
  want="$(jq -r --arg b "$b" '.binaries[$b]' "${MANIFEST}")"
  got="$(sha_of "${BINS}/${b}")"
  [[ "${want}" == "${got}" ]] || { echo "ERROR: ${b} sha256 ${got} != pinned ${want}" >&2; exit 1; }
  ver="$("${BINS}/${b}" --version | awk '{print $NF}')" || { echo "ERROR: ${b} does not run on this host" >&2; exit 1; }
  [[ "${ver}" == "${VERSION_STRING}" ]] || { echo "ERROR: ${b} reports ${ver}, expected ${VERSION_STRING}" >&2; exit 1; }
  echo "${got}  ${b}  (${ver})" | tee -a "${BINS}/PROVENANCE.txt"
done
echo ">> OK: docker/bins/ holds IOTA ${TAG} (${VERSION_STRING})"

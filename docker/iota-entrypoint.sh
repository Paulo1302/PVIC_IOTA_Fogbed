#!/usr/bin/env bash
# iota-entrypoint.sh - container entrypoint for the IOTA v1.33.1 Fogbed image.
#
# Sub-commands:
#   wait          (default) print version info, then idle so Fogbed can inject config
#   version       print + verify the pinned binary versions, then exit
#   check-config  verify validator.yaml / genesis.blob (and announced addresses)
#   start-node    version-check + check-config + exec `iota-node --config-path ...`
#   healthcheck   used by Docker HEALTHCHECK
#   diagnose      dump versions, addresses, sockets and the node log tail
#   shell         bash
#   <other>       exec'd verbatim (so `docker run <img> iota --version` still works)
set -euo pipefail

RELEASE_FILE="${IOTA_RELEASE_FILE:-/opt/iota/IOTA_RELEASE.json}"
CONFIG_DIR="${IOTA_CONFIG_DIR:-/iota/config}"
NODE_CONFIG="${IOTA_NODE_CONFIG:-${CONFIG_DIR}/validator.yaml}"
GENESIS_FILE="${IOTA_GENESIS_FILE:-${CONFIG_DIR}/genesis.blob}"
LOG_DIR="${IOTA_LOG_DIR:-/var/log/iota}"
NODE_LOG="${LOG_DIR}/iota-node.log"
STARTED_MARKER="${IOTA_STARTED_MARKER:-/run/iota-node.started}"
BIN_DIR="${IOTA_BIN_DIR:-/usr/local/bin}"
BINARIES=(iota iota-node iota-localnet)

log()  { echo "[iota-fogbed] $(date -u +%FT%TZ) [$(hostname)] $*"; }
fail() { log "ERROR: $*" >&2; exit 1; }

expected_version() { jq -r '.version_string' "${RELEASE_FILE}"; }

version_check() {
  [[ -r "${RELEASE_FILE}" ]] || fail "release manifest ${RELEASE_FILE} missing; image was not built from Dockerfile.local"
  local expected tag commit protocol bin actual
  expected="$(expected_version)"
  tag="$(jq -r '.release_tag' "${RELEASE_FILE}")"
  commit="$(jq -r '.commit_sha' "${RELEASE_FILE}")"
  protocol="$(jq -r '.protocol_version' "${RELEASE_FILE}")"
  log "pinned release ${tag} (commit ${commit}, protocol ${protocol}, version ${expected})"
  for bin in "${BINARIES[@]}"; do
    [[ -x "${BIN_DIR}/${bin}" ]] || fail "${BIN_DIR}/${bin} not found or not executable"
    actual="$("${BIN_DIR}/${bin}" --version | awk '{print $NF}')"
    if [[ "${actual}" != "${expected}" ]]; then
      fail "${bin} reports '${actual}' but this image is pinned to '${expected}' (do not mix IOTA versions)"
    fi
    log "  ${bin}: ${actual} OK"
  done
}

yaml_value() { # yaml_value <key> <file>: first scalar value of "<key>:" (any indentation)
  awk -v k="$1" '
    $1 == k":" { v=$0; sub(/^[^:]*:[ \t]*/, "", v); gsub(/^"|"$/, "", v); print v; exit }
  ' "$2"
}

check_config() {
  [[ -s "${NODE_CONFIG}" ]]  || fail "node config missing/empty: ${NODE_CONFIG}"
  [[ -s "${GENESIS_FILE}" ]] || fail "genesis.blob missing/empty: ${GENESIS_FILE}"

  local ext listen net
  ext="$(yaml_value external-address "${NODE_CONFIG}")"
  listen="$(yaml_value listen-address "${NODE_CONFIG}")"
  net="$(yaml_value network-address "${NODE_CONFIG}")"
  [[ -n "${ext}" ]]    || fail "p2p-config.external-address not set in ${NODE_CONFIG}"
  [[ -n "${listen}" ]] || fail "p2p-config.listen-address not set in ${NODE_CONFIG}"
  [[ -n "${net}" ]]    || fail "network-address not set in ${NODE_CONFIG}"

  if [[ "${ext}" == *127.0.0.1* || "${ext}" == *localhost* ]]; then
    fail "announced p2p external-address '${ext}' uses loopback; it must be the Fogbed 10.0.0.x address"
  fi
  [[ "${ext}" =~ ^/ip4/[0-9]{1,3}(\.[0-9]{1,3}){3}/udp/[0-9]+/quic$ ]] \
    || fail "external-address '${ext}' is not /ip4/<ip>/udp/<port>/quic"
  [[ "${listen}" =~ ^0\.0\.0\.0:[0-9]+$ ]] \
    || fail "p2p listen-address '${listen}' should be 0.0.0.0:<port>"
  [[ "${net}" == /ip4/0.0.0.0/tcp/*/http ]] \
    || fail "network-address '${net}' should be /ip4/0.0.0.0/tcp/<port>/http (local bind)"

  log "config OK: network-address=${net} p2p.listen=${listen} p2p.external=${ext}"
  log "genesis.blob sha256=$(sha256sum "${GENESIS_FILE}" | awk '{print $1}') ($(stat -c %s "${GENESIS_FILE}") bytes)"
}

start_node() {
  version_check
  check_config
  mkdir -p "${LOG_DIR}"
  : > "${STARTED_MARKER}"
  log "starting iota-node --config-path ${NODE_CONFIG} (log: ${NODE_LOG})"
  exec > >(tee -a "${NODE_LOG}") 2>&1
  exec "${BIN_DIR}/iota-node" --config-path "${NODE_CONFIG}"
}

healthcheck() {
  version_check >/dev/null
  if [[ -e "${STARTED_MARKER}" ]]; then
    check_config >/dev/null
    pgrep -x iota-node >/dev/null || fail "iota-node was started but is not running (see ${NODE_LOG})"
  fi
}

diagnose() {
  version_check || true
  log "--- addresses"; ip -br addr || true
  log "--- listening sockets"; ss -tulpn 2>/dev/null || true
  log "--- processes"; pgrep -a iota || echo "no iota process"
  if [[ -s "${NODE_CONFIG}" ]]; then
    log "--- p2p/network config"; grep -nE "network-address|listen-address|external-address|genesis-file-location" "${NODE_CONFIG}" || true
  fi
  [[ -s "${GENESIS_FILE}" ]] && log "genesis.blob sha256=$(sha256sum "${GENESIS_FILE}" | awk '{print $1}')"
  if [[ -f "${NODE_LOG}" ]]; then log "--- tail ${NODE_LOG}"; tail -n 60 "${NODE_LOG}"; fi
}

case "${1:-wait}" in
  wait)         version_check; log "waiting for config in ${CONFIG_DIR}"; exec tail -f /dev/null ;;
  version)      version_check ;;
  check-config) check_config ;;
  start-node)   shift || true; start_node "$@" ;;
  healthcheck)  healthcheck ;;
  diagnose)     diagnose ;;
  shell)        shift || true; exec /bin/bash "$@" ;;
  *)            exec "$@" ;;
esac

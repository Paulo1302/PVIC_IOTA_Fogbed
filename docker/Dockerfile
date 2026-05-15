FROM ubuntu:24.04 AS downloader

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates curl tar && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /tmp
ARG IOTA_VERSION=v1.15.0

RUN curl -fSL \
      "https://github.com/iotaledger/iota/releases/download/${IOTA_VERSION}/iota-${IOTA_VERSION}-linux-x86_64.tgz" \
      -o /tmp/iota.tgz && \
    tar -xzf /tmp/iota.tgz && \
    mkdir -p /out && \
    find /tmp -type f -name iota -executable -exec cp {} /out/iota \; && \
    find /tmp -type f -name iota-node -executable -exec cp {} /out/iota-node \;

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

LABEL maintainer="Paulo <paulogrcsilva@gmail.com>"
LABEL description="IOTA v1.15.0 runtime image for Fogbed distributed emulation"
LABEL version="1.15.0"

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      ca-certificates \
      curl \
      bash \
      iproute2 \
      iputils-ping \
      net-tools \
      jq \
      procps \
      libssl3 \
      libudev1 \
      libgcc-s1 \
      libstdc++6 && \
    rm -rf /var/lib/apt/lists/*

COPY --from=downloader /out/iota /usr/local/bin/iota
COPY --from=downloader /out/iota-node /usr/local/bin/iota-node

RUN chmod +x /usr/local/bin/iota /usr/local/bin/iota-node && \
    mkdir -p /iota/config /iota/db /var/lib/iota/mainnetdb /var/log/iota

RUN cat > /usr/local/bin/iota-entrypoint.sh <<'EOF' && chmod +x /usr/local/bin/iota-entrypoint.sh
#!/usr/bin/env bash
set -euo pipefail

CONFIG_DIR="${IOTA_CONFIG_DIR:-/iota/config}"
VALIDATOR_CONFIG="${IOTA_NODE_CONFIG:-${CONFIG_DIR}/validator.yaml}"
NETWORK_FILE="${IOTA_NETWORK_FILE:-${CONFIG_DIR}/network.yaml}"
GENESIS_FILE="${IOTA_GENESIS_FILE:-${CONFIG_DIR}/genesis.blob}"

wait_for_config() {
  echo "[iota-fogbed] waiting for config in ${CONFIG_DIR}"
  while true; do
    if [[ -s "${VALIDATOR_CONFIG}" && -s "${NETWORK_FILE}" && -s "${GENESIS_FILE}" ]]; then
      return 0
    fi
    sleep 1
  done
}

start_node() {
  wait_for_config
  echo "[iota-fogbed] starting iota-node with ${VALIDATOR_CONFIG}"
  exec /usr/local/bin/iota-node --config-path "${VALIDATOR_CONFIG}"
}

case "${1:-wait}" in
  wait)
    wait_for_config
    tail -f /dev/null
    ;;
  start-node)
    shift || true
    start_node "$@"
    ;;
  shell)
    shift || true
    exec /bin/bash "$@"
    ;;
  *)
    exec "$@"
    ;;
esac
EOF

EXPOSE 9000 9002 9184
EXPOSE 8080/udp

ENV IOTA_CONFIG_DIR=/iota/config \
    IOTA_DATA_DIR=/var/lib/iota/mainnetdb \
    IOTA_LOG_DIR=/var/log/iota \
    RUST_LOG=info \
    RUST_BACKTRACE=1

WORKDIR /iota

ENTRYPOINT ["/usr/local/bin/iota-entrypoint.sh"]
CMD ["wait"]

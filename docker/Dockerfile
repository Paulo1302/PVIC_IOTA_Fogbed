# docker/Dockerfile - IOTA v1.15.0 com suporte Move completo
FROM ubuntu:24.04 AS downloader

ENV DEBIAN_FRONTEND=noninteractive

# Ferramentas para download
RUN apt-get update && \
    apt-get install -y curl tar && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /tmp
ARG IOTA_VERSION=v1.15.0

# Baixa release oficial da IOTA
RUN curl -fSL \
      "https://github.com/iotaledger/iota/releases/download/${IOTA_VERSION}/iota-${IOTA_VERSION}-linux-x86_64.tgz" \
      -o iota.tgz

# Extrai TODOS os binários necessários
RUN tar -xzf iota.tgz && \
    mkdir -p /binaries && \
    find /tmp -type f -name "iota" -executable -exec mv {} /binaries/ \; && \
    find /tmp -type f -name "iota-node" -executable -exec mv {} /binaries/ \; && \
    find /tmp -type f -name "iota-move" -executable -exec mv {} /binaries/ \; 2>/dev/null || true

# ============================================
# Stage final - Imagem runtime com Move tooling
# ============================================
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

LABEL maintainer="Paulo <paulogrcsilva@gmail.com>"
LABEL description="IOTA node + Move tooling for Fogbed network emulation"
LABEL version="1.15.0-move"

# Dependências runtime + build tools para Move
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      # Runtime IOTA
      libssl3 \
      libudev1 \
      ca-certificates \
      libpq5 \
      # Networking
      iproute2 \
      net-tools \
      iputils-ping \
      curl \
      wget \
      jq \
      # Build tools para Move
      build-essential \
      pkg-config \
      libssl-dev \
      git \
    && rm -rf /var/lib/apt/lists/*

# Instalar Rust (necessário para iota move build)
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable
ENV PATH="/root/.cargo/bin:${PATH}"

# Copia binários compilados
COPY --from=downloader /binaries/* /usr/local/bin/

# Torna executável e verifica
RUN chmod +x /usr/local/bin/iota* && \
    iota --version && \
    iota-node --version && \
    (iota move --help || echo "iota move integrated into iota binary")

# Estrutura de diretórios
RUN mkdir -p \
    /app/config \
    /app/db \
    /app/consensus_db \
    /custom_config \
    /root/.iota \
    /root/.iota/iota.keystore \
    /var/log/iota \
    /contracts \
    /contracts/examples

# Expõe portas comuns
EXPOSE 9000 9184 8080 8081

# Variáveis de ambiente
ENV IOTA_HOME=/app
ENV IOTA_CONFIG_DIR=/app/config
ENV RUST_LOG=info,iota=debug
ENV RUST_BACKTRACE=1

WORKDIR /app

# Entrypoint flexível
ENTRYPOINT []
CMD ["tail", "-f", "/dev/null"]

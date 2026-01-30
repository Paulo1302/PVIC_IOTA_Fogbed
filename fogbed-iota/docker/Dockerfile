# docker/Dockerfile - IOTA v1.15.0 para Fogbed
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

# Extrai e organiza binários
RUN tar -xzf iota.tgz && \
    mkdir -p /binaries && \
    find /tmp -type f -name "iota" -executable -exec mv {} /binaries/ \; && \
    find /tmp -type f -name "iota-node" -executable -exec mv {} /binaries/ \;

# ============================================
# Stage final - Imagem runtime otimizada
# ============================================
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

LABEL maintainer="Paulo <seu-email@exemplo.com>"
LABEL description="IOTA node for Fogbed network emulation"
LABEL version="1.15.0"

# Dependências runtime
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      libssl3 \
      libudev1 \
      ca-certificates \
      libpq5 \
      iproute2 \
      net-tools \
      iputils-ping \
      curl \
      jq \
    && rm -rf /var/lib/apt/lists/*

# Copia binários compilados
COPY --from=downloader /binaries/* /usr/local/bin/

# Torna executável e verifica
RUN chmod +x /usr/local/bin/iota /usr/local/bin/iota-node && \
    iota --version && \
    iota-node --version

# Estrutura de diretórios para Fogbed
RUN mkdir -p \
    /app/config \
    /app/db \
    /app/consensus_db \
    /custom_config \
    /root/.iota \
    /var/log/iota

# Usuário não-root (opcional, para segurança)
# RUN useradd -m -u 1000 iota && \
#     chown -R iota:iota /app /root/.iota /var/log/iota
# USER iota

WORKDIR /app

# Expõe portas comuns da IOTA
EXPOSE 9000 9184 8080 8081

# Variáveis de ambiente padrão
ENV IOTA_HOME=/app
ENV IOTA_CONFIG_DIR=/app/config
ENV RUST_LOG=info,iota=debug

# Entrypoint flexível para Fogbed
ENTRYPOINT []
CMD ["tail", "-f", "/dev/null"]



FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive

# Instala ferramentas de rede, INCLUINDO ethtool
RUN apt-get update && apt-get install -y \
    iproute2 net-tools iputils-ping curl nano \
    ca-certificates libssl-dev openssl ethtool \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/config /app/db /app/consensus_db /custom_config

# Mantém o container vivo
ENTRYPOINT []
CMD ["tail", "-f", "/dev/null"]
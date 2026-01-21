# Usamos o Ubuntu 24.04 como base
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive

# 1. Instala APENAS dependências de execução (Runtime)
# Removemos todo o peso do Rust, Cargo e Compiladores.
# Adicionamos 'libudev1' que é necessário para rodar o IOTA.
RUN apt-get update && apt-get install -y \
    iproute2 net-tools iputils-ping curl nano \
    ca-certificates libssl-dev openssl ethtool \
    libudev1 \
    && rm -rf /var/lib/apt/lists/*

# 2. Prepara as pastas necessárias para o Fogbed
RUN mkdir -p /app/config /app/db /app/consensus_db /custom_config

# 3. COPIA OS BINÁRIOS (O Pulo do Gato)
# Eles precisam estar na mesma pasta que este Dockerfile
COPY iota /usr/local/bin/iota
COPY iota-node /usr/local/bin/iota-node

# 4. Garante permissão de execução
RUN chmod +x /usr/local/bin/iota /usr/local/bin/iota-node

# Mantém o container vivo para receber comandos
ENTRYPOINT []
CMD ["tail", "-f", "/dev/null"]
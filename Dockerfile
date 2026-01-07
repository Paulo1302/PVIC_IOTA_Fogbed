FROM ubuntu:22.04

# Instala ferramentas para debug de rede (Ping, IP, etc)
RUN apt-get update && apt-get install -y \
    iputils-ping \
    net-tools \
    iproute2 \
    curl \
    nano \
    && rm -rf /var/lib/apt/lists/*

# Cria diretórios que o Fogbed espera
RUN mkdir -p /app/config /app/db

# Cria um binário "falso" do IOTA para enganar o script
# Ele apenas imprime logs e dorme, mantendo o container vivo
RUN echo '#!/bin/bash\n\
echo ">>> [MOCK] IOTA Node iniciado simuladamente"\n\
echo ">>> [MOCK] Lendo config de: $@"\n\
echo ">>> [MOCK] Meu IP é: $(hostname -I)"\n\
# Loop infinito para manter o container rodando\n\
while true; do\n\
  echo "[MOCK] Processando transações falsas..."\n\
  sleep 5\n\
done' > /usr/local/bin/iota && chmod +x /usr/local/bin/iota

# Define o comando padrão para usar nosso script falso
CMD ["iota", "node", "--config", "/app/config/validator.yaml"]
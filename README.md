# IOTA Private Network on Fogbed 🕸️

Este projeto implementa uma rede privada (Private Tangle/Blockchain) do protocolo **IOTA** rodando sobre o emulador de redes **Fogbed**. O objetivo é simular um ambiente distribuído realista utilizando containers Docker orquestrados pelo Mininet.

## 📋 Pré-requisitos

Para executar este experimento, certifique-se de que seu ambiente (Linux/Ubuntu) possui:

* **Docker** instalado e rodando.
* **Open vSwitch** (OVS) instalado.
* **Python 3** com `pip`.
* **Fogbed** instalado (via venv).
* **Binários do IOTA** compilados (Rust) localizados em `~/iota/target/release/`.
    * Necessário: `iota` (CLI tool) e `iota-node` (Servidor).

## 🏗️ Arquitetura da Rede

O script `experiment.py` cria automaticamente a seguinte topologia:

* **Topologia:** Estrela (Star Topology) com um switch virtual central.
* **Nós:** 4 Containers Docker (`mn.iota0` a `mn.iota3`).
* **Imagens:** `iota-dev:latest` (Ubuntu base com dependências).
* **Endereçamento IP:**
    * `iota0`: 10.0.0.1
    * `iota1`: 10.0.0.2
    * `iota2`: 10.0.0.3
    * `iota3`: 10.0.0.4
* **Configuração:** Geração dinâmica de Gênesis e Chaves, injetados via `docker cp` (Estratégia Air Drop).

---

## 🚀 Como Iniciar a Rede

1.  **Ative o ambiente virtual (se estiver usando um):**
    ```bash
    source fog-env/bin/activate
    ```

2.  **Execute o script de orquestração (requer sudo):**
    ```bash
    sudo ./fog-env/bin/python experiment.py
    ```

    > **Nota:** O script fará uma limpeza automática de containers antigos, gerará novas chaves criptográficas (Gênesis), subirá os containers e injetará as configurações.

3.  **Aguarde o Boot:**
    O script espera 15 segundos para os nós iniciarem. Não se preocupe com mensagens de erro como `Error setting iota0-eth0 up` — são falsos positivos do Mininet; a rede sobe normalmente.

---

## 🧪 Como Realizar Testes

Com o script rodando (e esperando no "ENTER para sair"), abra um **novo terminal** para interagir com a rede.

### 1. Verificar Logs de Consenso (O Coração da Rede)
Para confirmar se a blockchain está viva e produzindo blocos:

```bash
docker exec mn.iota0 tail -f /app/iota.log
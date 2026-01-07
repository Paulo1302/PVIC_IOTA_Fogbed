import os

# Caminho do arquivo que descobrimos antes
arquivo = "/home/paulo/iota/crates/iota-config/src/node.rs"

print(f"--- Lendo arquivo: {arquivo} ---")

try:
    with open(arquivo, 'r') as f:
        linhas = f.readlines()
        
    encontrou = False
    for i, linha in enumerate(linhas):
        # Procura onde começa o Enum
        if "enum GenesisLocation" in linha:
            print(f"\n[ACHEI NA LINHA {i+1}]")
            # Imprime as 5 linhas antes (para ver os atributos #[serde...])
            # E as 20 linhas depois (para ver os campos)
            inicio = max(0, i - 5)
            fim = min(len(linhas), i + 20)
            
            for j in range(inicio, fim):
                prefixo = ">>" if j == i else "  "
                print(f"{prefixo} {linhas[j].rstrip()}")
            
            encontrou = True
            break
            
    if not encontrou:
        print("[ERRO] Não encontrei 'enum GenesisLocation' neste arquivo.")

except Exception as e:
    print(f"Erro ao ler arquivo: {e}")
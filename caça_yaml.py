import os

root_dir = "/home/paulo/iota"
print(f"[*] Vasculhando {root_dir} por arquivos de configuração de exemplo...\n")

found = False
for dirpath, dirnames, filenames in os.walk(root_dir):
    for filename in filenames:
        # Procuramos arquivos yaml que pareçam configs de validador
        if filename.endswith(".yaml") and ("validator" in filename or "node" in filename):
            full_path = os.path.join(dirpath, filename)
            
            # Filtra arquivos irrelevantes (CI/CD, github actions)
            if ".github" in full_path or "target" in full_path:
                continue
                
            print(f"--- ENCONTRADO: {filename} ---")
            print(f"Caminho: {full_path}")
            
            # Lê o arquivo para ver como eles escreveram o bloco 'genesis'
            try:
                with open(full_path, 'r') as f:
                    content = f.read()
                    if "genesis" in content:
                        print(">>> CONTEÚDO DO BLOCO GENESIS (Amostra):")
                        lines = content.split('\n')
                        for i, line in enumerate(lines):
                            if "genesis" in line:
                                # Mostra a linha e as 5 seguintes
                                print('\n'.join(lines[i:i+6]))
                                found = True
                                print("-" * 40)
                                break
            except:
                pass

if not found:
    print("[!] Nenhum exemplo com 'genesis' encontrado nos YAMLs.")
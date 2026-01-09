import json

class IotaNodeDriver:
    """
    Driver para comunicação com nós IOTA (Real ou Mock) dentro do Fogbed.
    """
    def __init__(self, container, rpc_port=9000):
        self.container = container
        # Endpoint local dentro do container
        self.endpoint = f"http://127.0.0.1:{rpc_port}"

    def _call_rpc(self, method_name, params=[]):
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method_name,
            "params": params
        }
        json_string = json.dumps(payload)
        
        # Adiciona -s (silent) e --fail para não sujar o output
        cmd = f"curl -s --fail -X POST -H 'Content-Type: application/json' --data '{json_string}' {self.endpoint}"
        
        raw_response = self.container.cmd(cmd)
        
        # --- BLINDAGEM DO OUTPUT ---
        # Às vezes o shell retorna o próprio comando ou espaços extras.
        # Vamos tentar encontrar o primeiro '{' e o último '}'
        try:
            start = raw_response.find('{')
            end = raw_response.rfind('}') + 1
            if start != -1 and end != 0:
                clean_json = raw_response[start:end]
                return json.loads(clean_json)
            else:
                # Tenta converter direto se não achar chaves (pode ser erro simples)
                return json.loads(raw_response)
        except json.JSONDecodeError:
            return {"error": "Falha no decode JSON", "raw": raw_response}
    # --- MÉTODOS QUE O EXPERIMENT.PY ESTÁ CHAMANDO ---

    def get_latest_checkpoint(self):
        """Consulta o último checkpoint (bloco) validado."""
        res = self._call_rpc("iota_getLatestCheckpointSequenceNumber")
        return res.get("result", "N/A")

    def get_total_transactions(self):
        """Consulta o total de transações processadas."""
        res = self._call_rpc("iota_getTotalTransactionBlocks")
        return res.get("result", 0)

    def get_peers(self):
        """Consulta a lista de peers conectados."""
        res = self._call_rpc("iota_getPeers")
        return res.get("result", [])
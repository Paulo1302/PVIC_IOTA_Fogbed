import http.server
import socketserver
import json
import sys

PORT = 9000

class MockIotaRPC(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            # Tenta ler o tamanho do conteúdo
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            
            # Decodifica o JSON
            try:
                request = json.loads(post_data)
            except json.JSONDecodeError:
                request = {}
                
            method = request.get("method")
            
            # Respostas Falsas para os testes
            result_data = "N/A"
            if method == "sui_getLatestCheckpointSequenceNumber":
                result_data = "42"
            elif method == "sui_getTotalTransactionBlocks":
                result_data = 100500
            elif method == "sui_getPeers":
                result_data = ["10.0.0.2", "10.0.0.3"]
            
            # Monta resposta padrão
            response = {
                "jsonrpc": "2.0",
                "result": result_data,
                "id": request.get("id", 1)
            }
            
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())
            
        except Exception as e:
            # Log de erro no terminal do container
            print(f"Erro no Handler: {e}", file=sys.stderr)

print(f"Mock API rodando na porta {PORT}...", flush=True)

# Configuração para evitar erro de "Porta em uso"
socketserver.TCPServer.allow_reuse_address = True

with socketserver.TCPServer(("0.0.0.0", PORT), MockIotaRPC) as httpd:
    httpd.serve_forever()
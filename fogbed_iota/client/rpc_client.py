import json
import requests
from typing import Any, Dict, List, Optional, Union
from .exceptions import IotaRpcError, IotaConnectionError, IotaTimeoutError
from fogbed_iota.utils import get_logger

logger = get_logger(__name__)

class IotaRpcClient:
    def __init__(self, endpoint: str, timeout: int = 30, headers: Optional[Dict[str, str]] = None):
        self.endpoint = endpoint.rstrip('/')
        self.timeout = timeout
        self.headers = headers or {"Content-Type": "application/json"}
        self._request_id = 0
        
    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id
    
    def next_id(self) -> int:
        return self._next_id()
    
    def _call(self, method: str, params: List[Any] = None) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
            "params": params or []
        }
        try:
            response = requests.post(
                self.endpoint, json=payload, 
                headers=self.headers, timeout=self.timeout
            )
            response.raise_for_status()
            data = response.json()
            if "error" in data:
                error = data["error"]
                raise IotaRpcError(
                    code=error.get("code", -1),
                    message=error.get("message", "Unknown error"),
                    data=error.get("data")
                )
            return data.get("result")
        except requests.exceptions.Timeout:
            raise IotaTimeoutError(f"Request timeout after {self.timeout}s")
        except requests.exceptions.ConnectionError as e:
            raise IotaConnectionError(f"Connection failed: {e}")
        except requests.exceptions.RequestException as e:
            raise IotaConnectionError(f"Request failed: {e}")
    
    # MÉTODOS RPC CORRETOS (iotax_)
    def get_balance(self, address: str, coin_type: str = "0x2::iota::IOTA") -> Dict[str, Any]:
        return self._call("iotax_getBalance", [address, coin_type])
    
    def get_coins(self, address: str, coin_type: str = "0x2::iota::IOTA", cursor: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
        params = [address, coin_type]
        if cursor: params.append(cursor)
        params.append(limit)
        return self._call("iotax_getCoins", params)
    
    def get_checkpoint(self, checkpoint_id: Union[str, int]) -> Dict[str, Any]:
        return self._call("iota_getCheckpoint", [str(checkpoint_id)])
    
    def get_transaction_block(self, digest: str, options: Optional[Dict[str, bool]] = None) -> Dict[str, Any]:
        params = [digest]
        if options: params.append(options)
        return self._call("iota_getTransactionBlock", params)
    
    def health_check(self) -> bool:
        try:
            self.get_chain_identifier()
            return True
        except Exception:
            return False
    
    def get_chain_identifier(self) -> str:
        return self._call("iota_getChainIdentifier")
    
    def get_latest_checkpoint_sequence_number(self) -> int:
        return int(self._call("iota_getLatestCheckpointSequenceNumber"))
    
    def get_owned_objects(self, address: str, query: Optional[Dict[str, Any]] = None, cursor: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
        params = [address]
        if query: params.append(query)
        if cursor: params.append(cursor)
        params.append(limit)
        return self._call("iotax_getOwnedObjects", params)
    
    def get_object(self, object_id: str, options: Optional[Dict[str, bool]] = None) -> Dict[str, Any]:
        params = [object_id]
        if options: params.append(options)
        return self._call("iota_getObject", params)
    
    def get_protocol_version(self) -> str:
        return self._call("iota_getProtocolVersion")
    
    def get_events(self, query: Dict[str, Any]) -> Dict[str, Any]:
        return self._call("iota_getEvents", [query])

class AsyncIotaRpcClient:
    def __init__(self, endpoint: str, timeout: int = 30, headers: Optional[Dict[str, str]] = None):
        self.endpoint = endpoint.rstrip('/')
        self.timeout = timeout
        self.headers = headers or {"Content-Type": "application/json"}
        self._session = None
        self._request_id = 0

from abc import ABC, abstractmethod
from typing import Any, Dict

class HttpRequest:
    def __init__(self, body: Dict[str, Any]) -> None:
        self.body = body
    
    def get(self, param: str) -> 'Any | None':
        return self.body.get(param)


class HttpResponse:
    def __init__(self, status_code: int, body: Dict[str, Any]) -> None:
        self.status_code = status_code
        self.body = body

    @property
    def is_ok(self) -> bool:
        return self.status_code in [200, 201]
    
class Controller(ABC):
    @abstractmethod
    def handle(self, request: HttpRequest) -> HttpResponse:
        pass
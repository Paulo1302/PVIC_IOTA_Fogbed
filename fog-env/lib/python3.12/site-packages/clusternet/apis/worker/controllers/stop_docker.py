from clusternet.apis.presentation.exceptions import NotFoundException
from clusternet.apis.presentation.helpers import (
    error, internal_server_error, not_found, success
)
from clusternet.apis.presentation.protocols import Controller, HttpRequest, HttpResponse
from clusternet.apis.worker.helpers import WorkerInstance, get_hostname


class StopDockerController(Controller):
    def __init__(self, name: str) -> None:
        self.name = name
        self.net = WorkerInstance.instance()

    def handle(self, request: HttpRequest) -> HttpResponse:   
        hostname = get_hostname()
        
        try:
            if(not self.name in self.net):
                raise NotFoundException(f'[{hostname}]: container {self.name} not found')
            
            self.net.getDocker(self.name).stop()
            return success({'content': f'[{hostname}]: container {self.name} stopped'})

        except NotFoundException as ex:
            return not_found(error(f'{ex}'))
        except Exception as ex:
            return internal_server_error(error(f'{ex}'))
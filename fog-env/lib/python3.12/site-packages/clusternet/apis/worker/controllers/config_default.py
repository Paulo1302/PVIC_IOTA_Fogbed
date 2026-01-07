from clusternet.apis.presentation.exceptions import BadRequestException, NotFoundException
from clusternet.apis.presentation.helpers import (
    bad_request, error, internal_server_error, not_found, success
)
from clusternet.apis.presentation.protocols import Controller, HttpRequest, HttpResponse
from clusternet.apis.worker.helpers import WorkerInstance, get_hostname

class ConfigDefaultController(Controller):
    def __init__(self, name: str) -> None:
        self.name = name
        self.net  = WorkerInstance.instance()

    def handle(self, request: HttpRequest) -> HttpResponse:
        name = self.name
        hostname = get_hostname()

        try:    
            if(not name in self.net):
                raise NotFoundException(f'[{hostname}]: node {name} not found')
            
            self.net.getHost(name).configDefault()

            return success({'content': f'[{hostname}]: node {name} configured with default interfaces'})

        except BadRequestException as ex:
            return bad_request(error(f'{ex}'))
        except NotFoundException as ex:
            return not_found(error(f'{ex}'))
        except Exception as ex:
            return internal_server_error(error(f'{ex}'))
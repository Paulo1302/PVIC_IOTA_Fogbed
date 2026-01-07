from functools import partial

from clusternet.apis.presentation.exceptions import BadRequestException
from clusternet.apis.presentation.helpers import (
    bad_request, created, error, internal_server_error, validate_required_params
)
from clusternet.apis.presentation.protocols import Controller, HttpRequest, HttpResponse
from clusternet.apis.worker.helpers import WorkerInstance, get_hostname

from mininet.node import RemoteController

class AddController(Controller):
    def __init__(self) -> None:
        self.net = WorkerInstance.instance()

    def handle(self, request: HttpRequest) -> HttpResponse:
        required_params = ['name', 'ip', 'port']
        hostname = get_hostname()

        try:
            validate_required_params(request, required_params)
            name = str(request.body['name'])
            ip   = str(request.body['ip'])
            port = int(request.body['port'])

            if(name in self.net):
                raise Exception(f'[{hostname}]: controller {name} already exist')

            controller = partial(RemoteController, ip=ip, port=port)
            self.net.addController(name, controller)
            return created({'content': f'[{hostname}]: controller {name} created'})

        except BadRequestException as ex:
            return bad_request(error(f'{ex}'))
        except Exception as ex:
            return internal_server_error(error(f'{ex}'))

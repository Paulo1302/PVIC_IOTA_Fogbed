from clusternet.apis.presentation.exceptions import BadRequestException
from clusternet.apis.presentation.helpers import (
    bad_request, error, internal_server_error, success, validate_required_params
)
from clusternet.apis.presentation.protocols import Controller, HttpRequest, HttpResponse
from clusternet.apis.worker.helpers import WorkerInstance, get_hostname

class RemoveLinkController(Controller):
    def __init__(self) -> None:
        self.net = WorkerInstance.instance()

    def handle(self, request: HttpRequest) -> HttpResponse:
        required_params = ['node1', 'node2']
        hostname = get_hostname()

        try:
            validate_required_params(request, required_params)
            node1 = str(request.body['node1'])
            node2 = str(request.body['node2'])
            self.net.removeLink(node1=node1, node2=node2)

            return success({'content': f'[{hostname}]: link removed between {node1} and {node2}'})

        except BadRequestException as ex:
            return bad_request(error(f'{ex}'))
        except Exception as ex:
            return internal_server_error(error(f'{ex}'))

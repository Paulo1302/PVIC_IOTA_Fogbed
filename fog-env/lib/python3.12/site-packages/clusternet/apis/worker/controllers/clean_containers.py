from clusternet.apis.presentation.exceptions import BadRequestException
from clusternet.apis.presentation.helpers import (
    bad_request, error, internal_server_error, success, validate_required_params
)
from clusternet.apis.presentation.protocols import Controller, HttpRequest, HttpResponse
from clusternet.apis.worker.helpers import (
    get_hostname, clean_containers_with_prefix, WorkerInstance
)


class CleanContainersController(Controller):
    def __init__(self) -> None:
        pass
    
    def handle(self, request: HttpRequest) -> HttpResponse:
        try:
            validate_required_params(request, ['containers_prefix'])
            prefix = str(request.body['containers_prefix'])
            containers = clean_containers_with_prefix(prefix)
            
            WorkerInstance.clear_instance()
            return success({'content': f'[{get_hostname()}]: Cleaned containers: {containers}'})
        except BadRequestException as ex:
            return bad_request(error(f'{ex}'))
        except Exception as ex:
            return internal_server_error(error(f'{ex}'))
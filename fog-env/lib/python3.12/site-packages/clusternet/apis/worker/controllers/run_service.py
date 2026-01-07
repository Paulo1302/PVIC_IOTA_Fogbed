from clusternet.apis.presentation.exceptions import BadRequestException
from clusternet.apis.presentation.helpers import (
    bad_request, created, error, internal_server_error, validate_required_params
)
from clusternet.apis.presentation.protocols import Controller, HttpRequest, HttpResponse
from clusternet.apis.worker.helpers import get_hostname, run_container


class RunServiceController(Controller):
    def __init__(self) -> None:
        pass
    
    def handle(self, request: HttpRequest) -> HttpResponse:
        required_params = ['name', 'image']
        try:
            hostname = get_hostname()
            validate_required_params(request, required_params)
            
            name = str(request.body.pop('name'))
            image = str(request.body.pop('image'))
            run_container(name, image, **request.body)
            
            return created({'content': f'[{hostname}]: service {name} created'})
        except BadRequestException as ex:
            return bad_request(error(f'{ex}'))
        except Exception as ex:
            return internal_server_error(error(f'{ex}'))

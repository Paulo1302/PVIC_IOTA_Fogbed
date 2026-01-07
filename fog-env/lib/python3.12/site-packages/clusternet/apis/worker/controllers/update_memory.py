from clusternet.apis.presentation.exceptions import BadRequestException, NotFoundException
from clusternet.apis.presentation.helpers import bad_request, error, internal_server_error, not_found, success, validate_required_params
from clusternet.apis.presentation.protocols import Controller, HttpRequest, HttpResponse
from clusternet.apis.worker.helpers import WorkerInstance, get_hostname


class UpdateMemoryController(Controller):
    def __init__(self, name: str) -> None:
        self.name = name
        self.net  = WorkerInstance.instance()

    def handle(self, request: HttpRequest) -> HttpResponse:
        hostname = get_hostname()
        required_params = ['mem_limit']

        try:
            if(not self.name in self.net):
                raise NotFoundException(f'[{hostname}]: container {self.name} not found')

            validate_required_params(request, required_params)
            mem_limit = int(request.body['mem_limit'])
            
            docker = self.net.getDocker(name=self.name)
            docker.updateMemoryLimit(mem_limit)

            return success({'content': f'[{hostname}]: container {self.name} memory updated'})
            
        except BadRequestException as ex:
            return bad_request(error(f'{ex}'))
        except NotFoundException as ex:
            return not_found(error(f'{ex}'))
        except Exception as ex:
            return internal_server_error(error(f'{ex}'))

from clusternet.apis.presentation.exceptions import BadRequestException, NotFoundException
from clusternet.apis.presentation.helpers import (
    bad_request, error, internal_server_error, not_found, success, validate_required_params
)
from clusternet.apis.presentation.protocols import Controller, HttpRequest, HttpResponse
from clusternet.apis.worker.helpers import WorkerInstance, get_hostname


class UpdateCPUController(Controller):
    def __init__(self, name: str) -> None:
        self.name = name
        self.net  = WorkerInstance.instance()

    def handle(self, request: HttpRequest) -> HttpResponse:
        hostname = get_hostname()
        required_params = ['cpu_quota', 'cpu_period']

        try:
            if(not self.name in self.net):
                raise NotFoundException(f'[{hostname}]: container {self.name} not found')

            validate_required_params(request, required_params)
            cpu_quota = int(request.body['cpu_quota'])
            cpu_period = int(request.body['cpu_period'])
            
            docker = self.net.getDocker(name=self.name)
            docker.updateCpuLimit(cpu_quota, cpu_period)

            return success({'content': f'[{hostname}]: container {self.name} cpu updated'})
            
        except BadRequestException as ex:
            return bad_request(error(f'{ex}'))
        except NotFoundException as ex:
            return not_found(error(f'{ex}'))
        except Exception as ex:
            return internal_server_error(error(f'{ex}'))

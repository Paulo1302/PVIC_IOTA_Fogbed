from clusternet.apis.presentation.helpers import error, internal_server_error, success
from clusternet.apis.presentation.protocols import Controller, HttpRequest, HttpResponse
from clusternet.apis.worker.helpers import WorkerInstance, get_hostname

class RunPingallController(Controller):
    def __init__(self) -> None:
        self.net = WorkerInstance.instance()
    
    def handle(self, request: HttpRequest) -> HttpResponse:
        hostname = get_hostname()

        try:
            if(not self.net.is_running):
                raise Exception(f'[{hostname}]: Containernet is not running')

            packets = self.net.pingAll()
            
            return success({'content': f'{packets}% dropped', 'dropped': packets})
        except Exception as ex:
            return internal_server_error(error(f'{ex}'))
    
from clusternet.apis.presentation.helpers import error, internal_server_error, success
from clusternet.apis.presentation.protocols import Controller, HttpRequest, HttpResponse
from clusternet.apis.worker.helpers import WorkerInstance, get_hostname


class StopWorkerController(Controller):
    def __init__(self) -> None:
        self.net = WorkerInstance.instance()
    
    def handle(self, request: HttpRequest) -> HttpResponse:
        hostname = get_hostname()

        try:
            if(not self.net.is_running):
                self.net.stop_hosts()
                WorkerInstance.clear_instance()
                raise Exception(f'[{hostname}]: Containernet already is stopped')

            self.net.stop()
            WorkerInstance.clear_instance()
        except Exception as ex:
            message = f'{ex}'
            return internal_server_error(error(message))
        
        return success({'content': f'[{hostname}]: Containernet stopped'})
            
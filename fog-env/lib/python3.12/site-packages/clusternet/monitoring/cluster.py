import os
from typing import List

from clusternet.client.worker import RemoteWorker

from clusternet.monitoring.helpers import (
    create_grafana_files, create_prometheus_file, resolve_ip
)
from clusternet.monitoring.services import (
    CLUSTERNET_PREFIX, 
    clean_containers, clean_workers, run_cadvisor, 
    run_grafana, run_node_exporters, run_prometheus
)

DATA_PATH = '/tmp/fogbed'
GRAFANA_PATH = f'{DATA_PATH}/grafana'
PROMETHEUS_PATH = f'{DATA_PATH}/prometheus'


class ClusterMonitoring:
    def __init__(self, 
        monitor_server: str, 
        scrape_interval: int = 1,
        grafana_uid: str = 'clusternet',
        workers: 'List[RemoteWorker] | None' = None
    ):
        self.monitor_server = monitor_server
        self.scrape_interval = scrape_interval
        self.grafana_uid = grafana_uid
        self.workers = workers


    def get_ip_targets(self) -> List[str]:
        if(self.workers is None):
            return [self.monitor_server]
        return [worker.ip for worker in self.workers]


    def create_data_folders(self, directories: List[str]):
        for directory in directories:
            os.makedirs(directory, exist_ok=True)
        
        monitor_server = resolve_ip(self.monitor_server)
        create_grafana_files(
            grafana_path=GRAFANA_PATH,
            grafana_uid=self.grafana_uid,
            prometheus_url=f'http://{monitor_server}:9090')
        create_prometheus_file(
            prometheus_path=PROMETHEUS_PATH,
            scrape_interval=self.scrape_interval,
            workers=self.get_ip_targets())

    
    def stop(self):
        clean_containers(prefix=CLUSTERNET_PREFIX)
        if(self.workers is not None):
            clean_workers(self.workers)

    
    def start(self):
        self.create_data_folders([GRAFANA_PATH, PROMETHEUS_PATH])
        
        if(self.workers is None):
            run_cadvisor()
        else:
            run_node_exporters(self.workers)

        run_prometheus(PROMETHEUS_PATH)
        run_grafana(GRAFANA_PATH)        
        print(f'[{self.monitor_server}]: Prometheus address http://localhost:9090/graph')
        print(f'[{self.monitor_server}]: Grafana address http://localhost:3000/d/{self.grafana_uid}/docker-monitoring')

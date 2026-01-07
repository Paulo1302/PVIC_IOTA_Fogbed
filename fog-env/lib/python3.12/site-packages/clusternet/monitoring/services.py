import docker
from typing import Any, List

from clusternet.client.worker import RemoteWorker

try:
    client = docker.from_env()
except:
    pass

CLUSTERNET_PREFIX = 'cn.'

def clean_containers(prefix: str):
    for container in client.containers.list(all=True):
        name = str(container.name) # type: ignore
        if(name.startswith(prefix)):
            container.remove(force=True) # type: ignore


def run_container(name: str, image: str, **params: Any):
    client.containers.run(image, name=name, remove=True, detach=True, **params)


def run_cadvisor():
    run_container(
        name=CLUSTERNET_PREFIX + 'cadvisor',
        image='gcr.io/cadvisor/cadvisor:v0.47.2',
        ports={'8080/tcp': 8080},
        volumes=[
            '/:/rootfs:ro',
            '/var/run:/var/run:ro',
            '/sys:/sys:ro',
            '/var/lib/docker/:/var/lib/docker:ro',
            '/dev/disk/:/dev/disk:ro'],
        devices=['/dev/kmsg'],
        privileged=True)


def run_grafana(grafana_path: str):
    run_container(
        name=CLUSTERNET_PREFIX + 'grafana',
        image='grafana/grafana-enterprise',
        ports={'3000/tcp': 3000},
        volumes=[f'{grafana_path}:/etc/grafana'],
        environment={
            'GF_PATHS_PROVISIONING': '/etc/grafana',
            'GF_SECURITY_ADMIN_PASSWORD': 'admin123'})


def run_prometheus(prometheus_path: str):
    run_container(
        name=CLUSTERNET_PREFIX + 'prometheus',
        image='prom/prometheus',
        ports={'9090/tcp': 9090},
        volumes=[f'{prometheus_path}:/etc/prometheus'])


def run_node_exporters(workers: List[RemoteWorker]):
    for worker in workers:
        worker.run_service(
            name=CLUSTERNET_PREFIX + 'cadvisor',
            image='gcr.io/cadvisor/cadvisor:v0.47.2',
            ports={'8080/tcp': 8080},
            volumes=[
                '/:/rootfs:ro',
                '/var/run:/var/run:ro',
                '/sys:/sys:ro',
                '/var/lib/docker/:/var/lib/docker:ro',
                '/dev/disk/:/dev/disk:ro'],
            devices=['/dev/kmsg'],
            privileged=True)


def clean_workers(workers: List[RemoteWorker]):
    for worker in workers:
        worker.clean_containers(prefix=CLUSTERNET_PREFIX)

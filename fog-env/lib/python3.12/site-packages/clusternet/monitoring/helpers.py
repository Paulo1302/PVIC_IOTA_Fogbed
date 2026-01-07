from pathlib import Path
import shutil
import socket
from typing import List
import yaml


BASEDIR = str(Path(__file__).parent.parent)


def get_file_content(filename: str) -> str:
    with open(filename, mode='r', encoding='utf-8') as file:
        return file.read()

def save_file_content(filename: str, content: str):
    with open(filename, mode='w', encoding='utf-8') as file:
        file.write(content)

def resolve_ip(ip: str) -> str:
    return socket.gethostbyname(ip)

def create_jobs(workers: List[str], scrape_interval: int):
    jobs = []
    for worker in workers:
        jobs.append({
            'job_name': worker, 
            'scrape_interval': f'{scrape_interval}s', 
            'static_configs': [{'targets': [f'{resolve_ip(worker)}:8080']}]
        })
    return jobs


def update_datasource(grafana_path: str, grafana_uid: str, prometheus_url: str):
    content = get_file_content(f'{grafana_path}/datasources/datasource.yml')
    datasource = content.replace('$PROMETHEUS_URL', prometheus_url).replace('$UID', grafana_uid)
    save_file_content(f'{grafana_path}/datasources/datasource.yml', datasource)


def update_dashboard_data(grafana_path: str, grafana_uid: str):
    content = get_file_content(f'{grafana_path}/dashboards/docker.json')
    dashboard_data = content.replace('$UID', grafana_uid)
    save_file_content(f'{grafana_path}/dashboards/docker.json', dashboard_data)


def create_grafana_files(grafana_path: str, grafana_uid: str, prometheus_url: str):
    shutil.copytree(f'{BASEDIR}/grafana', grafana_path, dirs_exist_ok=True)
    update_datasource(grafana_path, grafana_uid, prometheus_url)
    update_dashboard_data(grafana_path, grafana_uid)
    

def create_prometheus_file(prometheus_path: str, workers: List[str], scrape_interval: int):
    jobs = create_jobs(workers, scrape_interval)
    content = yaml.safe_dump({'scrape_configs': jobs})
    save_file_content(f'{prometheus_path}/prometheus.yml', content)

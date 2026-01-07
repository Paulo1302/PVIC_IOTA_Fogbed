import argparse
import os

from flask import Flask, jsonify, request
from flask.wrappers import Request

from clusternet.apis.worker.controllers import (
    AddController, AddDockerController, AddLinkController, AddSwitchController,
    CleanContainersController, ConfigDefaultController, GetDockerIPController,
    RemoveDockerController, RemoveLinkController, RunCommandOnHostController, 
    RunServiceController, RunPingallController, StartDockerController, 
    StopDockerController, StartWorkerController, StopWorkerController, 
    UpdateCPUController, UpdateMemoryController
)
from clusternet.apis.presentation.helpers import parse_request
from clusternet.apis.presentation.protocols import Controller


server = Flask(__name__)


def make_response(controller: Controller, request: Request):
    response = controller.handle(parse_request(request))
    return jsonify(response.body), response.status_code

@server.route('/controllers', methods=['POST'])
def add_controller():
    controller = AddController()
    return make_response(controller, request)


@server.route('/containers', methods=['POST'])
def add_docker():
    controller = AddDockerController()
    return make_response(controller, request)


@server.route('/containers/clean', methods=['POST'])
def clean_containers():
    controller = CleanContainersController()
    return make_response(controller, request)


@server.route('/containers/<string:name>/ip', methods=['GET'])
def get_ip(name: str):
    controller = GetDockerIPController(name)
    return make_response(controller, request)


@server.route('/containers/<string:name>/start', methods=['GET'])
def start_docker(name: str):
    controller = StartDockerController(name)
    return make_response(controller, request)


@server.route('/containers/<string:name>/stop', methods=['GET'])
def stop_docker(name: str):
    controller = StopDockerController(name)
    return make_response(controller, request)


@server.route('/containers/<string:name>', methods=['DELETE'])
def remove_docker(name: str):
    controller = RemoveDockerController(name)
    return make_response(controller, request)


@server.route('/containers/<string:name>/cpu', methods=['PUT'])
def update_cpu(name: str):
    controller = UpdateCPUController(name)
    return make_response(controller, request)


@server.route('/containers/<string:name>/memory', methods=['PUT'])
def update_memory(name: str):
    controller = UpdateMemoryController(name)
    return make_response(controller, request)


@server.route('/links', methods=['POST'])
def add_link():
    controller = AddLinkController()
    return make_response(controller, request)


@server.route('/links/remove', methods=['POST'])
def remove_link():
    controller = RemoveLinkController()
    return make_response(controller, request)


@server.route('/switches', methods=['POST'])
def add_switch():
    controller = AddSwitchController()
    return make_response(controller, request)


@server.route('/hosts/<string:name>/config', methods=['GET'])
def config_default(name: str):
    controller = ConfigDefaultController(name)
    return make_response(controller, request)


@server.route('/hosts/<string:name>/cmd', methods=['POST'])
def run_command(name: str):
    controller = RunCommandOnHostController(name)
    return make_response(controller, request)


@server.route('/hosts/pingall', methods=['GET'])
def run_pingall():
    controller = RunPingallController()
    return make_response(controller, request)


@server.route('/services', methods=['POST'])
def run_service():
    controller = RunServiceController()
    return make_response(controller, request)


@server.route('/start', methods=['GET'])
def start():
    controller = StartWorkerController()
    return make_response(controller, request)


@server.route('/stop', methods=['GET'])
def stop():
    controller = StopWorkerController()
    return make_response(controller, request)


def main():
    parser = argparse.ArgumentParser('sudo RunWorker')
    parser.add_argument('-p', '--port', type=int, default=5000, help='run server on especified port (default: 5000)')
    args = parser.parse_args()
    
    server.run(host='0.0.0.0', port=int(os.environ.get('PORT', args.port)))

if(__name__=='__main__'):
    main()
    
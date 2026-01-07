import httpx


class RemoteContainer:
    def __init__(self, name: str, url: str) -> None:
        self.name = name
        self.url = url

    def cmd(self, command: str) -> str:
        data = {'command': command}
        response = httpx.post(url=f'{self.url}/hosts/{self.name}/cmd', json=data, timeout=None)
        
        if(response.is_error):
            raise Exception(response.json()['error']) 
        return response.json()['content']
    
    
    def config_default(self):
        response = httpx.get(url=f'{self.url}/hosts/{self.name}/config', timeout=None)
        
        if(response.is_error):
            raise Exception(response.json()['error'])
        print(f'{response.json()["content"]}')
    

    def get_ip(self) -> str:
        response = httpx.get(url=f'{self.url}/containers/{self.name}/ip', timeout=None)
        
        if(response.is_error):
            raise Exception(response.json()['error'])
        return response.json()['content']


    def update_cpu(self, cpu_quota: int, cpu_period: int):
        data = {'cpu_quota': cpu_quota, 'cpu_period': cpu_period}
        response = httpx.put(url=f'{self.url}/containers/{self.name}/cpu', json=data, timeout=None)

        if(response.is_error):
            raise Exception(response.json()['error'])
        print(f'{response.json()["content"]}')
    

    def update_memory(self, mem_limit: int):
        data = {'mem_limit': mem_limit}
        response = httpx.put(url=f'{self.url}/containers/{self.name}/memory', json=data, timeout=None)

        if(response.is_error):
            raise Exception(response.json()['error'])
        print(f'{response.json()["content"]}')


    def start(self):
        response = httpx.get(url=f'{self.url}/containers/{self.name}/start', timeout=None)

        if(response.is_error):
            raise Exception(response.json()['error'])
        print(f'{response.json()["content"]}')
    

    def stop(self):
        response = httpx.get(url=f'{self.url}/containers/{self.name}/stop', timeout=None)

        if(response.is_error):
            raise Exception(response.json()['error'])
        print(f'{response.json()["content"]}')
        
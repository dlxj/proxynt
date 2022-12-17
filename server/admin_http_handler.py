import json
import uuid
from typing import List, Set

from tornado.web import RequestHandler, StaticFileHandler

from common.logger_factory import LoggerFactory
from context.context_utils import ContextUtils
from entity.message.push_config_entity import PushConfigEntity, ClientData
from entity.server_config_entity import ServerConfigEntity
from server.websocket_handler import MyWebSocketaHandler

COOKIE_KEY = 'c'
cookie_set = set()


class AdminHtmlHandler(RequestHandler):
    async def get(self):
        result = self.get_cookie(COOKIE_KEY)
        if result in cookie_set:
            self.render('ele_index.html')
        else:
            self.render('login.html')

    async def post(self):
        body_data= json.loads(self.request.body)
        password = body_data['password']
        if password == ContextUtils.get_password():
            uid = uuid.uuid4().hex
            cookie_set.add(uid)
            self.set_cookie(COOKIE_KEY, uid)
            self.write({
                'code': 200,
                'data': '',
                'msg': ''
            })
        else:
            self.write({
                'code': 400,
                'data': '',
                'msg': '密码错误'
            })





class AdminHttpApiHandler(RequestHandler):
    async def get(self):
        online_client_name_list: List[str] = list(MyWebSocketaHandler.client_name_to_handler.keys())
        return_list = []
        client_name_to_config_list_in_server = ContextUtils.get_client_name_to_config_in_server()
        online_set: Set[str] = set()
        for client_name in online_client_name_list:
            handler = MyWebSocketaHandler.client_name_to_handler.get(client_name)
            push_config: PushConfigEntity = handler.push_config
            if handler is None:
                continue
            config_list = push_config['config_list']  # 转发配置列表
            name_in_server: List[str] = list()
            for x in client_name_to_config_list_in_server.get(client_name, []):
                name_in_server.append(x['name'])
            return_list.append({
                'client_name': client_name,
                'config_list': config_list,
                'status': 'online',
                'can_delete_names': [x['name'] for x in client_name_to_config_list_in_server.get(client_name, [])]
                # 配置在服务器上的, 可以删除
            })
            online_set.add(client_name)

        for client_name, config_list in client_name_to_config_list_in_server.items():
            if client_name in online_set:
                continue
            return_list.append({
                'client_name': client_name,
                'config_list': config_list,
                'status': 'offline',
                'can_delete_names': [x['name'] for x in client_name_to_config_list_in_server.get(client_name, [])]
            })
        return_list.sort(key=lambda x: x['client_name'])
        self.write({
            'code': 200,
            'data': return_list,
            'msg': ''
        })

    def delete(self, *args, **kwargs):
        # request_data = json.loads(self.request.body)
        client_name = self.get_argument('client_name')
        name = self.get_argument('name')
        LoggerFactory.get_logger().info(f'delete {client_name}, {name}')
        if not client_name or not name:
            self.write({
                'code': 400,
                'data': '',
                'msg': 'client ,name 不能为空'
            })
            return
        client_to_server_config = ContextUtils.get_client_name_to_config_in_server()
        old_config = client_to_server_config[client_name]
        new_config = [x for x in old_config if x['name'] != name]
        client_to_server_config[client_name] = new_config
        self.write({
            'code': 200,
            'data': '',
            'msg': ''
        })
        self.update_config_file()
        if client_name in MyWebSocketaHandler.client_name_to_handler:
            MyWebSocketaHandler.client_name_to_handler[client_name].close(0, 'close by server')
        # for c in old_config:
        #     if c['name'] != name:
        #         new_config.append(c)
        #

    async def post(self):
        request_data = json.loads(self.request.body)
        LoggerFactory.get_logger().info(f'add config {request_data}')
        client_name = request_data.get('client_name')
        name = request_data.get('name')
        remote_port = int(request_data.get('remote_port'))
        local_ip = request_data.get('local_ip')
        local_port = int(request_data.get('local_port'))
        if not client_name:
            self.write({
                'code': 400,
                'data': '',
                'msg': 'client name 不能为空'
            })
            return
        if not remote_port:
            self.write({
                'code': 400,
                'data': '',
                'msg': '当前客户端不在线或不存在'
            })
            return
        if not local_ip:
            self.write({
                'code': 400,
                'data': '',
                'msg': '必填local_ip'
            })
            return
        if not local_port or (local_port <= 0 or local_port > 65535):
            self.write({
                'code': 400,
                'data': '',
                'msg': '本地port不合法'
            })
            return
        if not name or (name in MyWebSocketaHandler.name_to_tcp_forward_client):
            self.write({
                'code': 400,
                'data': '',
                'msg': 'name不合法'
            })
            return
        if self.is_port_in_use(remote_port):
            self.write({
                'code': 400,
                'data': '',
                'msg': '远程端口已占用, 请更换端口'
            })
            return
        new_config: ClientData = {
            'name': name,
            'remote_port': remote_port,
            'local_port': local_port,
            'local_ip': local_ip
        }

        client_name_to_config_in_server = ContextUtils.get_client_name_to_config_in_server()
        config_file_path = ContextUtils.get_config_file_path()
        if client_name in client_name_to_config_in_server:
            for c in client_name_to_config_in_server[client_name]:
                if c['name'] == name:
                    self.write({
                        'code': 400,
                        'data': '',
                        'msg': 'name不合法'
                    })
                    return
            client_name_to_config_in_server[client_name].append(new_config)  # 更新配置
        else:
            client_name_to_config_in_server[client_name] = [new_config]  # 更新配置
        if client_name in MyWebSocketaHandler.client_name_to_handler:
            MyWebSocketaHandler.client_name_to_handler[client_name].close(0, 'close by server')
        self.write({
            'code': 200,
            'data': '',
            'msg': '成功'
        })
        self.update_config_file()
        return
        # with open(config_file_path, 'rb') as rf:
        #     server_config_data: ServerConfigEntity = json.load(rf)
        # client_config = server_config_data.get('client_config')
        # if not client_config:
        #     pass

    def update_config_file(self):
        with open(ContextUtils.get_config_file_path(), 'r') as rf:
            content = rf.read()
        server_config: ServerConfigEntity = json.loads(content)
        server_config['client_config'] = ContextUtils.get_client_name_to_config_in_server()
        with open(ContextUtils.get_config_file_path(), 'w') as wf:
            wf.write(json.dumps(server_config, ensure_ascii=False, indent=4))

    @staticmethod
    def is_port_in_use(port: int) -> bool:
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(('localhost', port)) == 0
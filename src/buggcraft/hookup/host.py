# tunnel_host.py
import json
import socket
import threading
import logging
import sys
import signal
import struct

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("tunnel_host.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("TunnelHost")

def signal_handler(sig, frame):
    logger.info("检测到Ctrl+C，程序正在退出...")
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

class TunnelHost:
    def __init__(self, server_host='81.68.225.236', control_port=3333,
                 game_host='127.0.0.1', game_port=25565, host_id=1):
        self.control_port = control_port
        self.server_host = server_host
        self.game_host = game_host
        self.game_port = game_port
        self.host_id = host_id
        self.running = True

        self.send_data = {
            "id": None,
            "name": self.host_id,                   # 客户端唯一ID
            "type": 'host',                       # 当前为客户端
        }
        
        self.control_conn = None
        self.active_sessions = {}  # client_id -> (game_conn, server_conn)

    def create_forward_session(self, control, target_client_id, port):
        """与服务端数据端口建立连接进行数据转发路由"""
        # TODO 这里应该用线程！！！

        # 连接到服务端的数据端口
        data_conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # data_conn.settimeout(10)
        data_conn.connect((self.server_host, port))  # 数据端口
        
        # 连接到游戏服务器
        game_conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        game_conn.connect((self.game_host, self.game_port))
        logger.info(f"客户端会话{target_client_id}: 已连接到游戏服务器")

        # 发送通知到数据端口，告知服务端主机端准备已就绪，要开始转发数据
        data_conn.sendall(json.dumps({
            **self.send_data,
            "target_client_id": target_client_id
        }).encode('utf-8'))
        logger.info(f"主机端已连接到数据端")
        
        # 启动双向转发
        def forward_game_to_server():
            try:
                while True:
                    data = game_conn.recv(4096)
                    if not data:
                        break
                    data_conn.send(data)
            except:
                pass
        
        def forward_server_to_game():
            try:
                while True:
                    data = data_conn.recv(4096)
                    if not data:
                        break
                    game_conn.send(data)
            except:
                pass
        
        t1 = threading.Thread(target=forward_game_to_server, daemon=True)
        t2 = threading.Thread(target=forward_server_to_game, daemon=True)
        t1.start()
        t2.start()
        
        t1.join()
        t2.join()
        
        data_conn.close()
        game_conn.close()
        logger.info(f"主机端已与数据端关闭")

    def start(self):
        """启动主机端"""
        try:
            # 连接到控制端
            self.control_conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.control_conn.connect((self.server_host, self.control_port))
            
            # 请求控制端分配临时ID
            self.control_conn.sendall(json.dumps({
                **self.send_data,
                "action": "register_id"    # 主机请求与服务端控制端进行平台注册
            }).encode('utf-8'))

            data = self.control_conn.recv(2048)
            command = json.loads(data.decode('utf-8'))
            self.send_data['id'] = command.get('register_id')


            # 发送主机端标识及主机端ID 进行平台注册
            self.control_conn.sendall(json.dumps({
                **self.send_data,
                "action": "register"    # 主机请求与服务端控制端进行平台注册
            }).encode('utf-8'))

            logger.info(f"主机 {self.send_data['id']} 已连接到控制端，等待客户端连接...")
            while self.running:
                try:
                    # 等待新客户端连接通知
                    data = self.control_conn.recv(2048)
                    if not data:
                        break
                    
                    command = json.loads(data.decode('utf-8'))
                    if command.get('type') == 'heartbeat':
                        # 心跳包
                        continue

                    if not command.get('type') in ['client', 'heartbeat']:
                        logger.error(f"[主机] 收到不支持的客户端连接请求类型 {command.get('type')}")
                        self.control_conn.close()
                        return
                    
                    if command.get('id', None) is None:
                        logger.error(f"[主机] 未提供主机端ID")
                        self.control_conn.close()
                        return
                    
                    if command.get('id', None) != self.send_data['id']:
                        logger.error(f"[主机] 客户端请求目标主机不匹配，貌似是路由错误")
                        self.control_conn.close()
                        return
                    
                    if command.get('target_client_id', None) is None:
                        logger.error(f"[主机] 未提供客户端ID")
                        self.control_conn.close()
                        return
                    
                    if command.get('forward_port', None) is None:
                        logger.error(f"[主机] 服务端未提供数据端口")
                        self.control_conn.close()
                        return
                    
                    # 客户端唯一ID
                    # 服务端提供的数据端口，主机需要与此端口建立连接进行数据交换
                    target_client_id = command.get('target_client_id')
                    forward_port = command.get('forward_port')

                    threading.Thread(
                        target=self.create_forward_session, daemon=True,
                        args=(self.control_conn, target_client_id, forward_port)
                    ).start()

                except socket.timeout:
                    continue
                except Exception as e:
                    logger.error(f"接收数据错误: {e}")
                    break
                    
        except Exception as e:
            logger.error(f"连接服务端失败: {e}")
        finally:
            self.shutdown()

    def shutdown(self):
        """关闭主机端"""
        self.running = False
        if self.control_conn:
            try:
                self.control_conn.close()
            except:
                pass
        logger.info("主机端已关闭")

# 81.68.225.236
if __name__ == '__main__':
    host = TunnelHost(
        server_host='81.68.225.236',
        control_port=3333,
        game_host='127.0.0.1',
        game_port=25565,
        host_id=1
    )
    host.start()

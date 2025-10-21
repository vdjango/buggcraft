# tunnel_client.py
import json
import socket
import threading
import logging
import time
import sys
import signal

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("tunnel_client.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("TunnelClient")

def signal_handler(sig, frame):
    logger.info("检测到Ctrl+C，程序正在退出...")
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)


def send_multicast(message, multicast_group, port, source_ip=None, ttl=128):
    """
    发送组播数据
    
    参数:
        message: 要发送的消息 (bytes)
        multicast_group: 组播组地址 (str)
        port: 端口号 (int)
        source_ip: 源IP地址 (str, 可选)
        ttl: 生存时间 (int, 默认128)
    """
    # 创建UDP套接字
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    
    try:
        # 设置TTL (生存时间)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)
        
        if source_ip:
            # 设置组播源地址
            source_ip_bin = socket.inet_aton(source_ip)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, source_ip_bin)
        
        # 发送数据到组播组
        sock.sendto(message, (multicast_group, port))
    except socket.error as e:
        print(f"套接字错误: {e}")
    finally:
        sock.close()


class TunnelClient:

    def __init__(self, server_host='127.0.0.1', control_port=3333,
                 listen_port=20000, client_id=24, target_host_id=1):
        self.timeout = 50
        self.listen_port = listen_port
        self.server_host = server_host
        self.control_port = control_port
        self.forward_port = None
        self.multicast_message = None

        self.client_id = client_id
        self.target_host_id = target_host_id
        self.running = True
        self.send_data = {
            "id": None,
            "name": self.client_id,                 # 客户端唯一ID
            "type": 'client',                       # 当前为客户端
            "target_host_id": self.target_host_id   # 与目标主机建立连接 主机唯一ID
        }
        self.listener = None

    def control_connection(self):
        # 连接到服务端-控制端
        print('连接到控制端', self.server_host, self.control_port)
        control_conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        control_conn.settimeout(self.timeout)
        control_conn.connect((self.server_host, self.control_port))
        self.control_register_id(control_conn)
        return control_conn
    
    def forward_connection(self, host, port):
        # 连接到服务端-数据端
        print('连接到数据端', host, port)
        forward_conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        forward_conn.settimeout(self.timeout)
        forward_conn.connect((host, port))
        return forward_conn

    def control_register_id(self, conn):
        # 请求控制端分配临时ID
        conn.sendall(json.dumps({
            **self.send_data,
            "action": "register_id"    # 主机请求与服务端控制端进行平台注册
        }).encode('utf-8'))
        response = conn.recv(2048)
        if not response:
            conn.close()
            return
        command = json.loads(response.decode('utf-8'))
        self.send_data['id'] = command.get('register_id')

    def control_action_connect(self, conn):
        # 发送客户端标识及客户端ID和目标主机ID
        conn.sendall(json.dumps({
            **self.send_data,
            "action": "connect"     # 请求服务端控制端与主机建立连接
        }).encode('utf-8'))
        
        # 等待控制端确认数据通道连接确认
        response = conn.recv(2048)
        if not response:
            conn.close()
            return False
        command = json.loads(response.decode('utf-8'))

        # 主机端唯一ID
        # 服务端提供的数据端口，客户端需要与此端口建立连接进行数据交换
        # self.target_host_id = command.get('target_host_id')
        self.forward_port = command.get('forward_port')
        return True

    def control_action_forward(self, conn):
        # 发送转发确认
        time.sleep(.2)
        conn.sendall(json.dumps({
            **self.send_data,
            "target_host_id": self.target_host_id,
            "action": "forward"    # 发送转发确认
        }).encode('utf-8'))
        time.sleep(.5)

    def forward_connect(self, conn):
        # 发送通知到数据端口，告知服务端客户端端准备已就绪，要开始转发数据
        conn.sendall(json.dumps({
            **self.send_data,
            "target_host_id": self.target_host_id
        }).encode('utf-8'))
    
    def forward(self, src, dst):
        # 启动双向转发
        try:
            while True:
                data = src.recv(4096)
                if not data:
                    break
                dst.send(data)
        except:
            pass

    def handle_game_connection(self, game_conn, addr):
        """处理游戏客户端连接"""
        try:
            # 连接到服务端-控制端
            control_conn = self.control_connection()
            if self.control_action_connect(control_conn):
                # 连接到服务端-数据端
                forward_conn = self.forward_connection(self.server_host, self.forward_port)

                # 发送通知到数据端口，告知服务端客户端端准备已就绪，要开始转发数据
                self.forward_connect(forward_conn)
                logger.info(f"客户端 {self.send_data['id']} 已连接到数据端")
                
                # 发送转发确认
                self.control_action_forward(control_conn)

                # game_to_server
                t1 = threading.Thread(
                    target=self.forward,
                    daemon=True,
                    args=(game_conn, forward_conn,)
                )
                # server_to_game
                t2 = threading.Thread(
                    target=self.forward,
                    daemon=True,
                    args=(forward_conn, game_conn,)
                )
                t1.start()
                t2.start()
                
                t1.join()
                t2.join()
            
        except Exception as e:
            logger.error(f"处理游戏连接错误: {e}")
            import traceback
            traceback.print_exc()
        finally:
            try:
                game_conn.close()
            except:
                pass
            try:
                control_conn.close()
            except:
                pass
            try:
                self.control_conn.close()
            except:
                pass
            self.control_conn = None
            logger.info(f"游戏客户端 {addr} 连接结束")

    def multicast(self):
        def send():
            while self.running:
                if self.multicast_message:
                    send_multicast(
                        message=str(self.multicast_message).encode(),
                        multicast_group='127.0.0.1',
                        source_ip='127.0.0.1',
                        port=4445,
                        ttl=128
                    )
                time.sleep(.5)
        
        thread = threading.Thread(
            target=send,
            daemon=True,
        )
        thread.start()

        pass
    
    def start_multicast_server(self):
        """启动控制服务"""
        # 连接到服务端-控制端
        control_conn = self.control_connection()
        self.multicast()

        while self.running:
            control_conn.send(json.dumps({**self.send_data, 'action': 'multicast'}).encode('utf-8'))
            r = control_conn.recv(2048)
            command = json.loads(r.decode('utf-8'))
            self.multicast_message = f"[MOTD]{command.get('message')}[/MOTD][AD]{self.listen_port}[/AD]"  # command.get('message')
            time.sleep(self.timeout - 2)

    def start(self):
        """启动客户端"""
        thread = threading.Thread(
            target=self.start_multicast_server,
            daemon=True
        )
        thread.start()
        
        try:
            self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.listener.bind(('0.0.0.0', self.listen_port))
            self.listener.listen(10)
            logger.info(f"客户端监听在端口 {self.listen_port}")
            
            while self.running:
                try:
                    game_conn, addr = self.listener.accept()
                    logger.info(f"接受新的游戏客户端连接: {addr}")
                    
                    # 为每个游戏连接创建独立线程
                    thread = threading.Thread(
                        target=self.handle_game_connection,
                        args=(game_conn, addr),
                        daemon=True
                    )
                    thread.start()
                
                except Exception as e:
                    if self.running:
                        logger.error(f"接受连接错误: {e}")
        
        except Exception as e:
            logger.error(f"启动客户端失败: {e}")
        finally:
            self.shutdown()

    def shutdown(self):
        """关闭客户端"""
        self.running = False
        if self.listener:
            try:
                self.listener.close()
            except:
                pass
        logger.info("客户端已关闭")

# 81.68.225.236
if __name__ == '__main__':
    client = TunnelClient(server_host='81.68.225.236', control_port=3333,
                         listen_port=20000, client_id=24, target_host_id='c4ae858b37ea57bea61cb078c5adc4bf')
    client.start()

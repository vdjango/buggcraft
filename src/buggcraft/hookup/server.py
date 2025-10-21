# tunnel_server.py
import json
import uuid
import random
import socket
import threading
import logging
import time
import sys
import signal
from collections import defaultdict

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("tunnel_server.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("TunnelServer")

def signal_handler(sig, frame):
    logger.info("检测到Ctrl+C，程序正在退出...")
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)


class IDGenerator:
    """自增计数器"""
    def __init__(self):
        self._lock = threading.Lock()
        self._next_id = 1
        self.items = [i for i in 'qwertyuiopasdfghjklzxcvbnm,./;-=!@#$%^&*()_+<>?:']
    
    def randint(self):
        return str(random.randint(10000, 90000))
    
    def sample(self):
        return ''.join(random.sample(self.items, 5))

    def uidx(self, name):
        return uuid.uuid5(uuid.NAMESPACE_DNS, str(name))

    def get_next_id(self, name):
        with self._lock:
            id = self._next_id
            self._next_id += 1
            return self.uidx(str(name) + str(id) + self.randint() + self.sample()).hex
    
class SessionManager:
    """会话管理器，处理多主机多客户端映射"""
    def __init__(self):
        self.sessions = {}  # session_id -> {host_conn, client_conn, host_id, client_id}
        self.host_sessions = defaultdict(list)  # host_id -> [session_ids]
        self.lock = threading.Lock()
        self.next_session_id = 1
    
    def create_session(self, host_id, host_conn, client_id, client_conn):
        with self.lock:
            session_id = self.next_session_id
            self.next_session_id += 1
            
            self.sessions[session_id] = {
                'host_conn': host_conn,
                'client_conn': client_conn,
                'host_id': host_id,
                'client_id': client_id,
                'created_at': time.time()
            }
            
            self.host_sessions[host_id].append(session_id)
            return session_id
    
    def remove_session(self, session_id):
        with self.lock:
            if session_id in self.sessions:
                session = self.sessions[session_id]
                host_id = session['host_id']
                
                # 从主机会话列表中移除
                if host_id in self.host_sessions and session_id in self.host_sessions[host_id]:
                    self.host_sessions[host_id].remove(session_id)
                
                # 清理空的主机条目
                if host_id in self.host_sessions and not self.host_sessions[host_id]:
                    del self.host_sessions[host_id]
                
                del self.sessions[session_id]
    
    def get_session(self, session_id):
        with self.lock:
            return self.sessions.get(session_id)
    
    def get_host_sessions(self, host_id):
        with self.lock:
            return [self.sessions[sid] for sid in self.host_sessions.get(host_id, [])]

class TunnelServer:

    def __init__(self, host='0.0.0.0', control_port=3333, forward_port=4444):
        self.host = host
        self.control_port = control_port  # 控制连接端口
        self.forward_port = forward_port  # 数据连接端口
        self.running = True
        
        # 会话管理
        self.session_manager = SessionManager()
        # ID自增器
        self.idgx = IDGenerator()
        
        # 连接管理
        self.control_connections = {}  # id -> socket  主机和客户端ID不能重复，俩者控制连接都在这里
        self.forward_connections = {}  # id -> socket  主机和客户端ID不能重复，俩者控制连接都在这里
        self.conn_lock = threading.Lock()
        
        # 服务套接字
        self.control_socket = None  # 控制端
        self.forward_socket = None  # 数据端

    def forward_data(self, src_conn, dst_conn, description, session_id):
        """通用数据转发函数"""
        try:
            while True:
                try:
                    data = src_conn.recv(4096)
                    if not data:
                        logger.info(f"会话{session_id}: {description} 连接关闭")
                        break
                    dst_conn.send(data)
                except ConnectionResetError:
                    logger.info(f"会话{session_id}: {description} 连接被重置")
                    break
                except ConnectionAbortedError:
                    logger.info(f"会话{session_id}: {description} 连接被中止")
                    break
                except socket.timeout:
                    continue
                except Exception as e:
                    logger.error(f"会话{session_id}: {description} 数据转发错误: {e}")
                    break
                
        except Exception as e:
            logger.error(f"会话{session_id}: {description} 转发线程异常: {e}")
        finally:
            # 清理会话
            self.session_manager.remove_session(session_id)
            try:
                src_conn.close()
            except:
                pass
            try:
                dst_conn.close()
            except:
                pass
    
    def heartbeat(self, type_id, typec='host'):
        """心跳"""
        hear = self.control_connections[type_id]

        def _hear(hear, type_id, typec):
            while self.running:
                # 发送心跳保持连接
                try:
                    hear.send(json.dumps({'type': 'heartbeat', 'id': type_id}).encode('utf-8'))
                    time.sleep(5)
                except:
                    logger.info(f"[控制] {'主机' if typec == 'host' else '客户端'} {type_id} 连接断开, 当前数据端活跃 {len(self.forward_connections.keys())}")
                    break

                logger.info(f"[控制] 当前转发客户端(主机不会关闭，是长连接) {'主机' if typec == 'host' else '客户端'} {len(self.control_connections.keys())} {len(self.forward_connections.keys())}")
                logger.info(f"[控制] 其他端：")
                for i in self.forward_connections.keys():
                    logger.info(i)
            
            with self.conn_lock:
                if type_id in self.control_connections:
                    try:
                        self.control_connections[type_id].close()
                    except:
                        pass
                    finally:
                        del self.control_connections[type_id]
                
                if type_id in self.forward_connections:
                    try:
                        self.forward_connections[type_id].close()
                    except:
                        pass
                    finally:
                        del self.forward_connections[type_id]
        
        threading.Thread(
            target=_hear,
            args=(hear, type_id, typec),
            daemon=True
        ).start()

    def auto_forward_heartbeat(self, types: list):
        # 其中一个链接关闭时另一个关闭
        def heart(types):
            while self.running:
                index = 0
                for forward in types:
                    if forward in self.forward_connections:
                        index += 1
                        print('auto_forward_heartbeat', forward)
                
                print('auto_forward_heartbeat', index, len(types))
                if index != len(types):
                    break

                time.sleep(2)
            
            for forward in types:
                try:
                    self.forward_connections[forward].close()
                except:
                    pass
                if forward in self.forward_connections:
                    del self.forward_connections[forward]
        
        threading.Thread(
            target=heart,
            args=(types,),
            daemon=True
        ).start()
    
    def forward(self, target_host_id, target_client_id):
        logger.info(f"[控制] 双端开始转发：")
        logger.info(f"      {target_host_id} <---> {target_client_id}")
        logger.info(f"                                  主机 <---> 客户端")
        # self.auto_forward_heartbeat([target_host_id, target_client_id])

        logger.info(self.forward_connections, )
        if target_client_id in self.forward_connections and target_host_id in self.forward_connections:
            logger.info('开始转发')
            host_conn = self.forward_connections[target_host_id]
            client_conn = self.forward_connections[target_client_id]
            # 创建会话
            session_id = self.session_manager.create_session(
                target_host_id, host_conn, target_client_id, client_conn
            )
            # 启动双向转发
            host_to_client = threading.Thread(
                target=self.forward_data,
                args=(host_conn, client_conn, "主机端", session_id),
                daemon=True
            )
            client_to_host = threading.Thread(
                target=self.forward_data,
                args=(client_conn, host_conn, "客户端", session_id),
                daemon=True
            )
            
            host_to_client.start()
            client_to_host.start()
            
            # 等待转发线程结束
            host_to_client.join()
            client_to_host.join()
        
        else:
            logger.info('不满足转发')

    def handle_control_connection(self, conn, addr):
        """处理控制端连接
        控制端 处理主机与客户端的连接，协调何时进行数据转发"""
        try:
            while self.running:
                try:
                    response = conn.recv(2048)
                except:
                    logger.info(f"[控制] 错误 {response}")
                    break

                if not response:
                    print('[控制] 关闭连接', response)
                    break

                command = json.loads(response.decode('utf-8'))

                if not command.get('type') in ['host', 'client']:
                    logger.error(f"[控制] 连接 {addr} 不支持的类型")
                    conn.close()
                    return
                
                action = command.get('action')
                if command.get('id', None) is None and action != "register_id":
                    logger.error(f"[控制] 连接 {addr} 缺失ID")
                    conn.close()
                    return

                type_id = command.get('id', None)
                name = command.get('name')
                typec = command.get('type')
                
                if typec in ['host', 'client'] and action == "register_id":
                    # 创建唯一临时ID，每次连接ID都不相同且不能相同，需要保证每个连接（相同客户端）ID都不同
                    # 此ID仅作为一次性ID使用，TCP链接结束释放
                    conn.sendall(json.dumps({'register_id': self.idgx.get_next_id(name)}).encode('utf-8'))
                    continue
                elif typec == 'host':
                    if action == "register":
                        # 身份验证等
                        with self.conn_lock:
                            self.control_connections[type_id] = conn
                            # 主机端需要维持在控制端的长连接
                            self.heartbeat(type_id, typec)
                            logger.info(f"[控制] 主机完成注册 {type_id}")
                    elif action == 'heartbeat':
                        conn.send(json.dumps({'action': 'heartbeat', 'id': type_id}).encode('utf-8'))
                    else:
                        logger.info(f"[控制] 主机{type_id}: 未知动作")
                elif typec == 'client':
                    target_host_id = command.get('target_host_id')
                    if action == "connect":
                        # 客户端请求与主机建立连接
                        with self.conn_lock:
                            logger.info(f"[控制] 客户端{type_id}: 请求连接")
                            host_control_conn = self.control_connections.get(target_host_id)
                            if not host_control_conn:
                                # 检查主机是否在线
                                logger.error(f"[控制] 客户端{type_id}: 主机 {target_host_id} 不在线")
                                conn.close()
                                return
                            
                            self.control_connections[type_id] = conn

                            # 通知主机端有新客户端连接，开始连接数据端口
                            # 发送客户端ID给主机端 并通知主机与数据端口进行连接
                            # TODO 此处需要实现Token双向认证及签名
                            host_control_conn.sendall(json.dumps({
                                "id": target_host_id,                   # 主机端唯一ID
                                "type": 'client',                      # 当前为客户端
                                "target_client_id": type_id,            # 客户端唯一ID，表示当前客户端要与主机建立连接
                                "forward_port": self.forward_port       # 主机需要与此端口建立连接
                            }).encode('utf-8'))
                            logger.info(f"[控制] 通知主机{type_id}: 建立数据通道")
                            
                            # 通知客户端开始连接数据端口
                            # 发送主机端ID给客户端 并通知客户端与数据端口进行连接
                            # TODO 此处需要实现Token双向认证及签名
                            conn.sendall(json.dumps({
                                "id": type_id,                          # 客户端唯一ID
                                "type": 'host',                         # 当前为客户端
                                "target_host_id": target_host_id,       # 与目标主机建立连接 主机唯一ID
                                "forward_port": self.forward_port       # 主机需要与此端口建立连接
                            }).encode('utf-8'))
                            logger.info(f"[控制] 通知客户{type_id}: 建立数据通道")
                            
                            self.heartbeat(type_id, typec)
                            logger.info(f"[控制] 客户端{type_id}: 连接已建立")
                    elif action == "forward":
                        target_host_id = command.get('target_host_id')
                        print("self.forward(target_host_id, type_id)")
                        self.forward(target_host_id, type_id)
                    elif action == 'heartbeat':
                        conn.send(json.dumps({'type': 'heartbeat', 'id': type_id}).encode('utf-8'))
                    elif action == 'multicast':
                        # 客户端广播MOTD数据
                        conn.send(json.dumps({'type': 'multicast', 'id': type_id, 'message': 'BUGG测试联机'}).encode('utf-8'))
                    else:
                        logger.info(f"[控制] 客户端{type_id}: 未知动作")
        except Exception as e:
            logger.error(f"处理主机{addr} 连接错误: {e}")  # : {e}
            import traceback
            traceback.print_exc()
        finally:
            try:
                if type_id is None:
                    return
            
                with self.conn_lock:
                    if type_id in self.control_connections:
                        try:
                            self.control_connections[type_id].close()
                        except:
                            pass
                        finally:
                            del self.control_connections[type_id]
                    
                    if type_id in self.forward_connections:
                        try:
                            self.forward_connections[type_id].close()
                        except:
                            pass
                        finally:
                            del self.forward_connections[type_id]
            except:
                pass

    def handle_forward_connection(self, conn, addr):
        """处理数据端连接"""
        try:
            # 读取客户端ID和目标主机ID（各4字节）
            response = conn.recv(2048).decode('utf-8')
            command = json.loads(response)

            if not command.get('type') in ['host', 'client']:
                logger.error(f"[数据] 连接 {addr} 不支持的类型")
                conn.close()
                return
            
            if command.get('id', None) is None:
                logger.error(f"[数据] 连接 {addr} 缺失ID")
                conn.close()
                return

            type_id = command.get('id', None)
            typec = command.get('type')

            if typec == 'host':
                # 需要交叉验证 是否在控制端完成注册
                with self.conn_lock:
                    host_control_conn = self.control_connections.get(type_id)
                    if not host_control_conn:
                        # 检查主机注册状态
                        logger.error(f"[数据] 控制端中不存在 {type_id} 主机")
                        conn.close()
                        return
                    
                    target_client_id = command.get('target_client_id')
                    if not target_client_id:
                        logger.error(f"[数据] 主机未提供有效的客户端ID")
                        conn.close()
                        return
                    
                    client_conn = self.control_connections.get(target_client_id)
                    if not client_conn:
                        # 检查主机注册状态
                        logger.error(f"[数据] 控制端中不存在 {target_client_id} 客户端")
                        conn.close()
                        return

                    self.forward_connections[type_id] = conn
                
                logger.info(f"[数据] 主机端 {type_id} 已建立数据端口的连接")

                pass
            elif typec == 'client':
                # 需要交叉验证 是否在控制端完成注册
                with self.conn_lock:
                    client_control_conn = self.control_connections.get(type_id)
                    if not client_control_conn:
                        # 检查客户端注册状态
                        logger.error(f"[数据] 控制端中不存在 {type_id} 客户端")
                        conn.close()
                        return
                    
                    target_host_id = command.get('target_host_id')
                    if not target_host_id:
                        logger.error(f"[数据] 主机未提供有效的客户端ID")
                        conn.close()
                        return

                    # 检查主机是否在线
                    host_conn = self.control_connections.get(target_host_id)
                    if not host_conn:
                        logger.error(f"[数据] 客户端{type_id}: 主机 {target_host_id} 不在线")
                        conn.close()
                        return

                    self.forward_connections[type_id] = conn
                
                logger.info(f"[数据] 客户端 {type_id} 已建立数据端口的连接")

        except Exception as e:
            logger.error(f"处理客户端{addr} 连接错误: {e}")

    def start_control_server(self):
        """启动控制端服务"""
        self.control_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.control_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.control_socket.bind((self.host, self.control_port))
        self.control_socket.listen(100)
        logger.info(f"[控制] 服务监听在 {self.host}:{self.control_port}")
        
        while self.running:
            try:
                conn, addr = self.control_socket.accept()
                threading.Thread(
                    target=self.handle_control_connection,
                    args=(conn, addr),
                    daemon=True
                ).start()
            except Exception as e:
                if self.running:
                    logger.error(f"[控制] 接收连接错误: {e}")

    def start_forward_server(self):
        """启动数据端服务"""
        self.forward_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.forward_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.forward_socket.bind((self.host, self.forward_port))
        self.forward_socket.listen(100)
        logger.info(f"[数据] 数据端服务监听在 {self.host}:{self.forward_port}")
        
        while self.running:
            try:
                conn, addr = self.forward_socket.accept()
                threading.Thread(
                    target=self.handle_forward_connection,
                    args=(conn, addr),
                    daemon=True
                ).start()
            except Exception as e:
                if self.running:
                    logger.error(f"[数据] 接受客户端连接错误: {e}")

    def start(self):
        """启动服务器"""
        logger.info("启动隧道服务器")
        
        # 启动控制端服务线程
        control_thread = threading.Thread(target=self.start_control_server, daemon=True)
        control_thread.start()
        
        # 启动数据端服务线程
        forward_thread = threading.Thread(target=self.start_forward_server, daemon=True)
        forward_thread.start()
        
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("收到停止信号")
        finally:
            self.shutdown()

    def shutdown(self):
        """关闭服务器"""
        self.running = False
        logger.info("正在关闭服务器...")
        
        # 关闭所有连接
        with self.conn_lock:
            for conn in list(self.control_connections.values()):
                try:
                    conn.close()
                except:
                    pass
            self.control_connections.clear()
            
            for conn in list(self.forward_connections.values()):
                try:
                    conn.close()
                except:
                    pass
            self.forward_connections.clear()
        
        # 关闭服务器套接字
        if self.control_socket:
            try:
                self.control_socket.close()
            except:
                pass
        if self.forward_socket:
            try:
                self.forward_socket.close()
            except:
                pass
        
        logger.info("服务器关闭完成")

if __name__ == '__main__':
    server = TunnelServer(host='0.0.0.0', control_port=3333, forward_port=3334)
    server.start()

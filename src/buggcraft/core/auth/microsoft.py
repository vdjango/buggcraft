import os
import time
import json
import traceback
import webbrowser
import logging

from urllib.parse import urlparse, parse_qs

from PySide6.QtCore import Signal, QObject, QTimer

from core.skin import process_skin_info



logger = logging.getLogger(__name__)


class MicrosoftAuthSignals(QObject):
    """Microsoft 认证信号"""
    success = Signal(str, dict)  # 用户名, UUID
    failure = Signal(str)       # 错误消息
    progress = Signal(str)      # 进度消息


class MinecraftSignals(QObject):
    """Minecraft 信号类"""
    output = Signal(str)
    started = Signal()
    stopped = Signal(int)  # 退出代码
    error = Signal(str)
    progress = Signal(int)  # 进度百分比


import base64
from datetime import datetime

class JWTDecoder:
    """JWT Token 解码器类"""
    
    def __init__(self, token=None):
        self.token = token
        self.header = None
        self.payload = None
        self.signature = None
        self.decoded = False
        
    def decode(self):
        """解码 JWT Token"""
        try:
            # 分割 token 的三个部分
            parts = self.token.split('.')
            if len(parts) != 3:
                raise ValueError("无效的 JWT Token: 必须包含三个部分")
            
            # 解码头部
            header_encoded = parts[0]
            self.header = self._decode_part(header_encoded)
            
            # 解码载荷
            payload_encoded = parts[1]
            self.payload = self._decode_part(payload_encoded)
            
            # 签名部分
            self.signature = parts[2]
            
            self.decoded = True
            return True
            
        except Exception as e:
            return False
    
    def _decode_part(self, part):
        """解码单个 JWT 部分"""
        # 添加必要的填充
        padding = len(part) % 4
        if padding:
            part += '=' * (4 - padding)
        
        # 解码
        decoded_bytes = base64.urlsafe_b64decode(part)
        return json.loads(decoded_bytes)
    
    def get_expiration(self):
        """获取过期时间"""
        if not self.decoded:
            if not self.decode():
                return None
        
        if 'exp' in self.payload:
            exp_timestamp = self.payload['exp']
            exp_datetime = datetime.fromtimestamp(exp_timestamp)
            exp_formatted = exp_datetime.strftime('%Y-%m-%d %H:%M:%S')
            
            return {
                'timestamp': exp_timestamp,
                'formatted': exp_formatted
            }
        return None
    
    def get_issued_at(self):
        """获取签发时间"""
        if not self.decoded:
            if not self.decode():
                return None
        
        if 'iat' in self.payload:
            iat_timestamp = self.payload['iat']
            iat_datetime = datetime.fromtimestamp(iat_timestamp)
            iat_formatted = iat_datetime.strftime('%Y-%m-%d %H:%M:%S')
            
            return {
                'timestamp': iat_timestamp,
                'formatted': iat_formatted
            }
        return None
    
    def is_expired(self):
        """检查 Token 是否已过期"""
        expiration = self.get_expiration()
        if not expiration:
            return None
        
        current_time = datetime.now().timestamp()
        return expiration['timestamp'] < current_time
    
    def get_all_claims(self):
        """获取所有声明（claims）"""
        if not self.decoded:
            if not self.decode():
                return None
        return self.payload
    
    def get_header(self):
        """获取头部信息"""
        if not self.decoded:
            if not self.decode():
                return None
        return self.header


import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from utils.network import minecraft_httpx



class MinecraftUser:
    """Minecraft 用户基类"""
    def __init__(self):
        self.uuid = None
        self.username = None
        self.token = None
        self.avatar = None
        self.last_login = None

    def is_authenticated(self):
        """检查用户是否已认证"""
        return bool(self.username and self.username != '' and self.token)

    def clear(self):
        """清除用户信息"""
        self.uuid = None
        self.username = None
        self.token = None
        self.avatar = None
        self.last_login = None

    def __str__(self):
        return f"{self.__class__.__name__}(username={self.username}, authenticated={self.is_authenticated()})"


class MicrosoftOnlineUser(MinecraftUser):
    """正版登录用户信息"""
    def __init__(self):
        super().__init__()
        self.refresh_token = None
        self.expires_at = None

    def is_token_valid(self):
        """检查令牌是否有效"""
        return self.expires_at and datetime.now() < self.expires_at

    def clear(self):
        super().clear()
        self.refresh_token = None
        self.expires_at = None


class MicrosoftOfflineUser(MinecraftUser):
    """离线登录用户信息"""
    def __init__(self):
        super().__init__()
        self.custom_skin = None
    
    def is_authenticated(self):
        """检查用户是否已认证"""
        return bool(self.username and self.username != '')


class Authenticator:
    """认证管理器"""
    def __init__(self):
        self.decoder = JWTDecoder()  # 创建解码器实例
        self.signals = MicrosoftAuthSignals()

        self.online = MicrosoftOnlineUser()
        self.offline = MicrosoftOfflineUser()
        self.current_mode = 'offline'  # 默认使用离线模式
    
    @property
    def current(self):
        """获取当前认证模式的用户"""
        if self.current_mode == 'online':
            return self.online
        return self.offline
    
    @current.setter
    def current(self, mode):
        """设置当前认证模式"""
        if mode not in ('online', 'offline'):
            raise ValueError("无效的认证模式，必须是 'online' 或 'offline'")
        self.current_mode = mode

    def set_mode_current(self, mode):
        """设置当前认证模式"""
        if mode not in ('online', 'offline'):
            raise ValueError("无效的认证模式，必须是 'online' 或 'offline'")
        self.current_mode = mode
    
    def switch_mode(self):
        """切换认证模式"""
        self.current_mode = 'online' if self.current_mode == 'offline' else 'offline'
        return self.current_mode
    
    def get_user(self, mode=None):
        """获取指定模式的用户"""
        if mode == 'online':
            return self.online
        elif mode == 'offline':
            return self.offline
        return self.current
    
    def is_authenticated(self, mode=None):
        """检查指定模式是否已认证"""
        user = self.get_user(mode)
        return user.is_authenticated()
    
    def clear(self, mode=None):
        """清除指定模式的认证信息"""
        if mode == 'online':
            self.online.clear()
        elif mode == 'offline':
            self.offline.clear()
        else:
            self.current.clear()
    
    def clear_all(self):
        """清除所有认证信息"""
        self.online.clear()
        self.offline.clear()
    
    def save(self, filepath):
        """保存认证信息到文件"""
        import json
        filepath = os.path.join(filepath, "auth_credentials.json")
        if not os.path.exists(os.path.dirname(filepath)):
            os.makedirs(os.path.dirname(filepath))

        try:
            # 获取正版过期时间
            if self.online.token:
                self.decoder.token = self.online.token
                expiration = self.decoder.get_expiration()
                if expiration:
                    logger.info(f"Token 过期时间戳: {expiration['timestamp']}")
                    logger.info(f"Token 过期时间: {expiration['formatted']}")
                
                # 检查是否已过期
                if self.decoder.is_expired() and expiration is not None:
                    logger.info("⚠️  Token 已过期")
                    self.online.clear()
                    return False

            credentials = {
                "online": {
                    "uuid": self.online.uuid,
                    "username": self.online.username,
                    "token": self.online.token,
                    "refresh_token": self.online.refresh_token,
                    "avatar": self.online.avatar,
                    "expires_at": self.online.expires_at,
                },
                "offline": {
                    "uuid": self.offline.uuid,
                    "username": self.offline.username,
                    "avatar": self.offline.avatar
                }
            }
            
            with open(filepath, 'w') as f:
                json.dump(credentials, f, indent=2)

            return True
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.signals.failure.emit(f"保存凭据失败: {str(e)}")
            # TODO 需要添加通知
            return False
        
    def load(self, path):
        """从文件加载认证信息"""
        import os, json

        filepath = os.path.join(path, "auth_credentials.json")
        if not os.path.exists(os.path.dirname(filepath)):
            os.makedirs(os.path.dirname(filepath))

        if not os.path.isfile(filepath):
            return False
        
        self.signals.progress.emit("自动登录...")
        try:
            with open(filepath, 'r') as f:
                credentials = json.load(f)
            
            online = credentials.get('online', {})
            self.online.uuid = online.get('uuid')
            self.online.username = online.get('username')
            self.online.avatar = online.get('avatar')
            self.online.refresh_token = online.get('refresh_token')
            self.online.token = online.get('token')
            self.online.expires_at = online.get('expires_at')

            offline = credentials.get('offline', {})
            self.offline.uuid = offline.get('uuid')
            self.offline.username = offline.get('username')
            self.offline.avatar = offline.get('avatar')

            if self.online.token:
                self.decoder.token = self.online.token
                expiration = self.decoder.get_expiration()
                if expiration:
                    logger.info(f"Token 过期时间戳: {expiration['timestamp']}")
                    logger.info(f"Token 过期时间: {expiration['formatted']}")
                
                # 检查是否已过期
                if self.decoder.is_expired() and expiration is not None:
                    logger.info("⚠️  Token 已过期")
                    self.online.clear()
                    return False
            elif not (self.online.uuid and self.online.username and self.online.token):
                self.online.clear()
                self.save(path)

            if not self.offline.username or self.offline.username == '':
                self.offline.clear()
                print('self.offline.username == ""', self.offline.username)
                self.save(path)
            
            if not (self.online.uuid and self.online.username and self.online.token) or self.online.username == '':
                self.online.clear()
                self.save(path)

            if self.online.uuid and self.online.username and self.online.token:
                # 正版登录
                print('正版登录x')
                self.current_mode = "online"
                self.signals.success.emit(self.online.username, {
                    'uuid': self.online.uuid,
                    'skin': self.online.avatar,
                    'token': self.online.token,
                    'type': self.current_mode,
                    'refresh_token': self.online.refresh_token,
                    'expires_at': self.decoder.get_expiration()
                })
            elif self.offline.username:
                # 离线登录
                print('离线登录x')
                self.current_mode = "offline"
                self.signals.success.emit(self.offline.username, {
                    'uuid': self.offline.uuid,
                    'skin': self.offline.avatar,
                    'token': None,
                    'type': self.current_mode
                })

            return True
        except Exception as e:
            self.signals.failure.emit(f"加载凭据失败: {str(e)}")
            return False

    def __str__(self):
        return (f"Authenticator(current={self.current_mode}, "
                f"online_auth={self.online.is_authenticated()}, "
                f"offline_auth={self.offline.is_authenticated()})")


class MinecraftHttpServer(HTTPServer):
    
    def __init__(self, server_address, RequestHandlerClass, bind_and_activate = True):
        super().__init__(server_address, RequestHandlerClass, bind_and_activate)
        self.timeout = 500

    def serve_forever(self):
        self.stopped = False                    
        """Handle one request at a time until doomsday."""
        while not self.stopped:
            self.handle_request()

    def shutdown(self):
        self.stopped = True
        self.server_close()


class CallbackHandler(BaseHTTPRequestHandler):
    """本地服务器请求处理器"""
    def do_GET(self):
        """处理 GET 请求"""
        # 只处理指定的回调路径
        if self.path.startswith('/auth_callback'):
            # 解析URL中的查询参数
            query = urlparse(self.path).query
            params = parse_qs(query)
            code = params.get('code', [None])[0]  # 获取授权码
            error = params.get('error', [None])[0]  # 获取错误信息（如果有）
            BUGG_RESOURCE = os.environ.get('BUGG_RESOURCE')
            # 根据是否获取到授权码进行不同处理
            if code:
                # 发送HTTP 200响应给浏览器
                self.send_response(200)
                self.send_header('Content-type', 'text/html; charset=utf-8')
                self.end_headers()  # 结束头部设置
                response_content = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>正版登录成功</title>
    <style>
        /* 定义 '字魂像素积木体' 字体 */
        @font-face {{
            font-family: 'ZiHunPixelBlock'; /* 给你自定义的字体起个名字 */
            src: url('{BUGG_RESOURCE}/fonts/字魂像素积木体.ttf') format('ttf');
            /* 建议提供多种格式以兼容不同浏览器，woff2 优先 */
            font-weight: normal;
            font-style: normal;
            font-display: swap; /* 此属性可避免字体加载期间文本不可见 */
        }}

        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            font-family: 'ZiHunPixelBlock', 'Courier New', monospace;
        }}
        
        body {{
            background: linear-gradient(135deg, #1a1f2d 0%, #0d1520 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            color: #fff;
            overflow: hidden;
            position: relative;
        }}
        
        .container {{
            max-width: 800px;
            width: 90%;
            background: rgba(19, 26, 42, 0.85);
            border: 4px solid #3a3a3a;
            border-radius: 8px;
            padding: 30px;
            text-align: center;
            position: relative;
            z-index: 2;
            box-shadow: 0 0 30px rgba(0, 150, 255, 0.5);
            backdrop-filter: blur(10px);
        }}
        
        .header {{
            margin-bottom: 30px;
        }}
        
        .logo {{
            width: 120px;
            height: 120px;
            margin: 0 auto 20px;
            position: relative;
        }}
        
        .logo-inner {{
            width: 100%;
            height: 100%;
            background: linear-gradient(135deg, #5c94fc 0%, #3a75d0 100%);
            border-radius: 15px;
            display: flex;
            justify-content: center;
            align-items: center;
            transform: rotate(45deg);
            box-shadow: 0 0 20px rgba(92, 148, 252, 0.7);
        }}
        
        .logo-inner::before {{
            content: "";
            position: absolute;
            width: 80%;
            height: 80%;
            border: 3px solid #fff;
            border-radius: 8px;
            transform: rotate(-45deg);
        }}
        
        .logo-text {{
            transform: rotate(-45deg);
            color: white;
            font-size: 48px;
            font-weight: bold;
            text-shadow: 3px 3px 0 #000;
        }}
        
        h1 {{
            font-size: 42px;
            margin-bottom: 15px;
            color: #5c94fc;
            text-shadow: 3px 3px 0 #000;
            letter-spacing: 2px;
        }}
        
        .success-message {{
            font-size: 24px;
            margin-bottom: 30px;
            line-height: 1.6;
            color: #e0e0e0;
            text-shadow: 1px 1px 0 #000;
        }}
        
        .instruction {{
            background: rgba(30, 40, 60, 0.7);
            border: 3px solid #3a3a3a;
            border-radius: 8px;
            padding: 20px;
            margin: 30px 0;
            font-size: 20px;
            color: #a0c0ff;
            text-shadow: 1px 1px 0 #000;
        }}
        
        .pixel-button {{
            display: inline-block;
            background: linear-gradient(to bottom, #5c94fc, #3a75d0);
            color: white;
            font-size: 22px;
            padding: 15px 40px;
            margin: 20px 0;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            text-transform: uppercase;
            letter-spacing: 2px;
            font-weight: bold;
            text-shadow: 2px 2px 0 #000;
            box-shadow: 0 5px 0 #2a55a0, 0 8px 10px rgba(0, 0, 0, 0.5);
            transition: all 0.1s;
            position: relative;
            overflow: hidden;
        }}
        
        .pixel-button:hover {{
            background: linear-gradient(to bottom, #6ca4ff, #4a85e0);
            transform: translateY(2px);
            box-shadow: 0 3px 0 #2a55a0, 0 5px 8px rgba(0, 0, 0, 0.5);
        }}
        
        .pixel-button:active {{
            transform: translateY(5px);
            box-shadow: 0 0 0 #2a55a0, 0 2px 5px rgba(0, 0, 0, 0.5);
        }}
        
        .pixel-button::after {{
            content: "";
            position: absolute;
            top: 0;
            left: -100%;
            width: 100%;
            height: 100%;
            background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.2), transparent);
            transition: all 0.5s;
        }}
        
        .pixel-button:hover::after {{
            left: 100%;
        }}
        
        .footer {{
            margin-top: 30px;
            font-size: 16px;
            color: #7f7f7f;
            text-shadow: 1px 1px 0 #000;
        }}
        
        .disclaimer {{
            font-size: 12px;
            margin-top: 10px;
            color: #5a5a5a;
            line-height: 1.4;
        }}
        
        /* Minecraft 像素风格背景元素 */
        .pixel {{
            position: absolute;
            width: 20px;
            height: 20px;
            background: rgba(92, 148, 252, 0.2);
            z-index: 1;
        }}
        
        .pixel:nth-child(1) {{
            top: 10%;
            left: 20%;
            animation: float 12s infinite linear;
        }}
        
        .pixel:nth-child(2) {{
            top: 20%;
            right: 15%;
            animation: float 15s infinite linear reverse;
        }}
        
        .pixel:nth-child(3) {{
            bottom: 30%;
            left: 10%;
            animation: float 18s infinite linear;
        }}
        
        .pixel:nth-child(4) {{
            bottom: 15%;
            right: 20%;
            animation: float 14s infinite linear reverse;
        }}
        
        @keyframes float {{
            0% {{ transform: translate(0, 0) rotate(0deg); }}
            25% {{ transform: translate(50px, 50px) rotate(90deg); }}
            50% {{ transform: translate(100px, 0) rotate(180deg); }}
            75% {{ transform: translate(50px, -50px) rotate(270deg); }}
            100% {{ transform: translate(0, 0) rotate(360deg); }}
        }}
        
        /* 响应式设计 */
        @media (max-width: 768px) {{
            h1 {{ font-size: 32px; }}
            .success-message {{ font-size: 20px; }}
            .instruction {{ font-size: 18px; }}
            .pixel-button {{ font-size: 18px; padding: 12px 30px; }}
        }}
        
        @media (max-width: 480px) {{
            .container {{ padding: 20px; }}
            h1 {{ font-size: 28px; }}
            .success-message {{ font-size: 18px; }}
            .instruction {{ font-size: 16px; padding: 15px; }}
        }}
    </style>
</head>
<body>
    <!-- 背景像素元素 -->
    <div class="pixel"></div>
    <div class="pixel"></div>
    <div class="pixel"></div>
    <div class="pixel"></div>
    
    <div class="container">
        <div class="header">
            <div class="logo">
                <div class="logo-inner">
                    <div class="logo-text">MC</div>
                </div>
            </div>
            <h1>正版登录成功！</h1>
        </div>
        
        <div class="success-message">
            您的 Minecraft 正版账号已成功验证并登录
        </div>
        
        <div class="instruction">
            您现在可以安全地关闭此窗口并返回启动器<br>
            愉快的游戏之旅即将开始！
        </div>
        
        <button class="pixel-button" onclick="closeWindow()">关闭窗口</button>
        
        <div class="footer">
            BuggCraft 启动器 © 2024
        </div>
        <div class="disclaimer">
            本软件为开源项目，与任何游戏公司无隶属关系<br>
            玩家需自行确保拥有正版游戏授权
        </div>
    </div>
    
    <script>
        function closeWindow() {{
            try {{
                // 尝试关闭窗口
                if (window.opener) {{
                    // 如果窗口是由另一个窗口打开的，可以尝试关闭
                    window.close();
                }} else {{
                    // 否则，尝试使用更可靠的方法
                    window.open('', '_self', '').close();
                }}
            }} catch (e) {{
                // 如果关闭失败，显示提示信息
                const closeStatus = document.getElementById('closeStatus');
                closeStatus.style.display = 'block';
                closeStatus.innerHTML = `
                    无法自动关闭窗口<br>
                    请手动关闭此窗口返回启动器
                `;
                
                // 更改按钮状态
                const closeButton = document.querySelector('.pixel-button');
                closeButton.textContent = '请手动关闭';
                closeButton.style.background = '#ff5555';
                closeButton.onclick = null;
            }}
        }}
        
        // 添加像素风格背景动画
        document.addEventListener('DOMContentLoaded', function() {{
            const container = document.querySelector('.container');
            for (let i = 0; i < 20; i++) {{
                const pixel = document.createElement('div');
                pixel.classList.add('pixel');
                pixel.style.left = Math.random() * 100 + '%';
                pixel.style.top = Math.random() * 100 + '%';
                pixel.style.width = Math.random() * 20 + 10 + 'px';
                pixel.style.height = pixel.style.width;
                pixel.style.animationDuration = (Math.random() * 10 + 10) + 's';
                pixel.style.animationDelay = Math.random() * 5 + 's';
                pixel.style.opacity = Math.random() * 0.3 + 0.1;
                document.body.appendChild(pixel);
            }}
        }});
    </script>
</body>
</html>
                """
                self.wfile.write(response_content.encode('utf-8'))  # 关键修改：添加 .encode('utf-8')
                # 将授权码设置到服务器对象中，以便主线程获取
                self.server.auth_code = code
                # 安排服务器在短时间内关闭
                self.server.shutdown()
            elif error:
                # 处理错误情况
                error_description = params.get('error_description', ['未知错误'])[0]
                logger.info(f'error_description {error_description}')
                self.send_error(500, f"OAuth Error: {error}", error_description)
                self.server.auth_error = f"{error}: {error_description}"
                self.server.shutdown()
            else:
                self.send_error(404, "Not Found", "未找到指定的回调参数")
        else:
            self.send_error(404, "Not Found", "页面未找到")

    def log_message(self, format, *args):
        """禁用默认日志输出，保持控制台整洁"""
        return


class AsyncAuthServer(QObject):
    """异步认证服务器"""
    code_received = Signal(str)  # 授权码信号
    error_occurred = Signal(str)  # 错误信号
    signal_timeout = Signal()  # 超时信号
    
    def __init__(self, port=47952, timeout=300):
        super().__init__()
        self.port = port
        self.timeout = timeout
        self.server = None
        self.server_thread = None
        self.auth_code = None
        self.auth_error = None
        self.timer = QTimer()
        self.timer.timeout.connect(self.check_timeout)
        self.shutdown_timeout = 5  # 服务器关闭超时时间(秒)
        
    def start(self):
        """启动服务器"""
        try:
            self.server = MinecraftHttpServer(('localhost', self.port), CallbackHandler)
            self.server.auth_code = None
            self.server.auth_error = None
            
            # 启动服务器线程
            self.server_thread = threading.Thread(target=self.server.serve_forever)
            self.server_thread.daemon = True
            self.server_thread.start()
            
            # 启动超时计时器
            self.start_time = time.time()
            self.timer.start(100)  # 每100毫秒检查一次
            
            return True
        except Exception as e:
            self.error_occurred.emit(f"启动服务器失败: {str(e)}")
            return False
    
    def check_timeout(self):
        """检查是否超时"""
        if self.auth_code or self.auth_error:
            logger.info('检查是否超时1')
            self.timer.stop()
            return
            
        if time.time() - self.start_time > self.timeout:
            logger.info('检查是否超时2')
            self.timer.stop()
            self.timeout.emit()
            
        # 检查服务器状态
        if self.server:
            if self.server.auth_code:
                self.auth_code = self.server.auth_code
                self.code_received.emit(self.auth_code)
                self.stop()
            elif self.server.auth_error:
                self.auth_error = self.server.auth_error
                self.error_occurred.emit(self.auth_error)
                self.stop()
        
    def stop(self):
        """停止服务器 - 最终版"""
        self.timer.stop()
        if self.server:
            try:
                self.server.shutdown()
                logger.info('服务器关闭完成')
            except Exception as e:
                traceback.print_exc()
                logger.info(f'服务器关闭异常: {e}')
        
        # 清理线程
        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(timeout=1.0)


class MicrosoftAuthenticator(QObject):
    """Microsoft 正版登录认证类"""
    
    def __init__(self, parent=None, skins_cache_path=None):
        super().__init__(parent)
        self.oauth_thread = None
        self.decoder = JWTDecoder()  # 创建解码器实例
        self.signals = MicrosoftAuthSignals()
        self.auth_server = AsyncAuthServer()

        self.skins_cache_path = skins_cache_path  # 头像save
        self.signl_cancel = False  # 认证状态，表示是否取消认证

        # OAuth 认证参数
        # self.client_id = "00000000402b5328"
        self.client_id = "9372e575-a673-4100-bed9-b5d2e4023d30"
        self.client_secret = ""
        self.scope = "XboxLive.signin offline_access"
        self.redirect_uri = "http://localhost:47952/auth_callback"
        self.authorization_url = (
            f"https://login.live.com/oauth20_authorize.srf?"
            f"client_id={self.client_id}&"
            f"client_secret={self.client_secret}&"
            f"response_type=code&"
            f"redirect_uri={self.redirect_uri}&"
            f"scope={self.scope}"
        )
        
        # 状态变量
        self.authorization_code = None
        self.microsoft_token = None
        self.refresh_token = None
        self.user_hash = None
        self.xbox_token = None
        self.xsts_token = None
        
        self.minecraft_uuid = None
        self.minecraft_username = None
        self.minecraft_token = None
        self.minecraft_skin = None
        self.minecraft_login_type = "offline"
        

    def start_login(self):
        """启动登录流程（使用系统浏览器和本地服务器）"""
        # 创建异步服务器
        self.signl_cancel = False
        
        self.auth_server.code_received.connect(self.handle_auth_code)
        self.auth_server.error_occurred.connect(self.signals.failure)
        self.auth_server.signal_timeout.connect(lambda: self.signals.failure.emit("登录超时，请重试"))
        
        if self.auth_server.start():
            # 打开浏览器
            self.signals.progress.emit("[0/9] 正在调起认证...")
            webbrowser.open(self.authorization_url)
            self.signals.progress.emit("[1/9] 请在完成登录...")
        else:
            self.signals.failure.emit("无法启动服务器")
    
    def handle_auth_code(self, auth_code):
        """处理接收到的授权码"""
        if self.signl_cancel: return  # 用户取消了认证
        self.authorization_code = auth_code
        self.signals.progress.emit("[2/9] 交换令牌...")

        # 启动服务器线程
        self.oauth_thread = threading.Thread(target=self.get_oauth20_token)
        self.oauth_thread.daemon = True
        self.oauth_thread.start()
        
    def get_oauth20_token(self):
        """使用授权码获取Microsoft访问令牌"""
        if self.signl_cancel: return  # 用户取消了认证
        try:
            url = "https://login.live.com/oauth20_token.srf"
            data = {
                'client_id': self.client_id,
                'client_secret': self.client_secret,
                'code': self.authorization_code,
                'grant_type': 'authorization_code',
                'redirect_uri': self.redirect_uri,
            }

            self.signals.progress.emit("[3/9] 获取令牌...")
            status_code, response_data = minecraft_httpx.post(url, data)
            
            if status_code == 200:
                self.oauth20_token = response_data.get('access_token')
                self.refresh_token = response_data.get('refresh_token')
                
                if self.oauth20_token:
                    self.get_xbox_live_token()
                else:
                    self.signals.failure.emit("Microsoft令牌响应中缺少访问令牌")
            else:
                logger.info(f"get_oauth20_token 获取Microsoft令牌失败: HTTP {status_code}\n{response_data}")
                self.signals.failure.emit(f"获取Microsoft令牌失败: HTTP {status_code}\n{response_data}")
        except Exception as e:
            self.signals.failure.emit(f"获取Microsoft令牌时发生异常: {str(e)}")
    
    def get_xbox_live_token(self):
        """获取Xbox Live令牌"""
        if self.signl_cancel: return  # 用户取消了认证
        try:
            url = "https://user.auth.xboxlive.com/user/authenticate"
            headers = {
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            }
            data = {
                "Properties": {
                    "AuthMethod": "RPS",
                    "SiteName": "user.auth.xboxlive.com",
                    "RpsTicket": f"d={self.oauth20_token}"
                },
                "RelyingParty": "http://auth.xboxlive.com",
                "TokenType": "JWT"
            }
            
            self.signals.progress.emit("[4/9] 获取令牌...")
            status_code, response_data = minecraft_httpx.post(url, data, headers=headers)
            
            if status_code == 200:
                self.xbox_token = response_data.get('Token')
                self.user_hash = response_data.get('DisplayClaims', {}).get('xui', [{}])[0].get('uhs')
                
                if self.xbox_token and self.user_hash:
                    self.get_xsts_token()
                else:
                    self.signals.failure.emit("Xbox Live令牌响应中缺少必要字段")
            else:
                self.signals.failure.emit(f"获取Xbox Live令牌失败: HTTP {status_code}\n{response_data}")
        except Exception as e:
            self.signals.failure.emit(f"获取Xbox Live令牌时发生异常: {str(e)}")
    
    def get_xsts_token(self):
        """获取XSTS令牌"""
        if self.signl_cancel: return  # 用户取消了认证
        try:
            url = "https://xsts.auth.xboxlive.com/xsts/authorize"
            headers = {
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            }
            data = {
                "Properties": {
                    "SandboxId": "RETAIL",
                    "UserTokens": [self.xbox_token]
                },
                "RelyingParty": "rp://api.minecraftservices.com/",
                "TokenType": "JWT"
            }
            
            self.signals.progress.emit("[5/9] 获取令牌...")
            status_code, response_data = minecraft_httpx.post(url, data, headers=headers)
            
            if status_code == 200:
                self.xsts_token = response_data.get('Token')
                
                if self.xsts_token:
                    self.get_minecraft_token()
                else:
                    self.signals.failure.emit("XSTS令牌响应中缺少令牌")
            else:
                self.signals.failure.emit(f"获取XSTS令牌失败: HTTP {status_code}\n{response_data}")
        except Exception as e:
            self.signals.failure.emit(f"获取XSTS令牌时发生异常: {str(e)}")
    
    def get_minecraft_token(self):
        """获取Minecraft访问令牌"""
        if self.signl_cancel: return  # 用户取消了认证
        try:
            url = "https://api.minecraftservices.com/authentication/login_with_xbox"
            headers = {
                'Content-Type': 'application/json'
            }
            data = {
                "identityToken": f"XBL3.0 x={self.user_hash};{self.xsts_token}"
            }
            
            self.signals.progress.emit("[6/9] 获取Minecraft令牌...")
            status_code, response_data = minecraft_httpx.post(url, data, headers=headers)
            
            if status_code == 200:
                self.minecraft_token = response_data.get('access_token')
                if self.minecraft_token:
                    if not self.get_minecraft_mcstore():
                        return
                    
                    self.get_minecraft_profile()
                else:
                    self.signals.failure.emit("缺少访问令牌")
            else:
                self.signals.failure.emit(f"网络可能异常，获取Minecraft令牌失败 STATUS: {status_code}\n{response_data}")
        except Exception as e:
            self.signals.failure.emit(f"获取Minecraft令牌时发生异常: {str(e)}")
    
    def get_minecraft_profile(self):
        """获取Minecraft玩家档案"""
        if self.signl_cancel: return  # 用户取消了认证
        try:
            url = "https://api.minecraftservices.com/minecraft/profile"
            headers = {
                'Authorization': f'Bearer {self.minecraft_token}',
                'Content-Type': 'application/json'
            }
            
            self.signals.progress.emit("[8/9] 获取玩家档案...")
            status_code, response_data = minecraft_httpx.get(url, headers=headers)
            
            if status_code == 404:
                self.signals.failure.emit("玩家档案未建立，请先使用官方Minecraft启动器创建游戏名称​​")
                return
            
            if status_code == 200:
                print('response_data', response_data)
                self.minecraft_username = response_data.get('name')
                self.minecraft_uuid = response_data.get('id')
                minecraft_skins = response_data.get('skins', [])
                if minecraft_skins and self.skins_cache_path:
                    self.signals.progress.emit("[9/9] 获取玩家头像...")
                    self.minecraft_skin = process_skin_info(uuid=self.minecraft_uuid, skin_info=minecraft_skins[0], output_dir=self.skins_cache_path)
                
                if self.minecraft_username and self.minecraft_uuid:
                    self.auth_server.stop()
                    self.minecraft_login_type = "online"
                    self.decoder.token = self.minecraft_token
                    self.signals.success.emit(self.minecraft_username, {
                        'uuid': self.minecraft_uuid,
                        'skin': self.minecraft_skin,
                        'token': self.minecraft_token,
                        'type': self.minecraft_login_type,
                        'refresh_token': self.refresh_token,
                        'expires_at': self.decoder.get_expiration()
                    })
                else:
                    self.signals.failure.emit("玩家档案响应中缺少用户名或UUID")
            else:
                self.signals.failure.emit(f"获取玩家档案失败: HTTP {status_code}\n{response_data}")
        except Exception as e:
            traceback.print_exc()
            self.signals.failure.emit(f"获取玩家档案时发生异常: {str(e)}")
    
    def get_minecraft_mcstore(self):
        """检查游戏拥有情况
        使用Minecraft的访问令牌来检查该账号是否包含产品许可。"""
        if self.signl_cancel: return  # 用户取消了认证
        headers = {
            'Authorization': f'Bearer {self.minecraft_token}',
            'Content-Type': 'application/json'
        }
        try:
            self.signals.progress.emit("[7/9] 查询正版许可...")
            status_code, response_data = minecraft_httpx.get('https://api.minecraftservices.com/entitlements/mcstore', headers=headers)
            
            if status_code == 200:
                minecraft_signature = []
                for i in response_data['items']:
                    name = i.get('name', None)
                    if not name in ['game_minecraft', 'product_minecraft']:
                        continue
                    minecraft_signature.append(name)
                
                if 'game_minecraft' in minecraft_signature and 'product_minecraft' in minecraft_signature:
                    return True
                
                self.minecraft_login_type = "offline"
                self.signals.failure.emit("未购买正版")
            else:
                self.signals.failure.emit(f"网络可能异常，获取产品许可失败 STATUS: {status_code}")
        except Exception as e:
            self.signals.failure.emit(f"获取产品许可时发生异常: {str(e)}")

        return False

    def save_credentials(self, filepath):
        """保存认证信息到文件"""
        import os, shutil
        filepath = os.path.join(filepath, "auth_credentials.json")
        if not os.path.exists(os.path.dirname(filepath)):
            os.makedirs(os.path.dirname(filepath))

        try:
            # 获取过期时间
            self.decoder.token = self.minecraft_token
            expiration = self.decoder.get_expiration()
            if expiration and self.minecraft_token:
                # self.signals.progress.emit(f"Token 过期时间: {expiration['timestamp']}")
                logger.info(f"Token 过期时间戳: {expiration['timestamp']}")
                logger.info(f"Token 过期时间: {expiration['formatted']}")
            
            # 检查是否已过期
            if self.decoder.is_expired() and expiration is not None:
                logger.info("⚠️  Token 已过期")
                if os.path.isfile(filepath):
                    os.remove(filepath)
                self.signals.failure.emit(f"Token 已过期")
                return False

            credentials = {
                "minecraft_uuid": self.minecraft_uuid,
                "minecraft_username": self.minecraft_username,
                "refresh_token": self.refresh_token,
                "minecraft_token": self.minecraft_token,
                "minecraft_skin": self.minecraft_skin
            }
            
            with open(filepath, 'w') as f:
                json.dump(credentials, f)

            return True
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.signals.failure.emit(f"保存凭据失败: {str(e)}")
            return False
    
    def load_credentials(self, filepath):
        """从文件加载认证信息"""
        import os, shutil

        filepath = os.path.join(filepath, "auth_credentials.json")
        if not os.path.exists(os.path.dirname(filepath)):
            os.makedirs(os.path.dirname(filepath))

        if not os.path.isfile(filepath):
            return False
        
        self.signals.progress.emit("自动登录...")
        try:
            with open(filepath, 'r') as f:
                credentials = json.load(f)
            
            self.decoder.token = credentials.get('minecraft_token')
            expiration = self.decoder.get_expiration()
            if expiration:
                logger.info(f"Token 过期时间戳: {expiration['timestamp']}")
                logger.info(f"Token 过期时间: {expiration['formatted']}")
            
            # 检查是否已过期
            if self.decoder.is_expired() and expiration is not None:
                logger.info("⚠️  Token 已过期")
                if os.path.isfile(filepath):
                    os.remove(filepath)
                
                self.signals.failure.emit(f"Token 已过期")
                return False

            self.refresh_token = credentials.get('refresh_token')
            self.minecraft_username = credentials.get('minecraft_username')
            self.minecraft_uuid = credentials.get('minecraft_uuid')
            self.minecraft_skin = credentials.get('minecraft_skin')
            self.minecraft_token = credentials.get('minecraft_token')
            if self.minecraft_username and self.minecraft_uuid and self.minecraft_token:
                # 正版登录
                self.minecraft_login_type = "online"
                self.signals.success.emit(self.minecraft_username, {
                    'uuid': self.minecraft_uuid,
                    'skin': self.minecraft_skin,
                    'token': self.minecraft_token,
                    'type': self.minecraft_login_type
                })
            elif self.minecraft_username and not self.minecraft_token:
                # 离线登录
                self.minecraft_login_type = "offline"
                self.signals.success.emit(self.minecraft_username, {
                    'uuid': self.minecraft_uuid,
                    'skin': self.minecraft_skin,
                    'token': None,
                    'type': self.minecraft_login_type
                })

            return True
        except Exception as e:
            self.signals.failure.emit(f"加载凭据失败: {str(e)}")
            return False
    
    def is_authenticated(self):
        """检查是否已认证"""
        return bool(self.minecraft_token and self.minecraft_username and self.minecraft_uuid)
    
    def clear(self, filepath=None):
        """清空认证信息"""
        import os
        
        self.authorization_code = None
        self.microsoft_token = None
        self.refresh_token = None
        self.user_hash = None
        self.xbox_token = None
        self.xsts_token = None
        self.minecraft_token = None
        self.minecraft_username = None
        self.minecraft_uuid = None
        self.minecraft_skin = None

        filepath = os.path.join(filepath, "auth_credentials.json")
        if os.path.isfile(filepath):
            os.remove(filepath)

    def cancel_authentication(self):
        """用户取消认证"""
        self.signl_cancel = True
        if self.auth_server:
            self.auth_server.stop()

# 使用示例
if __name__ == "__main__":
    # 你的 JWT Token
    jwt_token = "..xkkXt7GSR----"
    
    # 创建解码器实例
    decoder = JWTDecoder(jwt_token)
    
    # 获取过期时间
    expiration = decoder.get_expiration()
    if expiration:
        logger.info(f"Token 过期时间戳: {expiration['timestamp']}")
        logger.info(f"Token 过期时间: {expiration['formatted']}")
        
        # 检查是否已过期
        if decoder.is_expired():
            logger.info("⚠️  Token 已过期")
        else:
            logger.info("✅  Token 仍然有效")
    
    # 获取签发时间
    issued_at = decoder.get_issued_at()
    if issued_at:
        logger.info(f"Token 签发时间: {issued_at['formatted']}")
    
    # 获取所有声明
    claims = decoder.get_all_claims()
    if claims:
        logger.info("\nToken 中的所有声明:")
        for key, value in claims.items():
            logger.info(f"  {key}: {value}")


# if __name__ == "__main__":
#     headers = {
#         'Authorization': f'Bearer eyJraWQiOiIwNDkxODEiLCJhbGciOiJSUzI1NiJ9.eyJ4dWlkIjoiMjUzNTQ0NDgzNjA5NzgwNyIsImFnZyI6IkFkdWx0Iiwic3ViIjoiM2M2NmYzZjctMjZmMC01MjQxLWIwNTgtZDdlMGMzY2FjYTczIiwiYXV0aCI6IlhCT1giLCJucyI6ImRlZmF1bHQiLCJyb2xlcyI6W10sImlzcyI6ImF1dGhlbnRpY2F0aW9uIiwiZmxhZ3MiOlsib3JkZXJzXzIwMjIiLCJtdWx0aXBsYXllciIsInR3b2ZhY3RvcmF1dGgiLCJtc2FtaWdyYXRpb25fc3RhZ2U0Il0sInByb2ZpbGVzIjp7Im1jIjoiYmVhMDU5MmYtZTBiNC00MjkzLTlmMWYtYjYxM2FmZWQ1ZDBlIn0sInBsYXRmb3JtIjoiUENfTEFVTkNIRVIiLCJwZmQiOlt7InR5cGUiOiJtYyIsImlkIjoiYmVhMDU5MmYtZTBiNC00MjkzLTlmMWYtYjYxM2FmZWQ1ZDBlIiwibmFtZSI6Ikp1bnNpenoifV0sIm5iZiI6MTc1NjkxMzE2MywiZXhwIjoxNzU2OTk5NTYzLCJpYXQiOjE3NTY5MTMxNjN9.xkkXt7GSR-5zPmb6tnijzYDElnOt0fhHzmZ3Vd_gEc6LWvvMZmP01GArfnBQegMx-rRKUj4vrCVVCaUT87PIJ7gCLGlIzwXrpcLkgDBFui7Bk4n_YMhPw2WJeMusMXuzGXbvOF2BREe-ZUr8KNHJBMzkKyoPNe0HTkjj4bTCNDttqYe6Ok0SQNYnze-wXN1pspx1WHKbWNt6stAIemw84hdjcNSiOiHqxdaXe2hmXM9GUOV8PmiPdoZPyF3w9B1oIlongSsHxiewec26TjswW_R8vjyAb5fAFH_dq1HdIOYqvIRY3rQPjZ0OepOndcMGdze_h6I9qGg1KXam5qca2Q',
#         'Content-Type': 'application/json'
#     }
#     response = requests.get('https://api.minecraftservices.com/entitlements/mcstore', headers=headers)
#     if response.status_code == 200:
#         data = response.json()
#         minecraft_signature = []
#         for i in data['items']:
#             name = i.get('name', None)
#             if not name in ['game_minecraft', 'product_minecraft']:
#                 continue
#             minecraft_signature.append(name)
        
#         if 'game_minecraft' in minecraft_signature and 'product_minecraft' in minecraft_signature:
#             logger.info('YES')

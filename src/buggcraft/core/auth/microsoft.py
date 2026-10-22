import os
import time
import json
import logging
import secrets
from PySide6.QtCore import Signal, QObject



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
        self.decoded = False
        self.header = self.payload = self.signature = None
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
        expiration = JWTDecoder(self.token).get_expiration()
        return bool(expiration and time.time() + 60 < expiration['timestamp'])

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
                
                # 游戏令牌过期时仍保留刷新令牌，供下次恢复登录。

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
            
            temporary = filepath + '.' + secrets.token_hex(8) + '.tmp'
            try:
                with open(temporary, 'x', encoding='utf-8') as f:
                    json.dump(credentials, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(temporary, filepath)
            finally:
                if os.path.exists(temporary):
                    os.remove(temporary)

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

            if self.online.refresh_token and not self.online.token:
                self.current_mode = 'online'
                self.refresh_login()
                return True

            if self.online.token:
                self.decoder.token = self.online.token
                expiration = self.decoder.get_expiration()
                if expiration:
                    logger.info(f"Token 过期时间戳: {expiration['timestamp']}")
                    logger.info(f"Token 过期时间: {expiration['formatted']}")
                
                # 检查是否已过期
                if not expiration or time.time() + 60 >= expiration['timestamp']:
                    logger.info("⚠️  Token 已过期")
                    if self.online.refresh_token:
                        self.current_mode = 'online'
                        self.signals.progress.emit('正在恢复正版登录…')
                        self.refresh_login()
                        return True
                    self.signals.failure.emit('正版登录已过期，请重新登录。')
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

    def refresh_login(self):
        if not self.online.refresh_token:
            self.signals.failure.emit('正版登录已过期，请重新登录。')
            return
        if not hasattr(self, '_refresh_auth'):
            self._refresh_auth = MicrosoftAuthenticator()
            self._refresh_auth.signals.success.connect(self._accept_refreshed_login)
            self._refresh_auth.signals.failure.connect(self.signals.failure)
            self._refresh_auth.signals.progress.connect(self.signals.progress)
        if not self._refresh_auth.busy:
            self._refresh_auth.refresh_login(self.online.refresh_token)

    def _accept_refreshed_login(self, username, data):
        self.online.username = username
        self.online.uuid = data['uuid']
        self.online.token = data['token']
        self.online.refresh_token = data['refresh_token']
        self.online.expires_at = data['expires_at']
        self.online.avatar = data.get('skin') or self.online.avatar
        self.current_mode = 'online'
        self.signals.success.emit(username, data)

    def cancel_refresh(self):
        if hasattr(self, '_refresh_auth'):
            self._refresh_auth.cancel_authentication()


# Public-client implementation shared by the login dialog and token refresh.
from core.auth.microsoft_oauth import (
    MicrosoftAuthenticator, AsyncAuthServer, MinecraftHttpServer, CallbackHandler,
)

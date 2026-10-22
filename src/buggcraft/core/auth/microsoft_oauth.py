"""Microsoft public-client sign-in; no application secret belongs in a launcher."""
import base64
import hashlib
import json
import logging
import os
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from core.skin import process_skin_info
from utils.network import minecraft_httpx

logger = logging.getLogger(__name__)
AUTHORITY = 'https://login.microsoftonline.com/consumers/oauth2/v2.0/'
DEFAULT_CLIENT_ID = '9372e575-a673-4100-bed9-b5d2e4023d30'


class AuthSignals(QObject):
    success = Signal(str, dict)
    failure = Signal(str)
    progress = Signal(str)
    device_code = Signal(str, str)


class LoginError(Exception):
    def __init__(self, message, *, status=None, code=None):
        super().__init__(message)
        self.status, self.code = status, code


class LoginCancelled(Exception):
    pass


def expiration(token):
    try:
        payload = token.split('.')[1]
        timestamp = int(json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))['exp'])
        return {'timestamp': timestamp, 'formatted': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(timestamp))}
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):
        return None


class MinecraftHttpServer(HTTPServer):
    allow_reuse_address = True


class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        if parsed.path != '/auth_callback':
            self.send_error(404)
            return
        if not secrets.compare_digest(params.get('state', [''])[0], self.server.expected_state):
            self.send_error(400, 'Invalid sign-in state')
            return
        code, error = params.get('code', [''])[0], params.get('error', [''])[0]
        if not code and not error:
            self.send_error(400, 'Missing authorization response')
            return
        if self.server.auth_code or self.server.auth_error:
            self.send_error(409, 'Authorization response already received')
            return
        self.server.auth_code = code or None
        # Do not echo query parameters, tokens or error descriptions into HTML or logs.
        self.server.auth_error = '微软授权已取消，请重新登录。' if error else None
        body = ('<!doctype html><meta charset="utf-8"><title>BuggCraft 登录</title>'
                '<body style="background:#272937;color:#eee;font:16px sans-serif;padding:48px">'
                '<h2>BuggCraft</h2><p>已收到微软授权结果，请返回启动器查看 Minecraft 身份验证结果。</p></body>').encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


class AsyncAuthServer(QObject):
    code_received = Signal(str)
    error_occurred = Signal(str)
    signal_timeout = Signal()

    def __init__(self, port=47952, timeout=300):
        super().__init__()
        self.port, self.timeout = port, timeout
        self.server = self.server_thread = None
        self.auth_code = self.auth_error = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check_timeout)

    def start(self, state=None):
        self.stop()
        self.auth_code = self.auth_error = None
        try:
            self.server = MinecraftHttpServer(('127.0.0.1', self.port), CallbackHandler)
            self.server.expected_state = state or secrets.token_urlsafe(32)
            self.server.auth_code = self.server.auth_error = None
            self.port = self.server.server_port
            self.server_thread = threading.Thread(target=self.server.serve_forever,
                                                  kwargs={'poll_interval': .05}, daemon=True)
            self.server_thread.start()
            self.start_time = time.monotonic()
            self.timer.start(100)
            return True
        except OSError:
            self.server = None
            self.error_occurred.emit('本地登录回调端口被占用，请使用微软设备登录。')
            return False

    def check_timeout(self):
        if not self.server:
            return
        if self.server.auth_code:
            self.auth_code = self.server.auth_code
            self.stop()
            self.code_received.emit(self.auth_code)
        elif self.server.auth_error:
            self.auth_error = self.server.auth_error
            self.stop()
            self.error_occurred.emit(self.auth_error)
        elif time.monotonic() - self.start_time >= self.timeout:
            self.stop()
            self.signal_timeout.emit()

    def stop(self):
        self.timer.stop()
        server, worker = self.server, self.server_thread
        self.server = self.server_thread = None
        if server:
            server.shutdown()
            server.server_close()
        if worker and worker is not threading.current_thread():
            worker.join(timeout=1)


class MicrosoftAuthenticator(QObject):
    """Use Microsoft's device flow on Windows/macOS/Linux, retaining browser PKCE support."""

    def __init__(self, parent=None, skins_cache_path=None):
        super().__init__(parent)
        self.signals = AuthSignals(self)
        self.skins_cache_path = skins_cache_path
        self.client_id = os.environ.get('BUGGCRAFT_MICROSOFT_CLIENT_ID', DEFAULT_CLIENT_ID)
        self.scope = 'XboxLive.signin offline_access'
        self.redirect_uri = 'http://localhost:47952/auth_callback'
        self.authorization_url = ''
        self.auth_server = AsyncAuthServer()
        self.auth_server.code_received.connect(self.handle_auth_code)
        self.auth_server.error_occurred.connect(self.signals.failure)
        self.auth_server.signal_timeout.connect(lambda: self.signals.failure.emit('登录超时，请重新登录。'))
        self.signals.device_code.connect(self._open_device_browser)
        self._cancel = threading.Event()
        self._local = threading.local()
        self._attempt = 0
        self._code_received = False
        self.oauth_thread = None
        self.signl_cancel = False
        self.authorization_code = self.oauth20_token = self.refresh_token = None
        self.user_hash = self.xbox_token = self.xsts_token = None
        self.minecraft_uuid = self.minecraft_username = self.minecraft_token = self.minecraft_skin = None
        self.minecraft_login_type = 'offline'
        self._token_endpoint = AUTHORITY + 'token'

    @property
    def busy(self):
        return bool(self.oauth_thread and self.oauth_thread.is_alive() and not self._cancel.is_set())

    def _new_attempt(self):
        self.cancel_authentication()
        self._attempt += 1
        self.signl_cancel = False
        self._cancel = threading.Event()
        self._code_received = False
        return self._attempt, self._cancel

    def _check_cancelled(self):
        attempt = getattr(self._local, 'attempt', self._attempt)
        if attempt != self._attempt or self._cancel.is_set():
            raise LoginCancelled()

    def _spawn(self, task):
        attempt = self._attempt
        def run():
            self._local.attempt = attempt
            try:
                task()
            except LoginCancelled:
                pass
            except LoginError as exc:
                self.signals.failure.emit(str(exc))
            except Exception as exc:
                # Exception strings may contain request data; log only their type.
                logger.warning('Microsoft sign-in failed: %s', type(exc).__name__)
                self.signals.failure.emit('登录服务连接失败，请检查网络后重新登录。')
        self.oauth_thread = threading.Thread(target=run, daemon=True, name='MicrosoftSignIn')
        self.oauth_thread.start()

    @staticmethod
    def _error(stage, status, data):
        error = data.get('error', '') if isinstance(data, dict) else ''
        xerr = data.get('XErr') if isinstance(data, dict) else None
        if error == 'invalid_client':
            return LoginError('微软应用配置不正确（invalid_client）。请使用设备登录；应用需启用公共客户端，桌面程序不应携带客户端密钥。')
        if error in ('invalid_grant', 'expired_token'):
            return LoginError('微软授权已失效或已被使用，请重新登录。', status=status, code=error)
        if error in ('authorization_declined', 'access_denied'):
            return LoginError('微软授权已取消，请重新登录。')
        if xerr == 2148916233:
            return LoginError('此微软账号尚未建立 Xbox 档案，请先在 xbox.com 创建玩家代号后重试。')
        if xerr in (2148916236, 2148916237, 2148916238):
            return LoginError('Xbox 账号的年龄、地区或家庭权限限制了登录，请在 Xbox 账号设置中检查。')
        if status is None:
            return LoginError('无法连接微软或 Minecraft 登录服务，请检查网络后重试。')
        return LoginError(f'{stage}失败（HTTP {status}），请稍后重试。', status=status, code=error)

    def _request(self, method, url, data=None, stage='登录'):
        self._check_cancelled()
        if method == 'GET':
            status, result = minecraft_httpx.get(url, headers={'Authorization': f'Bearer {self.minecraft_token}'})
        else:
            headers = {'Content-Type': 'application/x-www-form-urlencoded' if 'oauth' in url else 'application/json'}
            status, result = minecraft_httpx.post(url, data, headers=headers)
        self._check_cancelled()
        if status != 200 or not isinstance(result, dict):
            raise self._error(stage, status, result)
        return result

    def start_login(self):
        self._new_attempt()
        self._token_endpoint = AUTHORITY + 'token'
        self.signals.progress.emit('正在连接微软登录服务…')
        self._spawn(self._device_login)

    def _device_login(self):
        data = self._request('POST', AUTHORITY + 'devicecode',
                             {'client_id': self.client_id, 'scope': self.scope}, '获取微软登录码')
        code, uri = data.get('user_code'), data.get('verification_uri')
        if not code or not data.get('device_code') or not uri:
            raise LoginError('微软未返回完整的设备登录信息，请重试。')
        parsed = urlparse(uri)
        if parsed.scheme != 'https' or parsed.hostname not in ('microsoft.com', 'www.microsoft.com', 'login.microsoftonline.com'):
            raise LoginError('微软返回的登录地址无效，请重试。')
        self.signals.device_code.emit(code, uri)
        deadline = time.monotonic() + min(max(float(data.get('expires_in', 900)), 1), 1800)
        interval = max(float(data.get('interval', 5)), 1)
        while time.monotonic() < deadline:
            if self._cancel.wait(interval):
                raise LoginCancelled()
            self._check_cancelled()
            status, result = minecraft_httpx.post(self._token_endpoint, {
                'client_id': self.client_id, 'grant_type': 'urn:ietf:params:oauth:grant-type:device_code',
                'device_code': data['device_code'],
            }, headers={'Content-Type': 'application/x-www-form-urlencoded'})
            self._check_cancelled()
            error = result.get('error') if isinstance(result, dict) else None
            if error == 'authorization_pending':
                continue
            if error == 'slow_down':
                interval += 5
                continue
            if status != 200 or not isinstance(result, dict):
                raise self._error('微软设备授权', status, result)
            return self._accept_microsoft_token(result)
        raise LoginError('微软登录码已过期，请点击重新登录。')

    @Slot(str, str)
    def _open_device_browser(self, code, uri):
        if self._cancel.is_set():
            return
        self.signals.progress.emit(f'请在微软页面输入登录码 {code}，选择拥有 Minecraft 的账号并授权。')
        if not webbrowser.open(uri):
            self.signals.progress.emit(f'请手动打开 {uri}，输入登录码 {code}。')

    def start_browser_login(self):
        """For deployments whose app registration has a native loopback redirect."""
        self._new_attempt()
        self._token_endpoint = 'https://login.live.com/oauth20_token.srf'
        self._verifier = secrets.token_urlsafe(64)
        state = secrets.token_urlsafe(32)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(self._verifier.encode('ascii')).digest()).rstrip(b'=').decode('ascii')
        self.authorization_url = 'https://login.live.com/oauth20_authorize.srf?' + urlencode({
            'client_id': self.client_id, 'response_type': 'code', 'redirect_uri': self.redirect_uri,
            'scope': self.scope, 'state': state, 'code_challenge': challenge, 'code_challenge_method': 'S256',
        })
        if self.auth_server.start(state):
            webbrowser.open(self.authorization_url)

    def handle_auth_code(self, code):
        if self.signl_cancel or self._code_received:
            return
        self._code_received = True
        self.authorization_code = code
        self._spawn(self.get_oauth20_token)

    def get_oauth20_token(self):
        result = self._request('POST', self._token_endpoint, {
            'client_id': self.client_id, 'code': self.authorization_code, 'grant_type': 'authorization_code',
            'redirect_uri': self.redirect_uri, 'code_verifier': self._verifier,
        }, '微软授权')
        self._accept_microsoft_token(result)

    def refresh_login(self, refresh_token):
        if self.busy:
            return
        self._new_attempt()
        self.refresh_token = refresh_token
        self._spawn(self._refresh_login)

    def _refresh_login(self):
        self.signals.progress.emit('正在刷新正版登录…')
        form = {
            'client_id': self.client_id, 'grant_type': 'refresh_token',
            'refresh_token': self.refresh_token, 'scope': self.scope,
        }
        try:
            result = self._request('POST', AUTHORITY + 'token', form, '刷新微软授权')
        except LoginError as exc:
            # Upgrade caches issued by the previous login.live.com implementation.
            # Retry only an invalid grant, never network failures or account restrictions.
            if exc.code != 'invalid_grant':
                raise
            result = self._request('POST', 'https://login.live.com/oauth20_token.srf', form, '恢复旧版微软授权')
        self._accept_microsoft_token(result)

    def _accept_microsoft_token(self, result):
        self.oauth20_token = result.get('access_token')
        self.refresh_token = result.get('refresh_token') or self.refresh_token
        if not self.oauth20_token:
            raise LoginError('微软响应缺少访问令牌，请重新登录。')
        self.get_xbox_live_token()

    def get_xbox_live_token(self):
        self.signals.progress.emit('正在验证 Xbox Live 身份…')
        data = self._request('POST', 'https://user.auth.xboxlive.com/user/authenticate', {
            'Properties': {'AuthMethod': 'RPS', 'SiteName': 'user.auth.xboxlive.com', 'RpsTicket': f'd={self.oauth20_token}'},
            'RelyingParty': 'http://auth.xboxlive.com', 'TokenType': 'JWT',
        }, 'Xbox Live 身份验证')
        claims = data.get('DisplayClaims', {}).get('xui', [])
        self.xbox_token = data.get('Token')
        self.user_hash = claims[0].get('uhs') if claims else None
        if not self.xbox_token or not self.user_hash:
            raise LoginError('Xbox Live 响应缺少身份信息。')
        self.get_xsts_token()

    def get_xsts_token(self):
        self.signals.progress.emit('正在验证 Xbox 游戏权限…')
        data = self._request('POST', 'https://xsts.auth.xboxlive.com/xsts/authorize', {
            'Properties': {'SandboxId': 'RETAIL', 'UserTokens': [self.xbox_token]},
            'RelyingParty': 'rp://api.minecraftservices.com/', 'TokenType': 'JWT',
        }, 'Xbox 游戏权限验证')
        self.xsts_token = data.get('Token')
        if not self.xsts_token:
            raise LoginError('Xbox 响应缺少游戏授权。')
        self.get_minecraft_token()

    def get_minecraft_token(self):
        self.signals.progress.emit('正在登录 Minecraft…')
        data = self._request('POST', 'https://api.minecraftservices.com/authentication/login_with_xbox', {
            'identityToken': f'XBL3.0 x={self.user_hash};{self.xsts_token}',
        }, 'Minecraft 登录')
        self.minecraft_token = data.get('access_token')
        if not self.minecraft_token:
            raise LoginError('Minecraft 响应缺少访问令牌。')
        self.get_minecraft_profile()

    def get_minecraft_profile(self):
        self.signals.progress.emit('正在读取 Minecraft 正版角色…')
        try:
            data = self._request('GET', 'https://api.minecraftservices.com/minecraft/profile', stage='读取 Minecraft 角色')
        except LoginError as exc:
            if exc.status == 404:
                raise LoginError('该账号没有可用的 Java 版角色，请确认账号及 Java 版授权，并在官方启动器创建角色名称。') from None
            raise
        self.minecraft_username, self.minecraft_uuid = data.get('name'), data.get('id')
        if not self.minecraft_username or not self.minecraft_uuid:
            raise LoginError('Minecraft 响应缺少角色名称或 UUID。')
        self.minecraft_skin = None
        if data.get('skins') and self.skins_cache_path:
            try:
                self.minecraft_skin = process_skin_info(uuid=self.minecraft_uuid, skin_info=data['skins'][0], output_dir=self.skins_cache_path)
            except Exception:
                logger.info('Minecraft skin unavailable; using the default avatar')
        self._check_cancelled()
        self.minecraft_login_type = 'online'
        self.signals.success.emit(self.minecraft_username, {
            'uuid': self.minecraft_uuid, 'skin': self.minecraft_skin, 'token': self.minecraft_token,
            'type': 'online', 'refresh_token': self.refresh_token, 'expires_at': expiration(self.minecraft_token),
        })

    def is_authenticated(self):
        return bool(self.minecraft_token and self.minecraft_username and self.minecraft_uuid)

    def cancel_authentication(self):
        self.signl_cancel = True
        self._cancel.set()
        self.auth_server.stop()

    def clear(self, filepath=None):
        self.cancel_authentication()
        self.minecraft_token = self.minecraft_username = self.minecraft_uuid = self.refresh_token = None
        if filepath:
            path = os.path.join(filepath, 'auth_credentials.json')
            if os.path.isfile(path):
                os.remove(path)

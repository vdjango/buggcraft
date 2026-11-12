"""Drive two isolated production bugg.exe clients against the existing real node fixture.

Only test setup and desktop input live here. Authentication, rooms, chat, file sync,
installation and launch run in the shipped C++ services and native bridge processes.
"""
import asyncio
import base64
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


def link_tree(source, destination):
    for path in source.rglob('*'):
        if path.is_file():
            target = destination / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                os.link(path, target)
            elif not os.path.samefile(path, target):
                shutil.copy2(path, target)


def protect(payload):
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    buffer = ctypes.create_string_buffer(payload)
    incoming = Blob(len(payload), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    outgoing = Blob()
    if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(incoming), None, None, None, None, 1, ctypes.byref(outgoing)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(outgoing.data, outgoing.size)
    finally:
        ctypes.windll.kernel32.LocalFree(outgoing.data)


async def run_clients(project, fixture, ca):
    from cryptography.hazmat.primitives.asymmetric import ec
    from tests.test_web_accounts import sign, canonical, public
    build = project / 'build'
    root = build / os.environ.get('BUGG_TEST_CLIENT_ROOT', 'native-launcher-clients')
    root.mkdir(exist_ok=True)
    print('Native launcher clients: ' + str(root), flush=True)
    origin = str(fixture.clients[0].server.make_url('/')).rstrip('/')
    for index, name in enumerate(['NativeHost', 'NativeGuest']):
        destination = root / name
        destination.mkdir(exist_ok=True)
        for source in build.glob('*.dll'):
            if not (destination / source.name).exists():
                os.link(source, destination / source.name)
            elif not os.path.samefile(source, destination / source.name):
                shutil.copy2(source, destination / source.name)
        shutil.copy2(build / os.environ.get('BUGG_TEST_LAUNCHER_BINARY', 'bugg.exe'), destination / 'bugg.exe')
        for folder in ['native', 'qml', 'platforms', 'styles', 'imageformats', 'tls', 'networkinformation']:
            if (build / folder).is_dir():
                link_tree(build / folder, destination / folder)
        cache = destination / '.buggcraft'
        cache.mkdir(exist_ok=True)
        for folder in ['runtime', 'metadata']:
            if (build / '.buggcraft' / folder).is_dir():
                link_tree(build / '.buggcraft' / folder, cache / folder)
        game = destination / '.minecraft'
        game.mkdir(exist_ok=True)
        for folder in ['libraries', 'assets']:
            link_tree(build / '.minecraft' / folder, game / folder)
        version = game / 'versions/1.20.1'
        version.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cache / 'metadata/1.20.1.json', version / '1.20.1.json')
        if not (version / '1.20.1.jar').exists():
            os.link(build / '.minecraft/versions/1.20.1/1.20.1.jar', version / '1.20.1.jar')
        # A private file unavailable on public catalogs exercises the real native file channel.
        if index == 0:
            (version / 'mods').mkdir(exist_ok=True)
            (version / 'mods/private-fixture.jar').write_bytes(os.urandom(1048576))
        user = await fixture.create_user(name)
        headers, _ = await fixture.login_user(fixture.clients[0], user)
        device = ec.generate_private_key(ec.SECP256R1())
        client = fixture.clients[0]
        response = await client.post('/api/launcher/start', json={'key': public(device), 'name': name, 'remember': True})
        assert response.status == 200, await response.text()
        started = await response.json()
        response = await client.post('/api/launcher/prepare', json={'id': started['id']}, headers=headers)
        grant = (await response.json())['grant']
        response = await client.post('/api/launcher/approve', json={'id': started['id'], 'signature': sign(user[1], canonical(grant))}, headers=headers)
        assert response.status == 200, await response.text()
        message = {'p': 'buggcraft-launcher-poll-v1', 'id': started['id'], 'nonce': started['nonce']}
        response = await client.post('/api/launcher/poll', json={'id': started['id'], 'signature': sign(device, canonical(message))})
        profile = (await response.json())['profile']
        numbers = device.private_numbers()
        scalar = numbers.private_value.to_bytes(32, 'big')
        raw = numbers.public_numbers.x.to_bytes(32, 'big') + numbers.public_numbers.y.to_bytes(32, 'big') + scalar
        profile['token'] = profile['token'].split('~')[0] + '~' + base64.urlsafe_b64encode(scalar).decode().rstrip('=')
        payload = dict(key=base64.b64encode(raw).decode(), profile=profile, device=started['id'], origin=origin)
        (cache / 'node-credentials.bin').write_bytes(protect(json.dumps(payload).encode()))
        settings = {'game': {'resolution': '854x480', 'fullscreen': False},
                    'preferences': {'theme': 'small', 'afterLaunch': 'keep', 'selectedInstance': '1.20.1',
                    'identity': {'offline': [name], 'selectedId': 'offline:' + name}}}
        (cache / 'instance-settings.json').write_text(json.dumps(settings), encoding='utf-8')
    environment = os.environ.copy()
    environment['PATH'] = os.pathsep.join([str(project.parent / '.tools/Qt/6.8.1/msvc2022_64/bin'),
        str(build / 'native/bin'), environment['PATH']])
    environment['QT_QUICK_BACKEND'] = 'software'
    # Both Qt/OpenSSL and the native engine use the fixture CA; no system trust changes.
    environment['QT_SSL_BACKEND'] = 'openssl'
    environment['SSL_CERT_FILE'] = str(ca)
    async def node_heartbeats():
        while True:
            for federation in fixture.feds:
                await federation.sync_once()
            await asyncio.sleep(1)
    heartbeat = asyncio.create_task(node_heartbeats())
    try:
        process = await asyncio.create_subprocess_exec(sys.executable, '-X', 'utf8', __file__, str(root), env=environment)
        result = await asyncio.wait_for(process.wait(), 1200 if os.environ.get('BUGG_TEST_WORLD') == '1' else 600)
    finally:
        heartbeat.cancel()
        await asyncio.gather(heartbeat, return_exceptions=True)
    assert result == 0, f'Native launcher UI test failed; inspect {root}'
    print('Native launcher multi-client results: ' + str(root / 'results.json'), flush=True)


def drive(root):
    winui = root.parents[2] / '.test-tools/winui'
    sys.path[:0] = [str(winui), str(winui / 'win32'), str(winui / 'win32/lib'),
                   str(winui / 'pythonwin'), str(winui / 'pywin32_system32')]
    os.add_dll_directory(str(winui / 'pywin32_system32'))
    from pywinauto import Application, Desktop, keyboard
    import win32clipboard
    from PIL import ImageGrab
    results = []
    processes = []
    windows = []
    games = []
    old_clipboard = None
    def clipboard(text=None):
        win32clipboard.OpenClipboard()
        try:
            if text is None:
                return win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
        finally:
            win32clipboard.CloseClipboard()
    def button(window, title):
        return window.child_window(title=title, control_type='Button').wrapper_object()
    def wait_for(check, timeout=60):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                value = check()
                if value:
                    return value
            except Exception:
                pass
            time.sleep(.3)
        raise AssertionError('Timed out waiting for native launcher state')
    def capture(window, label):
        window.set_focus()
        time.sleep(.2)
        bounds = window.rectangle()
        ImageGrab.grab(bbox=(bounds.left, bounds.top, bounds.right, bounds.bottom)).save(root / (label + '.png'))
    def text(window):
        # Qt StaticText exposes its accessible name through UIA while Win32
        # window_text can remain empty for the same item.
        return '\n'.join(item.element_info.name or item.window_text() for item in window.descendants())
    def enter(window, value):
        edit = window.descendants(control_type='Edit')[-1]
        # UIA sets the real QQuick input focus; WM_CHAR then exercises its
        # textEdited path without competing with Minecraft for desktop focus.
        edit.element_info.element.SetFocus()
        edit.set_edit_text('')
        for character in value:
            if not ctypes.windll.user32.PostMessageW(window.handle, 0x0102, ord(character), 1):
                raise ctypes.WinError()
        actual = wait_for(lambda: edit.window_text() if edit.window_text() == value else None, timeout=5)
        assert actual == value, ('Desktop text entry mismatch', len(value), len(actual),
            [(i, ord(a), ord(b)) for i, (a, b) in enumerate(zip(value, actual)) if a != b])
    try:
        try:
            old_clipboard = clipboard()
        except Exception:
            pass
        for index, name in enumerate(['NativeHost', 'NativeGuest']):
            process = subprocess.Popen([str(root / name / 'bugg.exe'), '--theme', 'small', '--page', 'createRoom' if index == 0 else 'joinRoom'])
            processes.append(process)
            application = Application(backend='uia').connect(process=process.pid, timeout=30)
            window = application.window(title='Bugg')
            window.wait('visible', timeout=30)
            ctypes.windll.user32.SetWindowPos(window.handle, None, 20 + index * 820, 50, 0, 0, 0x0041)
            windows.append(window)
        host, guest = windows
        launcher_handles = {'NativeHost': host.handle, 'NativeGuest': guest.handle}
        # A running game must still be able to create its room; its instance stays locked.
        button(host, '回到首页').invoke()
        wait_for(lambda: button(host, '启动游戏').is_enabled())
        button(host, '启动游戏').invoke()
        wait_for(lambda: host.child_window(title='停止游戏', control_type='Button').exists(), timeout=180)
        button(host, '联机').invoke()
        wait_for(lambda: button(host, '创建房间').is_enabled())
        button(host, '创建房间').invoke()
        wait_for(lambda: host.child_window(title='加速缓存', control_type='CheckBox').exists())
        assert not host.child_window(control_type='ComboBox', found_index=0).is_enabled()
        wait_for(lambda: button(host, '创建房间').is_enabled())
        capture(host, 'host-create')
        # UIA Toggle changes Qt's checked property without the user toggled
        # signal. Exercise the real checkbox input and its draft binding.
        host.child_window(title='加速缓存', control_type='CheckBox').click_input()
        button(host, '创建房间').invoke()
        wait_for(lambda: button(host, '复制邀请').is_enabled())
        clipboard('')
        button(host, '复制邀请').invoke()
        invite = wait_for(lambda: clipboard() if clipboard().startswith('bugg1-') else None)
        assert invite.startswith('bugg1-')
        enter(guest, invite)
        wait_for(lambda: button(guest, '加入房间').is_enabled())
        button(guest, '加入房间').invoke()
        wait_for(lambda: guest.child_window(title='发送', control_type='Button').exists())
        capture(guest, 'guest-room')
        results.append('Two bugg.exe clients created and joined the same native room')
        results.append('Host created its room while Minecraft was already running; instance selection stayed locked')
        message = 'Native guest chat delivered to host'
        enter(guest, message)
        button(guest, '发送').invoke()
        wait_for(lambda: message in text(host))
        capture(host, 'host-chat-received')
        results.append('Guest chat appeared in host launcher')
        host.child_window(title_re='成员.*', control_type='Button').invoke()
        wait_for(lambda: 'NativeGuest' in text(host))
        capture(host, 'host-members-two')
        wait_for(lambda: button(guest, '同步安装').is_enabled())
        assert not guest.child_window(title='启动游戏', control_type='Button').exists()
        button(guest, '同步安装').invoke()
        wait_for(lambda: guest.child_window(title='复用已有配置', control_type='Button').exists())
        wait_for(lambda: button(guest, '复用已有配置').is_enabled())
        capture(guest, 'guest-config-mismatch')
        expected = hashlib.sha256((root / 'NativeHost/.minecraft/versions/1.20.1/mods/private-fixture.jar').read_bytes()).digest()
        def prepared_files():
            return [path for path in (root / 'NativeGuest/.minecraft/versions').glob('*/mods/private-fixture.jar')
                    if not path.parent.parent.name.startswith('.') and hashlib.sha256(path.read_bytes()).digest() == expected]
        button(guest, '复用已有配置').invoke()
        wait_for(lambda: '正在下载' in text(host) or '检查文件' in text(host) or 'NativeGuest，已就绪' in text(host), timeout=90)
        capture(host, 'host-member-status')
        wait_for(lambda: prepared_files() and button(guest, '启动游戏').is_enabled(), timeout=240)
        capture(guest, 'guest-sync-complete')
        actual = list((root / 'NativeGuest/.minecraft/versions').glob('*/mods/private-fixture.jar'))
        assert any(hashlib.sha256(path.read_bytes()).digest() == expected for path in actual)
        wait_for(lambda: 'NativeGuest，已就绪' in text(host) or 'NativeGuest，' in text(host) and '已就绪' in text(host))
        capture(host, 'host-members-ready')
        capture(guest, 'guest-ready')
        results.append('Real room install queue and private native file transfer completed with matching SHA-256')
        results.append('Host member list received the real guest readiness state')
        results.append('Guest start opened configuration matching; reuse prepared an independent instance without changing the original')
        assert not (root / 'NativeGuest/.minecraft/versions/1.20.1/mods/private-fixture.jar').exists()
        assert not guest.child_window(title='全新安装', control_type='Button').exists()
        # Selecting the original mismatched configuration switches the single action back to installation.
        guest.child_window(control_type='ComboBox').click_input()
        wait_for(lambda: guest.child_window(title='1.20.1，1.20.1 · Minecraft', control_type='Button').exists())
        button(guest, '1.20.1，1.20.1 · Minecraft').invoke()
        wait_for(lambda: button(guest, '同步安装').is_enabled())
        assert not guest.child_window(title='启动游戏', control_type='Button').exists()
        button(guest, '全新安装').invoke()
        wait_for(lambda: len(prepared_files()) == 2 and button(guest, '启动游戏').is_enabled(), timeout=240)
        capture(guest, 'guest-fresh-complete')
        results.append('Fresh room preparation also completed through the shared installation pipeline')
        results.append('Install and launch remained mutually exclusive through matching, preparation and reselection')
        for window in [host, guest]:
            if window.child_window(title='启动游戏', control_type='Button').exists():
                button(window, '启动游戏').invoke()
            wait_for(lambda: window.child_window(title='游戏运行中', control_type='Button').exists(), timeout=180)
        import psutil
        def launched_games():
            clients = [game for game in Desktop(backend='win32').windows(title_re='Minecraft.*', visible_only=True)
                       if psutil.Process(game.process_id()).ppid() in [process.pid for process in processes]]
            return clients if len(clients) == 2 else None
        games = wait_for(launched_games, timeout=90)
        for index, game in enumerate(games):
            capture(game, f'minecraft-client-{index}')
        results.append('Both launchers started real Minecraft windows from the shared launch pipeline')
        if os.environ.get('BUGG_TEST_WORLD') == '1':
            for window in windows:
                # Keep Qt exposed; external ShowWindow hiding leaves its input/render state stale.
                ctypes.windll.user32.SetWindowPos(window.handle, -2, 0, 0, 0, 0, 0x0013)
            host_game = next(game for game in games if psutil.Process(game.process_id()).ppid() == processes[0].pid)
            guest_game = next(game for game in games if psutil.Process(game.process_id()).ppid() == processes[1].pid)
            # Minecraft itself is operated during this optional visual acceptance step.
            # The product still owns world discovery, announcements and forwarding.
            handles = {'NativeHost': host_game.handle, 'NativeGuest': guest_game.handle}
            (root / 'game-handles.json').write_text(json.dumps(handles), encoding='utf-8')
            (root / 'launcher-handles.json').write_text(json.dumps(launcher_handles), encoding='utf-8')
            (root / 'world-test-continue').unlink(missing_ok=True)
            (root / 'world-test-ready').write_text('ready', encoding='utf-8')
            print('World test: operate the two Minecraft windows; continue after guest joins BUGG LAN entry', flush=True)
            wait_for(lambda: (root / 'world-test-continue').exists(), timeout=900)
            log = (root / 'NativeHost/.minecraft/versions/1.20.1/logs/latest.log').read_text(errors='replace')
            assert log.rfind('NativeGuest[/127.0.0.1:') > log.rfind('NativeGuest lost connection')
            for index, game in enumerate(games):
                capture(game, f'minecraft-world-{index}')
            results.append('Guest entered the host Minecraft world through the launcher tunnel and remained connected')
            for index, window in enumerate(windows):
                ctypes.windll.user32.SetWindowPos(launcher_handles[['NativeHost', 'NativeGuest'][index]], -1, 0, 0, 0, 0, 0x0013)
                capture(window, f'room-world-connected-{index}')
        for window in [host, guest]:
            button(window, '回到首页').invoke()
            wait_for(lambda: window.child_window(title='停止游戏', control_type='Button').exists())
            button(window, '停止游戏').invoke()
            wait_for(lambda: not window.child_window(title='停止游戏', control_type='Button').exists())
            window.child_window(title_re='.*NativeHost.*房间.*', control_type='Button').invoke()
        button(guest, '离开房间并返回').invoke()
        wait_for(lambda: not guest.child_window(title='发送', control_type='Button').exists())
        capture(guest, 'guest-left')
        button(host, '离开房间并返回').invoke()
        wait_for(lambda: not host.child_window(title='发送', control_type='Button').exists())
        results.append('Both launchers left/closed the room')
        (root / 'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(results, ensure_ascii=False), flush=True)
    finally:
        # The host starts before room creation. A failure there must also release
        # its game, before the later two-window collection has populated games.
        import psutil
        owned_games = []
        for process in processes:
            if process.poll() is not None:
                continue
            try:
                owned_games.extend(child for child in psutil.Process(process.pid).children(recursive=True)
                    if child.name().lower() in ('java.exe', 'javaw.exe')
                    and Path(child.exe()).is_relative_to(root))
            except psutil.Error:
                pass
        for game in games:
            try:
                ctypes.windll.user32.PostMessageW(game.handle, 0x0010, 0, 0)
            except Exception:
                pass
        for child in owned_games:
            try:
                child.terminate()
            except psutil.Error:
                pass
        _, remaining_games = psutil.wait_procs(owned_games, timeout=5)
        for child in remaining_games:
            try:
                child.kill()
            except psutil.Error:
                pass
        for index, window in enumerate(windows):
            try:
                capture(window, f'final-{index}')
                (root / f'ui-{index}.json').write_text(json.dumps([
                    dict(text=item.window_text(), type=item.element_info.control_type)
                    for item in window.descendants()], ensure_ascii=False, indent=2), encoding='utf-8')
                window.close()
            except Exception:
                pass
        for process in processes:
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.terminate()
        if old_clipboard is not None:
            clipboard(old_clipboard)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    drive(Path(sys.argv[1]))

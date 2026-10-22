"""A separate, unprivileged chat participant for offline/LAN Java worlds.

Never edits player packets, executes commands, authenticates as another player,
or disables secure chat. Online-mode/mod handshakes require their own adapter.
"""
import asyncio
import hashlib
import json
from pathlib import Path
import re
import secrets
import struct
import time
import uuid
import zlib

from .rooms import varint, read_varint

PROFILES = json.loads(Path(__file__).with_name('chat_protocols.json').read_text(encoding='utf8'))
MAX_PACKET = 2 * 1024 * 1024


def string(value):
    data = value.encode('utf8')
    return varint(len(data)) + data


class Cursor:
    def __init__(self, data):
        self.data, self.pos = data, 0

    def take(self, size):
        if size < 0 or self.pos + size > len(self.data):
            raise ValueError('Truncated game chat packet')
        result = self.data[self.pos:self.pos + size]
        self.pos += size
        return result

    def integer(self):
        value = 0
        for i in range(5):
            byte = self.take(1)[0]
            value |= (byte & 127) << (i * 7)
            if not byte & 128:
                return value
        raise ValueError('Invalid VarInt')

    def text(self, maximum=32767):
        size = self.integer()
        if size > maximum * 4:
            raise ValueError('Game string exceeds limit')
        result = self.take(size).decode('utf8')
        if len(result) > maximum:
            raise ValueError('Game string exceeds limit')
        return result

    def nbt(self, tag=None, depth=0):
        if depth > 32:
            raise ValueError('NBT nesting exceeds limit')
        tag = self.take(1)[0] if tag is None else tag
        if tag == 0:
            return None
        if tag in (1, 2, 3, 4, 5, 6):
            fmt = {1:'b', 2:'h', 3:'i', 4:'q', 5:'f', 6:'d'}[tag]
            return struct.unpack('>' + fmt, self.take(struct.calcsize(fmt)))[0]
        if tag == 8:
            return self.take(struct.unpack('>H', self.take(2))[0]).decode('utf8')
        if tag in (7, 11, 12):
            count = struct.unpack('>i', self.take(4))[0]
            if not 0 <= count <= 65536:
                raise ValueError('NBT array exceeds limit')
            self.take(count * {7:1, 11:4, 12:8}[tag])
            return None
        if tag == 9:
            child = self.take(1)[0]
            count = struct.unpack('>i', self.take(4))[0]
            if not 0 <= count <= 4096:
                raise ValueError('NBT list exceeds limit')
            return [self.nbt(child, depth + 1) for _ in range(count)]
        if tag == 10:
            result = {}
            for _ in range(4096):
                child = self.take(1)[0]
                if child == 0:
                    return result
                key = self.take(struct.unpack('>H', self.take(2))[0]).decode('utf8')
                result[key] = self.nbt(child, depth + 1)
            raise ValueError('NBT compound exceeds limit')
        raise ValueError('Unknown NBT tag')


def plain(component):
    if isinstance(component, str):
        return component
    if isinstance(component, list):
        return ''.join(plain(item) for item in component)
    if isinstance(component, dict):
        if component.get('translate') in ('chat.type.text', 'chat.type.announcement'):
            values = [plain(item) for item in component.get('with', component.get('using', []))]
            if len(values) == 2:
                return '<' + values[0] + '> ' + values[1]
        return str(component.get('text', '')) + ''.join(plain(item) for item in component.get('extra', []))
    return ''


class GameChatBridge:
    def __init__(self, port, protocol, on_message, on_state, *, name=None):
        if protocol != 78 and str(protocol) not in PROFILES:
            raise ValueError('此游戏协议暂未接入聊天桥，房间聊天仍可使用。')
        self.port, self.protocol = port, protocol
        self.profile = PROFILES.get(str(protocol), {})
        self.on_message, self.on_state = on_message, on_state
        from .chat_validation import bridge_player_name
        self.name = bridge_player_name(name if name is not None else 'BuggChat' + secrets.token_hex(4))
        self.uuid = uuid.UUID(bytes=hashlib.md5(('OfflinePlayer:' + self.name).encode()).digest(), version=3)
        self.reader = self.writer = None
        self.compression = None
        self.state = 'login'
        self.ready = False
        self.signed_pending = 0
        self.signatures = []
        self.seen_signatures = set()
        self.write_lock = asyncio.Lock()
        self.position = None
        self.rotation = (0., 0.)
        self.permanent_error = False
        self.cipher = self.decipher = None

    async def take(self, size):
        data = await self.reader.readexactly(size)
        return self.decipher.update(data) if self.decipher else data

    async def packet_length(self):
        value = 0
        for index in range(5):
            byte = (await self.take(1))[0]
            value |= (byte & 127) << (index * 7)
            if not byte & 128:
                return value
        raise ValueError('Invalid encrypted packet length')

    async def encryption(self, cursor):
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives.serialization import load_der_public_key
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
        from cryptography.hazmat.decrepit.ciphers.modes import CFB8
        cursor.text(20)
        public_key = cursor.take(cursor.integer())
        token = cursor.take(cursor.integer())
        if len(public_key) > 4096 or len(token) > 1024:
            raise ValueError('Invalid game encryption challenge')
        secret = secrets.token_bytes(16)
        key = load_der_public_key(public_key)
        encrypted = [key.encrypt(value, padding.PKCS1v15()) for value in (secret, token)]
        # 1.19–1.19.2 use a union of verify token / signed salt.
        payload = varint(len(encrypted[0])) + encrypted[0]
        if 759 <= self.protocol <= 760:
            payload += b'\1'
        payload += varint(len(encrypted[1])) + encrypted[1]
        await self.send('encryption_begin', payload)
        cipher = Cipher(algorithms.AES(secret), CFB8(secret))
        self.cipher, self.decipher = cipher.encryptor(), cipher.decryptor()

    async def send(self, name, payload=b''):
        packet = varint(self.profile[self.state + '_toServer'][name]) + payload
        if self.compression is not None:
            packet = varint(len(packet)) + zlib.compress(packet) if len(packet) >= self.compression else b'\0' + packet
        async with self.write_lock:
            data = varint(len(packet)) + packet
            self.writer.write(self.cipher.update(data) if self.cipher else data)
            await self.writer.drain()

    async def read(self):
        length = await self.packet_length()
        if not 0 < length <= MAX_PACKET:
            raise ValueError('Game packet exceeds limit')
        data = await self.take(length)
        if self.compression is not None:
            cursor = Cursor(data)
            size = cursor.integer()
            body = cursor.take(len(data) - cursor.pos)
            if size:
                if size > MAX_PACKET:
                    raise ValueError('Compressed game packet exceeds limit')
                decoder = zlib.decompressobj()
                data = decoder.decompress(body, MAX_PACKET + 1)
                if len(data) != size or not decoder.eof or decoder.unused_data:
                    raise ValueError('Invalid compressed game packet')
            else:
                data = body
        cursor = Cursor(data)
        packet_id = cursor.integer()
        names = self.profile[self.state + '_toClient']
        return next((name for name, value in names.items() if value == packet_id), ''), cursor

    def component(self, cursor):
        return cursor.nbt() if self.protocol >= 765 and self.state != 'login' else json.loads(cursor.text())

    def login_payload(self):
        payload = string(self.name)
        if 759 <= self.protocol <= 760:
            payload += b'\0'  # No public-key signature for an offline participant.
        if 760 <= self.protocol <= 763:
            payload += b'\1' + self.uuid.bytes
        elif self.protocol >= 764:
            payload += self.uuid.bytes
        return payload

    async def settings(self):
        payload = string('zh_cn') + b'\2\0\1'
        payload += b'\0\1' if self.protocol <= 5 else b'\0'
        if self.protocol >= 107:
            payload += b'\1'
        if self.protocol >= 755:
            payload += b'\0'
        if self.protocol >= 757:
            payload += b'\1'
        if self.protocol >= 768:
            payload += b'\2'  # minimal particles
        await self.send('settings', payload)

    async def send_position(self):
        x, y, z = self.position
        payload = struct.pack('>dddd', x, y + 1.62, y, z) if self.protocol <= 5 else struct.pack('>ddd', x, y, z)
        await self.send('position', payload + b'\1')
        if 'client_tick_end' in self.profile['play_toServer']:
            await self.send('client_tick_end')

    async def position_packet(self, cursor):
        if self.protocol >= 768:
            teleport = cursor.integer()
            xyz = struct.unpack('>ddd', cursor.take(24))
            cursor.take(24)  # velocity
            rotation = struct.unpack('>ff', cursor.take(8))
            flags = struct.unpack('>I', cursor.take(4))[0]
        else:
            xyz = struct.unpack('>ddd', cursor.take(24))
            rotation = struct.unpack('>ff', cursor.take(8))
            flags = cursor.take(1)[0] if self.protocol > 5 else 0
            teleport = cursor.integer() if self.protocol >= 107 else None
        previous = self.position or (0., 0., 0.)
        self.position = tuple(value + previous[i] if flags & (1 << i) else value for i, value in enumerate(xyz))
        self.rotation = tuple(value + self.rotation[i] if flags & (1 << (i + 3)) else value
                              for i, value in enumerate(rotation))
        if teleport is not None:
            payload = varint(teleport)
            if self.protocol >= 777:
                payload += struct.pack('>dddff', *self.position, *self.rotation)
            await self.send('teleport_confirm', payload)
        await self.send_position()
        if not self.ready:
            self.ready = True
            if 'player_loaded' in self.profile['play_toServer']:
                await self.send('player_loaded')
            self.on_state('online', '游戏聊天已同步')

    async def old_chat(self, cursor, system=False):
        component = self.component(cursor)
        # Action bars, server notices and private translated messages stay local.
        position = cursor.integer() if system and self.protocol == 759 else (
            cursor.take(1)[0] if cursor.pos < len(cursor.data) else 0)
        if position != 0 and not (system and self.protocol == 759 and position == 1):
            return
        if isinstance(component, dict) and component.get('translate') not in (None, 'chat.type.text'):
            return
        text = plain(component)
        match = re.fullmatch(r'<([^<>]{1,32})> (.{1,256})', text)
        if match and match[1] != self.name:
            await self.on_message(match[1], match[2])

    async def run(self):
        if self.protocol == 78:
            from .legacy_chat import run_legacy
            return await run_legacy(self)
        try:
            self.on_state('connecting', '正在连接游戏聊天')
            self.reader, self.writer = await asyncio.wait_for(asyncio.open_connection('127.0.0.1', self.port), 5)
            handshake = b'\0' + varint(self.protocol) + string('localhost') + struct.pack('>H', self.port) + b'\2'
            self.writer.write(varint(len(handshake)) + handshake)
            await self.writer.drain()
            await self.send('login_start', self.login_payload())
            while True:
                async with asyncio.timeout(45):
                    name, cursor = await self.read()
                if name in ('disconnect', 'kick_disconnect'):
                    raise ConnectionError('游戏拒绝聊天桥连接：' + (plain(self.component(cursor)) or '请检查白名单或游戏聊天设置'))
                if name == 'encryption_begin':
                    await self.encryption(cursor)
                if name == 'compress':
                    self.compression = cursor.integer()
                elif name == 'login_plugin_request':
                    # The vanilla login protocol requires an explicit negative
                    # response to optional plugin queries, not a fake handshake.
                    await self.send('login_plugin_response', varint(cursor.integer()) + b'\0')
                elif name == 'cookie_request':
                    await self.send('cookie_response', string(cursor.text()) + b'\0')
                elif self.state == 'login' and name == 'success':
                    if self.protocol >= 764:
                        await self.send('login_acknowledged')
                        self.state = 'configuration'
                    else:
                        self.state = 'play'
                    if self.protocol >= 764:
                        await self.settings()
                elif name == 'select_known_packs':
                    await self.send('select_known_packs', b'\0')
                elif name == 'finish_configuration':
                    await self.send('finish_configuration')
                    self.state = 'play'
                elif name == 'start_configuration':
                    self.ready = False
                    await self.send('configuration_acknowledged')
                    self.state = 'configuration'
                elif name == 'keep_alive':
                    await self.send('keep_alive', cursor.take(len(cursor.data) - cursor.pos))
                    if self.position:
                        await self.send_position()
                elif name == 'ping':
                    await self.send('pong', cursor.take(4))
                elif name == 'login':
                    if self.protocol >= 766 and cursor.data[-1]:
                        raise ValueError('此世界强制签名聊天，未启用未签名聊天桥。')
                elif name == 'position':
                    await self.position_packet(cursor)
                elif name == 'chunk_batch_finished':
                    await self.send('chunk_batch_received', struct.pack('>f', 1.0))
                elif name == 'player_chat':
                    if self.protocol <= 760:
                        await self.early_player_chat(cursor)
                    else:
                        await self.player_chat(cursor)
                elif name == 'chat':
                    await self.old_chat(cursor)
                elif name == 'system_chat':
                    await self.old_chat(cursor, system=True)
        except asyncio.CancelledError:
            raise
        except (OSError, ValueError, asyncio.TimeoutError, asyncio.IncompleteReadError, KeyError) as exc:
            self.ready = False
            self.permanent_error = isinstance(exc, (ValueError, KeyError))
            detail = str(exc) or '游戏聊天连接已关闭'
            if isinstance(exc, (ValueError, KeyError)) and not detail.startswith((
                    '此世界', '此模组服务器', '此游戏协议', '游戏拒绝')):
                detail = '游戏聊天协议无法识别（可能由版本或模组导致）；房间大厅聊天仍可使用。'
            self.on_state('unavailable', detail)
        finally:
            self.ready = False
            await self.close()

    async def player_chat(self, cursor):
        if self.protocol >= 770:
            cursor.integer()
        sender = uuid.UUID(bytes=cursor.take(16))
        cursor.integer()
        signature = cursor.take(256) if cursor.take(1)[0] else None
        message = cursor.text(256)
        cursor.take(16)
        previous = cursor.integer()
        if previous > 20:
            raise ValueError('Chat acknowledgement limit exceeded')
        for _ in range(previous):
            if cursor.integer() == 0:
                cursor.take(256)
        if cursor.take(1)[0]:
            self.component(cursor)
        filter_type = cursor.integer()
        if filter_type == 2:
            size = cursor.integer()
            if size > 64:
                raise ValueError('Chat filter exceeds limit')
            cursor.take(size * 8)
        chat_type = cursor.integer()
        network_name = plain(self.component(cursor)) if self.protocol < 766 or chat_type else str(sender)[:8]
        if signature and signature not in self.seen_signatures:
            self.signatures.append(signature)
            self.signatures = self.signatures[-20:]
            self.seen_signatures = set(self.signatures)
            self.signed_pending += 1
            if self.signed_pending > 64:
                await self.send('message_acknowledgement', varint(self.signed_pending))
                self.signed_pending = 0
        # Vanilla's public chat registry ID is 0. Since 1.20.5 a registry
        # holder encodes IDs with an offset of one (0 means an inline value).
        # A signed private/team message must never be published to the room.
        public_chat_type = 1 if self.protocol >= 766 else 0
        if sender != self.uuid and filter_type == 0 and chat_type == public_chat_type:
            await self.on_message(network_name[:32] or str(sender)[:8], message)

    async def early_player_chat(self, cursor):
        if self.protocol == 759:
            message = plain(self.component(cursor))
            if cursor.take(1)[0]:
                self.component(cursor)
            chat_type = cursor.integer()
            sender = uuid.UUID(bytes=cursor.take(16))
            network_name = plain(self.component(cursor))
            filtered = 0
        else:
            if cursor.take(1)[0]:
                cursor.take(cursor.integer())
            sender = uuid.UUID(bytes=cursor.take(16))
            signature = cursor.take(cursor.integer())
            message = cursor.text(256)
            if cursor.take(1)[0]:
                self.component(cursor)
            cursor.take(16)
            count = cursor.integer()
            if count > 20:
                raise ValueError('Chat acknowledgement limit exceeded')
            for _ in range(count):
                cursor.take(16)
                cursor.take(cursor.integer())
            if cursor.take(1)[0]:
                self.component(cursor)
            filtered = cursor.integer()
            if filtered == 2:
                count = cursor.integer()
                if count > 64:
                    raise ValueError('Chat filter exceeds limit')
                cursor.take(count * 8)
            chat_type = cursor.integer()
            network_name = plain(self.component(cursor))
            if signature:
                self.signatures = [entry for entry in self.signatures if entry[0] != sender.bytes]
                self.signatures.append((sender.bytes, signature))
                self.signatures = self.signatures[-5:]
                await self.send('message_acknowledgement', self.early_ack())
        if sender != self.uuid and filtered == 0 and chat_type == 0:
            await self.on_message(network_name[:32] or str(sender)[:8], message)

    def early_ack(self):
        return varint(len(self.signatures)) + b''.join(
            sender + varint(len(signature)) + signature for sender, signature in self.signatures) + b'\0'

    async def send_message(self, sender, text):
        if not self.ready:
            raise ConnectionError('游戏聊天尚未连接，消息仅送达房间大厅。')
        prefix = '[大厅] ' + sender + ': '
        # Split at code point boundaries; never silently truncate the user's text.
        budget = (200 if self.protocol < 315 else 512) - len(prefix.encode('utf-16-le'))
        if budget < 4:
            raise ValueError('聊天昵称过长。')
        chunks, chunk, size = [], '', 0
        for char in text:
            units = len(char.encode('utf-16-le'))
            if size + units > budget:
                chunks.append(chunk)
                chunk, size = '', 0
            chunk += char
            size += units
        if chunk:
            chunks.append(chunk)
        for index, chunk in enumerate(chunks):
            if index:
                await asyncio.sleep(.6)
            if self.protocol == 78:
                from .legacy_chat import text as legacy_text, write
                async with self.write_lock:
                    write(self, b'\x03' + legacy_text(prefix + chunk))
                    await self.writer.drain()
                continue
            payload = string(prefix + chunk)
            if self.protocol >= 759:
                payload += struct.pack('>qq', int(time.time() * 1000), 0) + b'\0'
                if self.protocol <= 760:
                    payload += b'\0'
                    if self.protocol == 760:
                        payload += self.early_ack()
                else:
                    acknowledged = ((1 << len(self.signatures)) - 1) << (20 - len(self.signatures))
                    payload += varint(self.signed_pending) + acknowledged.to_bytes(3, 'little')
                    if self.protocol >= 770:
                        payload += b'\0'  # Zero explicitly skips the optional checksum.
            await self.send('chat_message' if self.protocol >= 759 else 'chat', payload)
            self.signed_pending = 0

    async def close(self):
        if self.writer:
            writer, self.writer = self.writer, None
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), 3)
            except (OSError, asyncio.TimeoutError):
                writer.transport.abort()

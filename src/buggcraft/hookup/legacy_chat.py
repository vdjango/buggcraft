"""Bounded reader for the pre-Netty Java 1.6.4 packet stream.

Packet field names are derived from the BSD-licensed node-minecraft-protocol
reference. Unlike modern packets, these have no length prefix: every field must
be consumed, even when the chat participant does not use its contents.
"""
import asyncio
import json
from pathlib import Path
import re
import secrets
import struct

PACKETS = json.loads(Path(__file__).with_name('legacy_packets.json').read_text(encoding='utf8'))
MAX_FIELD = 2 * 1024 * 1024


def text(value):
    data = value.encode('utf-16-be')
    return struct.pack('>H', len(data) // 2) + data


class LegacyReader:
    def __init__(self, reader):
        self.reader = reader
        self.remaining = MAX_FIELD
        self.decipher = None

    async def take(self, count):
        if count < 0 or count > self.remaining:
            raise ValueError('Legacy packet exceeds limit')
        self.remaining -= count
        data = await self.reader.readexactly(count)
        return self.decipher.update(data) if self.decipher else data

    async def number(self, fmt):
        return struct.unpack('>' + fmt, await self.take(struct.calcsize(fmt)))[0]

    async def count(self, fmt, maximum=65536):
        count = await self.number(fmt)
        if not 0 <= count <= maximum:
            raise ValueError('Legacy array exceeds limit')
        return count

    async def field(self, kind):
        formats = {'int':'i', 'short':'h', 'ushort':'H', 'byte':'b', 'ubyte':'B',
                   'bool':'?', 'long':'q', 'double':'d', 'float':'f'}
        if kind in formats:
            return await self.number(formats[kind])
        if kind in ('string', 'ustring', 'ascii'):
            size = await self.count('h', 32767)
            return (await self.take(size * (1 if kind == 'ascii' else 2))).decode(
                'ascii' if kind == 'ascii' else 'utf-16-be', errors='replace')
        if kind in ('byteArray16', 'byteArray32'):
            return await self.take(await self.count('h' if kind.endswith('16') else 'i', MAX_FIELD))
        if kind == 'slot':
            item = await self.number('h')
            if item != -1:
                await self.take(3)
                size = await self.number('h')
                if size != -1:
                    await self.take(size)
            return item
        if kind in ('slotArray', 'stringArray'):
            count = await self.count('h', 4096)
            for _ in range(count):
                await self.field('slot' if kind == 'slotArray' else 'string')
        elif kind == 'intArray8':
            await self.take(4 * await self.count('B', 255))
        elif kind == 'byteVectorArray':
            await self.take(3 * await self.count('i'))
        elif kind == 'objectData':
            if await self.number('i') != 0:
                await self.take(6)
        elif kind == 'mapChunkBulk':
            count = await self.count('h', 4096)
            size = await self.count('i', MAX_FIELD)
            await self.take(1 + size + 12 * count)
        elif kind == 'propertyArray':
            for _ in range(await self.count('i', 4096)):
                await self.field('string')
                await self.take(8)
                await self.take(25 * await self.count('h', 4096))
        elif kind == 'entityMetadata':
            types = ['byte','short','int','float','string','slot','intVector']
            for _ in range(256):
                marker = await self.number('B')
                if marker == 127:
                    return
                if marker >> 5 >= len(types):
                    raise ValueError('Unknown legacy metadata type')
                await self.field(types[marker >> 5])
            raise ValueError('Legacy metadata exceeds limit')
        elif kind in ('intVector', 'byteVector'):
            await self.take(12 if kind == 'intVector' else 3)
        else:
            raise ValueError('Unknown legacy packet field: ' + kind)

    async def packet(self):
        self.remaining = MAX_FIELD
        packet_id = await self.number('B')
        fields = PACKETS.get(str(packet_id))
        if fields is None:
            raise ValueError('Unknown legacy packet: ' + str(packet_id))
        result = {}
        # Scoreboard/team packet fields are conditional in the wire protocol.
        for field in fields:
            name = field['name']
            if packet_id == 0xcf and name in ('scoreName', 'value') and result.get('remove'):
                continue
            if packet_id == 0xd1:
                mode = result.get('mode')
                if name in ('name','prefix','suffix','friendlyFire') and mode not in (0, 2):
                    continue
                if name == 'players' and mode not in (0, 3, 4):
                    continue
            result[name] = await self.field(field['type'])
        if packet_id == 0x64 and result.get('inventoryType') == 11:
            await self.take(4)
        return packet_id, result


async def run_legacy(bridge):
    """Use a separate participant; player streams remain byte-for-byte intact."""
    from .game_chat import plain
    pending_cipher = pending_decipher = None
    try:
        bridge.on_state('connecting', '正在连接 1.6.4 游戏聊天')
        bridge.reader, bridge.writer = await asyncio.wait_for(
            asyncio.open_connection('127.0.0.1', bridge.port), 5)
        bridge.writer.write(b'\x02\x4e' + text(bridge.name) + text('localhost') + struct.pack('>i', bridge.port))
        await bridge.writer.drain()
        reader = LegacyReader(bridge.reader)
        while True:
            async with asyncio.timeout(45):
                packet_id, packet = await reader.packet()
            if packet_id == 0xfd:
                # Offline 1.6.4 can still encrypt transport. Complete that
                # handshake without borrowing a real player's credentials.
                from cryptography.hazmat.primitives.asymmetric import padding
                from cryptography.hazmat.primitives.serialization import load_der_public_key
                from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
                from cryptography.hazmat.decrepit.ciphers.modes import CFB8
                secret = secrets.token_bytes(16)
                key = load_der_public_key(packet['publicKey'])
                encrypted = [key.encrypt(value, padding.PKCS1v15())
                             for value in (secret, packet['verifyToken'])]
                bridge.writer.write(b'\xfc' + b''.join(struct.pack('>H', len(value)) + value for value in encrypted))
                cipher = Cipher(algorithms.AES(secret), CFB8(secret))
                pending_cipher, pending_decipher = cipher.encryptor(), cipher.decryptor()
            elif packet_id == 0xfc:
                if pending_cipher is None:
                    raise ValueError('Unexpected legacy encryption acknowledgement')
                bridge.legacy_cipher = pending_cipher
                reader.decipher = pending_decipher
                write(bridge, b'\xcd\0')
            elif packet_id == 0xff:
                raise ConnectionError('游戏拒绝聊天桥连接：' + packet['reason'])
            elif packet_id == 0:
                write(bridge, b'\0' + struct.pack('>i', packet['keepAliveId']))
                if bridge.position:
                    x, y, z = bridge.position
                    write(bridge, b'\x0b' + struct.pack('>dddd?', x, y, y + 1.62, z, True))
            elif packet_id == 0x0d:
                bridge.position = packet['x'], packet['y'], packet['z']
                write(bridge, b'\x0d' + struct.pack('>ddddff?', packet['x'], packet['y'],
                    packet['stance'], packet['z'], packet['yaw'], packet['pitch'], True))
                if not bridge.ready:
                    bridge.ready = True
                    bridge.on_state('online', '游戏聊天已同步')
            elif packet_id == 0x03:
                raw = packet['message']
                try:
                    raw = plain(json.loads(raw))
                except json.JSONDecodeError:
                    pass
                match = re.fullmatch(r'<([^<>]{1,32})> (.{1,256})', raw)
                if match and match[1] != bridge.name:
                    await bridge.on_message(match[1], match[2])
            await bridge.writer.drain()
    except asyncio.CancelledError:
        raise
    except (OSError, ValueError, asyncio.TimeoutError, asyncio.IncompleteReadError) as exc:
        bridge.permanent_error = isinstance(exc, ValueError)
        bridge.on_state('unavailable', str(exc) or '游戏聊天连接已关闭')
    finally:
        bridge.ready = False
        await bridge.close()


def write(bridge, packet):
    cipher = getattr(bridge, 'legacy_cipher', None)
    bridge.writer.write(cipher.update(packet) if cipher else packet)

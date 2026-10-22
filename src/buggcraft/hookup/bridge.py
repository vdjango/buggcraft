"""JSON-RPC 2.0 over stdio. Room networking stays inside this subprocess."""
import asyncio
import json
import logging
import secrets
import sys

import asyncssh

from .nodes import decode_code, probe
from .relay import RoomInvite, TunnelClient, TunnelHost
from .rooms import connect_directory, request as directory_request

MAX_LINE = 8192


class RPCError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message


async def serve(reader, writer):
    nodes, endpoints, tasks = {}, {}, {}

    async def send(value):
        writer.write((json.dumps(value, ensure_ascii=True, separators=(',', ':')) + '\n').encode())
        await writer.drain()

    async def stop(session):
        endpoint = endpoints.pop(session, None)
        if endpoint is None:
            raise RPCError(-32004, 'Unknown session')
        await endpoint.stop()
        await asyncio.gather(tasks.pop(session), return_exceptions=True)
        return {'closed': True}

    async def add(endpoint):
        if len(endpoints) >= 8:
            raise RPCError(-32010, 'Session limit reached')
        session = secrets.token_urlsafe(18)
        endpoints[session] = endpoint
        online = asyncio.Event()
        endpoint.on_status = lambda state, detail: online.set() if state == 'online' else None
        task = tasks[session] = asyncio.create_task(endpoint.run())
        waiter = asyncio.create_task(online.wait())
        try:
            done, _ = await asyncio.wait((task, waiter), timeout=15,
                                         return_when=asyncio.FIRST_COMPLETED)
            if task in done:
                task.result()
                raise RPCError(-32020, 'Room closed before becoming ready')
            if waiter not in done:
                raise RPCError(-32021, 'Room connection timed out')
            return {'session': session, 'room': endpoint.invite.room_id,
                    'address': f'127.0.0.1:{endpoint.listen_port}' if endpoint.role == 'client' else None,
                    'transport': endpoint.transport_state, 'state': 'online'}
        except BaseException:
            await stop(session)
            raise
        finally:
            waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)

    def node(params):
        handle = params.get('node')
        if not isinstance(handle, str) or handle not in nodes:
            raise RPCError(-32602, 'Unknown node handle; call node.add first')
        return nodes[handle]

    async def dispatch(method, params):
        if method == 'bridge.initialize':
            if params.get('protocol', 1) != 1:
                raise RPCError(-32602, 'Unsupported bridge protocol version')
            return {'protocol': 1, 'name': 'buggcraft-bridge', 'jsonrpc': '2.0',
                    'transports': ['auto', 'relay'], 'mixed_rooms': True,
                    'methods': ['node.add', 'node.remove', 'room.list', 'room.host',
                                'room.join', 'room.close', 'session.list'],
                    'limits': {'request_bytes': MAX_LINE, 'nodes': 16, 'sessions': 8}}
        if method == 'node.add':
            if len(nodes) >= 16:
                raise RPCError(-32010, 'Node limit reached')
            if not isinstance(params.get('code'), str):
                raise RPCError(-32602, 'code must be a string')
            profile = await probe(decode_code(params['code']))
            handle = secrets.token_urlsafe(12)
            nodes[handle] = profile
            return {'node': handle, 'name': getattr(profile, '_name', '') or 'Node',
                    'identity': 'account' if profile.token.startswith('acct1') else 'anonymous'}
        if method == 'node.remove':
            profile = node(params)
            if any(e.profile is profile for e in endpoints.values()):
                raise RPCError(-32009, 'Node has active rooms')
            del nodes[params['node']]
            return {'removed': True}
        if method == 'room.list':
            offset = params.get('offset', 0)
            if type(offset) is not int or offset < 0:
                raise RPCError(-32602, 'Invalid offset')
            async with await connect_directory(node(params)) as connection:
                return await directory_request(connection, 'list', offset=offset)
        if method in ('room.host', 'room.join'):
            profile = node(params)
            policy = params.get('transport', 'auto')
            if policy not in ('auto', 'relay'):
                raise RPCError(-32602, 'Invalid transport policy')
            if method == 'room.host':
                port = params.get('game_port', 25565)
                if type(port) is not int or not 1 <= port <= 65535:
                    raise RPCError(-32602, 'Invalid game_port')
                invite = RoomInvite.create()
                endpoint = TunnelHost(profile, invite, game_port=port, listen_port=0,
                                      announce=False, transport_policy=policy)
            else:
                if not isinstance(params.get('invite'), str):
                    raise RPCError(-32602, 'invite must be a string')
                invite = RoomInvite.decode(params['invite'])
                endpoint = TunnelClient(profile, invite, listen_port=0, announce=False,
                                        transport_policy=policy)
            result = await add(endpoint)
            if method == 'room.host':
                result['invite'] = invite.encode()
            return result
        if method == 'room.close':
            if not isinstance(params.get('session'), str):
                raise RPCError(-32602, 'session must be a string')
            return await stop(params['session'])
        if method == 'session.list':
            return {'sessions': [{'session': key, 'role': e.role, 'room': e.invite.room_id,
                'state': 'stopped' if tasks[key].done() else e.room_state,
                'transport': e.transport_state,
                'address': f'127.0.0.1:{e.listen_port}' if e.role == 'client' else None}
                for key, e in endpoints.items()]}
        raise RPCError(-32601, 'Method not found')

    try:
        while True:
            # Reject an unterminated oversized frame before allocating more.
            try:
                line = await reader.readline()
            except (ValueError, asyncio.LimitOverrunError):
                await send({'jsonrpc': '2.0', 'id': None,
                            'error': {'code': -32600, 'message': 'Request too large'}})
                break
            if not line:
                break
            identifier, notification = None, False
            try:
                if len(line) > MAX_LINE:
                    raise RPCError(-32600, 'Request too large')
                try:
                    value = json.loads(line)
                except (ValueError, UnicodeError) as exc:
                    raise RPCError(-32700, 'Parse error') from exc
                if not isinstance(value, dict) or value.get('jsonrpc') != '2.0':
                    raise RPCError(-32600, 'Invalid request')
                notification = 'id' not in value
                identifier = value.get('id')
                if identifier is not None and (type(identifier) not in (str, int) or
                        isinstance(identifier, str) and len(identifier) > 128):
                    identifier = None
                    raise RPCError(-32600, 'Invalid request id')
                if not isinstance(value.get('method'), str):
                    raise RPCError(-32600, 'Invalid method')
                if not isinstance(value.get('params', {}), dict):
                    raise RPCError(-32602, 'params must be an object')
                result = await dispatch(value['method'], value.get('params', {}))
                if not notification:
                    await send({'jsonrpc': '2.0', 'id': identifier, 'result': result})
            except RPCError as exc:
                if not notification:
                    await send({'jsonrpc': '2.0', 'id': identifier,
                                'error': {'code': exc.code, 'message': exc.message}})
            except (ValueError, TypeError, KeyError):
                if not notification:
                    await send({'jsonrpc': '2.0', 'id': identifier,
                                'error': {'code': -32602, 'message': 'Invalid parameters'}})
            except (OSError, asyncssh.Error, asyncio.TimeoutError):
                if not notification:
                    await send({'jsonrpc': '2.0', 'id': identifier,
                                'error': {'code': -32000, 'message': 'Node operation failed'}})
            if len(line) > MAX_LINE:
                break
    finally:
        await asyncio.gather(*(e.stop() for e in endpoints.values()), return_exceptions=True)
        await asyncio.gather(*tasks.values(), return_exceptions=True)
        writer.close()
        try:
            await writer.wait_closed()
        except NotImplementedError:
            pass


async def main():
    # Windows launchers usually provide synchronous anonymous pipes, which
    # cannot be attached to ProactorEventLoop. Threaded bounded IO also works
    # on Unix and never blocks the networking event loop.
    class Input:
        async def readline(self):
            return await asyncio.to_thread(sys.stdin.buffer.readline, MAX_LINE + 1)

    class Output:
        def __init__(self):
            self.pending = b''

        def write(self, data):
            self.pending = data

        async def drain(self):
            data, self.pending = self.pending, b''
            def flush():
                sys.stdout.buffer.write(data)
                sys.stdout.buffer.flush()
            await asyncio.to_thread(flush)

        def close(self):
            pass

        async def wait_closed(self):
            pass

    await serve(Input(), Output())


if __name__ == '__main__':
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass

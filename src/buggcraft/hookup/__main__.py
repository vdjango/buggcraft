"""Native Python room client: python -m buggcraft.hookup."""
import argparse
import asyncio
import logging
import signal
import os
from .relay import RelayProfile, RoomInvite, TunnelHost, TunnelClient


async def main(args):
    if args.role == 'bridge':
        from .bridge import main as bridge_main
        await bridge_main()
        return
    if not args.profile:
        raise ValueError('--profile is required for host/client mode')
    profile = RelayProfile.load(args.profile)
    callback = lambda state, detail: print(f'{state}: {detail}', flush=True)
    if args.role == 'host':
        invite = RoomInvite.decode(args.invite) if args.invite else RoomInvite.create()
        endpoint = TunnelHost(profile, invite, game_port=args.game_port, on_status=callback)
        print('房间邀请（仅发给好友）: ' + invite.encode(), flush=True)
    else:
        if not args.invite:
            raise ValueError('加入房间需要 --invite')
        endpoint = TunnelClient(profile, RoomInvite.decode(args.invite),
                                listen_port=args.listen_port, on_status=callback)
    task = asyncio.create_task(endpoint.run())
    if os.name != 'nt':
        for sig in (signal.SIGINT, signal.SIGTERM):
            asyncio.get_running_loop().add_signal_handler(sig, task.cancel)
    try:
        await task
    finally:
        await endpoint.stop()


parser = argparse.ArgumentParser(description='Minecraft 加密房间联机，无需虚拟网卡')
parser.add_argument('role', choices=['host', 'client', 'bridge'])
parser.add_argument('--profile', help='受信任服务配置 JSON；bridge 模式不需要')
parser.add_argument('--invite', help='主机提供的房间邀请')
parser.add_argument('--game-port', type=int, default=25565)
parser.add_argument('--listen-port', type=int, default=25566)
if __name__ == '__main__':
    logging.basicConfig(level=logging.WARNING)
    try:
        asyncio.run(main(parser.parse_args()))
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass

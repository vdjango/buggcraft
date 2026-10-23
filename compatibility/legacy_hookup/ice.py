"""Route-aware gathering for aioice 0.10.2; ICE checks remain upstream's.

Host binding is adapted from aioice, Copyright (c) 2018-2019 Jeremy Lainé.
BSD-3-Clause; see THIRD_PARTY_NOTICES.txt for the full license.
"""
import asyncio
import ipaddress
import logging
import socket
import time

from aioice import Candidate, Connection as AioIceConnection
from aioice.candidate import candidate_foundation, candidate_priority
from aioice.ice import StunProtocol, server_reflexive_candidate
from aioice.turn import UDP_SOCKET_BUFFER_SIZE
import psutil

LOG = logging.getLogger(__name__)
PRIMARY_STUN_WAIT = 1
ROUTE_LOOKUP_TIMEOUT = .5


def usable_addresses(addresses):
    """Keep LAN/VPN/IPv6 paths, excluding unusable and known down addresses.

    Up virtual adapters remain eligible for LAN peers, regardless of whether
    they can reach the public STUN service.
    """
    states = {}
    try:
        stats = psutil.net_if_stats()
        for name, entries in psutil.net_if_addrs().items():
            if name in stats:
                for entry in entries:
                    address = entry.address.split('%', 1)[0]
                    states.setdefault(address, set()).add(stats[name].isup)
    except (OSError, psutil.Error):
        LOG.debug('ice_interface_status_unavailable', exc_info=True)

    result = []
    for address in addresses:
        ip = ipaddress.ip_address(address)
        reason = None
        if ip.is_unspecified or ip.is_loopback or ip.is_multicast or ip.is_link_local:
            reason = 'unusable-address'
        elif states.get(address) == {False}:
            reason = 'interface-down'
        if reason:
            LOG.info('ice_address_skipped address=%s reason=%s', address, reason)
        elif address not in result:
            result.append(address)
    return result


async def stun_route(server):
    """Resolve one IPv4 target and ask the OS which source would reach it.

    UDP connect selects a route without sending any probe or game data. Pin
    STUN queries to this resolved target so the source decision stays valid.
    """
    loop = asyncio.get_running_loop()
    records = await asyncio.wait_for(loop.getaddrinfo(
        server[0], server[1], family=socket.AF_INET, type=socket.SOCK_DGRAM), ROUTE_LOOKUP_TIMEOUT)
    target = (records[0][4][0], server[1])
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.connect(target)
        source = probe.getsockname()[0]
    return target, source


class Connection(AioIceConnection):
    async def get_component_candidates(self, component, addresses, timeout=5):
        # The launcher uses STUN plus SSH fallback. Preserve upstream TURN
        # behavior for other consumers of the vendored adapter.
        addresses = usable_addresses(addresses)
        trace = getattr(self, 'diagnostic_trace', f'ice-{self._id}')
        if self.turn_server:
            LOG.info('ice_gather_policy trace=%s policy=upstream reason=turn-configured', trace)
            return await super().get_component_candidates(component, addresses, timeout=timeout)

        started = time.monotonic()
        deadline = started + timeout
        loop = asyncio.get_running_loop()
        protocols, candidates, tasks = [], [], set()
        stop_reason = 'cancelled'
        try:
            for address in addresses:
                if self._closed:
                    raise ConnectionError('ICE closed during gathering')
                transport = None
                try:
                    transport, protocol = await loop.create_datagram_endpoint(
                        lambda: StunProtocol(self), local_addr=(address, 0))
                    if self._closed:
                        transport.close()
                        raise ConnectionError('ICE closed during binding')
                    sock = transport.get_extra_info('socket')
                    if sock is not None:
                        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, UDP_SOCKET_BUFFER_SIZE)
                except OSError as exc:
                    if transport:
                        transport.close()
                    LOG.info('ice_host_bind trace=%s address=%s result=%s errno=%s',
                             trace, address, type(exc).__name__, exc.errno)
                    if self._closed:
                        raise
                    continue
                host, port = transport.get_extra_info('sockname')[:2]
                protocol.local_candidate = Candidate(
                    foundation=candidate_foundation('host', 'udp', host), component=component,
                    transport='udp', priority=candidate_priority(component, 'host'),
                    host=host, port=port, type='host')
                # Register immediately: cancellation/peer departure must close
                # every socket even when binding the next address is interrupted.
                self._protocols.append(protocol)
                protocols.append(protocol)
                candidates.append(protocol.local_candidate)

            if not protocols:
                raise ConnectionError('No usable ICE sockets')
            ipv4 = [p for p in protocols if ipaddress.ip_address(p.local_candidate.host).version == 4]
            if not self.stun_server or not ipv4:
                stop_reason = 'host-only'
                return candidates

            server, source = self.stun_server, None
            try:
                server, source = await asyncio.wait_for(stun_route(server),
                    max(0, deadline - time.monotonic()))
            except (OSError, ValueError, asyncio.TimeoutError) as exc:
                LOG.info('ice_route trace=%s server=%s:%s result=fallback-all reason=%s',
                         trace, *server, type(exc).__name__)
            preferred = [p for p in ipv4 if p.local_candidate.host == source]
            route_matched = bool(preferred)
            others = [p for p in ipv4 if p not in preferred]
            LOG.info('ice_gather_policy trace=%s server=%s:%s source=%s hosts=%d primary=%d policy=%s',
                     trace, *server, source, len(candidates), len(preferred),
                     'route-first' if preferred else 'all-interfaces')
            if not preferred:
                if source:
                    LOG.info('ice_route trace=%s result=fallback-all reason=source-not-bound source=%s',
                             trace, source)
                preferred, others = ipv4, []

            async def query(protocol, phase):
                address = protocol.local_candidate.host
                query_started = time.monotonic()
                LOG.info('ice_stun_start trace=%s address=%s phase=%s', trace, address, phase)
                try:
                    candidate, _ = await server_reflexive_candidate(protocol, server)
                    LOG.info('ice_stun_result trace=%s address=%s phase=%s result=ok mapped=%s:%s elapsed_ms=%d',
                             trace, address, phase, candidate.host, candidate.port,
                             (time.monotonic() - query_started) * 1000)
                    return candidate
                except asyncio.CancelledError:
                    LOG.info('ice_stun_result trace=%s address=%s phase=%s result=cancelled reason=%s elapsed_ms=%d',
                             trace, address, phase, stop_reason, (time.monotonic() - query_started) * 1000)
                    raise
                except Exception as exc:
                    LOG.info('ice_stun_result trace=%s address=%s phase=%s result=%s elapsed_ms=%d',
                             trace, address, phase, type(exc).__name__,
                             (time.monotonic() - query_started) * 1000)
                    return None

            def launch(group, phase):
                launched = {asyncio.create_task(query(p, phase)) for p in group}
                tasks.update(launched)
                return launched

            async def collect(pending, budget):
                until = time.monotonic() + max(0, budget)
                while pending and time.monotonic() < until:
                    done, pending = await asyncio.wait(pending,
                        timeout=max(0, until - time.monotonic()), return_when=asyncio.FIRST_COMPLETED)
                    found = []
                    for task in done:
                        if not task.cancelled() and (candidate := task.result()) is not None:
                            found.append(candidate)
                    if found:
                        candidates.extend(found)
                        return True, pending
                return False, pending

            pending = launch(preferred, 'primary' if route_matched else 'all')
            budget = max(0, deadline - time.monotonic())
            found, pending = await collect(pending, min(PRIMARY_STUN_WAIT, budget) if others else budget)
            if not found and others:
                LOG.info('ice_stun_fallback trace=%s reason=%s interfaces=%d remaining_ms=%d',
                         trace, 'primary-slow' if pending else 'primary-failed', len(others),
                         max(0, deadline - time.monotonic()) * 1000)
                pending |= launch(others, 'fallback')
                found, pending = await collect(pending, max(0, deadline - time.monotonic()))
            stop_reason = 'mapping-found' if found else 'stun-timeout' if pending else 'stun-failed'
            return candidates
        except Exception:
            stop_reason = 'gather-failed'
            raise
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            LOG.info('ice_gather_complete trace=%s component=%s hosts=%d srflx=%d result=%s elapsed_ms=%d',
                     trace, component, len(protocols), sum(c.type == 'srflx' for c in candidates), stop_reason,
                     (time.monotonic() - started) * 1000)

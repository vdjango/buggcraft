"""Best-effort local route evidence; never infer a NAT class from one STUN reply."""
from datetime import datetime, timezone
import ipaddress
import json
import logging
import os
from pathlib import Path
import platform
import subprocess
import socket
import threading
import queue

from .nat_probe import probe_network

LOG = logging.getLogger('hookup.network_diagnostics')
_session_probe_lock = threading.Lock()


def resolve_probe_server(host, port, family, timeout=0.8):
    """Bound OS DNS even when a VPN's resolver is unresponsive."""
    result = queue.Queue(maxsize=1)
    def resolve():
        try:
            addresses = socket.getaddrinfo(host, port, family, socket.SOCK_DGRAM)
            result.put((addresses[0][4][:2], None))
        except (OSError, IndexError) as exc:
            result.put((None, type(exc).__name__))
    threading.Thread(target=resolve, daemon=True, name='diagnostic-dns').start()
    try:
        return result.get(timeout=timeout)
    except queue.Empty:
        return None, 'dns-timeout'


def capture_session_network(directory, trace_id):
    """One bounded background capture per concurrent batch of room attempts."""
    if not _session_probe_lock.acquire(blocking=False):
        LOG.info('network_snapshot_skipped trace=%s reason=probe-in-progress', trace_id)
        return None
    try:
        return capture_network(directory, trace_id)
    except Exception as exc:
        LOG.warning('network_snapshot_failed trace=%s error=%s', trace_id, type(exc).__name__)
        return None
    finally:
        _session_probe_lock.release()


def address_scope(address):
    try:
        ip = ipaddress.ip_address(address.split('%', 1)[0])
        if ip in ipaddress.ip_network('100.64.0.0/10'):
            return 'shared-address-space'
        if ip.is_loopback:
            return 'loopback'
        if ip.is_link_local:
            return 'link-local'
        return 'global' if ip.is_global else 'private-or-special'
    except ValueError:
        return 'unknown'


def capture_network(directory, trace_id, *, active_probe=True, stun_servers=None,
                    filtering_server=None, ipv6_servers=None):
    """Runs in a worker thread. Failure cannot stop ICE or SSH connections."""
    result = {'schema': 2, 'trace_id': trace_id,
              'captured_utc': datetime.now(timezone.utc).isoformat(),
              'platform': platform.system(), 'interfaces': [],
              'topology_scope': 'Local interfaces, connection profiles, DNS and route table; per-peer ICE candidates and selected pairs are in p2p session logs.',
              'nat_type': 'unknown',
              'nat_type_reason': 'Local routes and a single STUN mapping do not establish NAT filtering or mapping behavior.',
              'proxy_environment_present': {key: bool(os.environ.get(key)) for key in
                                            ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY')}}
    try:
        import psutil
        stats = psutil.net_if_stats()
        for name, addresses in psutil.net_if_addrs().items():
            interface = {'name': name, 'is_up': stats[name].isup if name in stats else None,
                         'speed_mbps': stats[name].speed if name in stats else None, 'addresses': []}
            for address in addresses:
                if address.family.name not in ('AF_INET', 'AF_INET6'):
                    continue
                interface['addresses'].append({'address': address.address, 'netmask': address.netmask,
                                                'family': address.family.name, 'scope': address_scope(address.address)})
            result['interfaces'].append(interface)
    except Exception as exc:
        result['interfaces_error'] = type(exc).__name__
    system = platform.system()
    if system == 'Windows':
        command = ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
            "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; $ErrorActionPreference='Stop'; "
            "$n=@{adapters=@(Get-NetAdapter | Select-Object Name,InterfaceDescription,ifIndex,Status,LinkSpeed,MediaType,PhysicalMediaType,Virtual,HardwareInterface); "
            "profiles=@(Get-NetConnectionProfile | Select-Object Name,InterfaceAlias,InterfaceIndex,NetworkCategory,IPv4Connectivity,IPv6Connectivity); "
            "graphics=@(Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion,DriverDate,AdapterRAM,VideoProcessor,Status); "
            "gateways=@(Get-NetIPConfiguration | Select-Object InterfaceAlias,InterfaceIndex,@{n='IPv4Gateway';e={$_.IPv4DefaultGateway.NextHop}},@{n='IPv6Gateway';e={$_.IPv6DefaultGateway.NextHop}}); "
            "routes=@(Get-NetRoute | Select-Object AddressFamily,DestinationPrefix,NextHop,InterfaceIndex,RouteMetric,InterfaceMetric); "
            "dns=@(Get-DnsClientServerAddress | Select-Object InterfaceAlias,InterfaceIndex,AddressFamily,ServerAddresses)}; "
            "$n | ConvertTo-Json -Depth 5 -Compress"]
    elif system == 'Darwin':
        command = ['/usr/sbin/netstat', '-rn']
    else:
        command = ['ip', '-j', 'route', 'show', 'table', 'all']
    try:
        run = subprocess.run(command, capture_output=True, timeout=8,
                             creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        output = run.stdout[:256 * 1024].decode('utf-8-sig', errors='replace')
        result['route_probe_exit'] = run.returncode
        if run.returncode == 0:
            try:
                result['routes_and_adapters'] = json.loads(output)
            except ValueError:
                result['route_table'] = output
        else:
            result['route_error'] = run.stderr[:2000].decode('utf-8', errors='replace')
    except (OSError, subprocess.TimeoutExpired) as exc:
        result['route_error'] = type(exc).__name__
    result['global_ipv6_configured'] = None if 'interfaces_error' in result else any(
        a['family'] == 'AF_INET6' and a['scope'] == 'global'
        for interface in result['interfaces'] if interface['is_up']
        for a in interface['addresses'])
    if active_probe:
        try:
            resolution = {}
            if filtering_server is None:
                filtering_server, resolution['filtering_error'] = resolve_probe_server(
                    'stun.nextcloud.com', 3478, socket.AF_INET)
                resolution['filtering_host'] = 'stun.nextcloud.com'
            if ipv6_servers is None and result['global_ipv6_configured']:
                ipv6, resolution['ipv6_error'] = resolve_probe_server(
                    'stun.l.google.com', 19302, socket.AF_INET6)
                ipv6_servers = [ipv6] if ipv6 else []
                resolution['ipv6_host'] = 'stun.l.google.com'
            result['probe_resolution'] = resolution
            result['nat_probe'] = probe_network(stun_servers,
                filtering_server=filtering_server, ipv6_servers=ipv6_servers, budget=16)
            if not result['nat_probe']['ipv6'].get('observations'):
                result['nat_probe']['ipv6']['reason'] = ('interface-discovery-unavailable'
                    if result['global_ipv6_configured'] is None else
                    'no-global-ipv6-address' if not result['global_ipv6_configured'] else
                    'no-resolved-ipv6-stun-server')
            mapping = result['nat_probe']['ipv4']['mapping']['behavior']
            filtering = result['nat_probe']['ipv4']['filtering']['behavior']
            result['nat_type'] = {
                ('endpoint-independent', 'endpoint-independent'): 'full-cone-observed',
                ('endpoint-independent', 'address-dependent'): 'restricted-cone-observed',
                ('endpoint-independent', 'address-and-port-dependent'): 'port-restricted-cone-observed',
            }.get((mapping, filtering), 'mapping-' + mapping if mapping != 'unknown' else 'unknown')
            result['nat_type_reason'] = 'Observed mapping=' + mapping + '; filtering=' + filtering + '. This is a network-path observation, not proof of peer reachability.'
        except Exception as exc:
            result['nat_probe'] = {'status': 'failed', 'error': type(exc).__name__}
    result['p2p_capability'] = {'status': 'not-verified-by-network-probe',
        'reason': 'Inspect per-attempt ICE candidates, selected IPv4/IPv6 pair and game data-path evidence in player journals.'}
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / ('network-' + trace_id + '.json')
    # Atomic replace prevents export while a partial JSON snapshot is being written.
    temporary = destination.with_suffix('.tmp')
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(destination)
    LOG.info('network_snapshot trace=%s file=%s interfaces=%d route_status=%s nat_type=%s',
             trace_id, destination.name, len(result['interfaces']), result.get('route_probe_exit', result.get('route_error')), result['nat_type'])
    return result

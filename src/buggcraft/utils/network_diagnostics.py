"""Best-effort local route evidence; never infer a NAT class from one STUN reply."""
from datetime import datetime, timezone
import ipaddress
import json
import logging
import os
from pathlib import Path
import platform
import subprocess

LOG = logging.getLogger('hookup.network_diagnostics')


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


def capture_network(directory, trace_id):
    """Runs in a worker thread. Failure cannot stop ICE or SSH connections."""
    result = {'schema': 1, 'trace_id': trace_id,
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
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / ('network-' + trace_id + '.json')
    # Atomic replace prevents export while a partial JSON snapshot is being written.
    temporary = destination.with_suffix('.tmp')
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(destination)
    LOG.info('network_snapshot trace=%s file=%s interfaces=%d route_status=%s nat_type=unknown',
             trace_id, destination.name, len(result['interfaces']), result.get('route_probe_exit', result.get('route_error')))
    return result

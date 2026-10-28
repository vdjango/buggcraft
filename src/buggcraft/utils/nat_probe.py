"""Bounded STUN evidence. A NAT observation is never a peer connectivity test.

Only numeric, explicitly configured STUN endpoints are probed. Reports contain
addresses and transport facts, never SDP passwords, access codes or payloads.
"""
import ipaddress
import secrets
import socket
import struct
import time

COOKIE = 0x2112A442
DEFAULT_SERVERS = (('81.68.225.236', 3334), ('43.241.50.19', 13331))


def parse_binding(packet, transaction):
    if len(packet) < 20:
        raise ValueError('short-header')
    kind, size, cookie = struct.unpack('!HHI', packet[:8])
    if cookie != COOKIE or packet[8:20] != transaction:
        raise ValueError('wrong-transaction')
    if kind != 0x101 or size % 4 or size + 20 != len(packet):
        raise ValueError('invalid-binding-response')
    result = {}
    offset = 20
    while offset < len(packet):
        if offset + 4 > len(packet):
            raise ValueError('truncated-attribute')
        kind, size = struct.unpack('!HH', packet[offset:offset + 4])
        value = packet[offset + 4:offset + 4 + size]
        if len(value) != size or offset + 4 + ((size + 3) // 4) * 4 > len(packet):
            raise ValueError('truncated-attribute')
        if kind in (0x20, 1, 0x802b, 0x802c):
            if size not in (8, 20) or value[0] != 0 or value[1] not in (1, 2):
                raise ValueError('invalid-address')
            family = 4 if value[1] == 1 else 6
            if size != (8 if family == 4 else 20):
                raise ValueError('invalid-address-size')
            port = struct.unpack('!H', value[2:4])[0]
            packed = value[4:]
            if kind == 0x20:
                port ^= COOKIE >> 16
                mask = struct.pack('!I', COOKIE) + transaction
                packed = bytes(a ^ b for a, b in zip(packed, mask))
            address = str(ipaddress.ip_address(packed))
            result[{0x20: 'mapped', 1: 'legacy_mapped', 0x802b: 'origin',
                    0x802c: 'other'}[kind]] = [address, port]
        offset += 4 + ((size + 3) // 4) * 4
    if 'mapped' not in result:
        raise ValueError('missing-xor-mapped-address')
    return result


def binding(sock, endpoint, *, timeout=0.6, attempts=2, change=None, deadline=None,
            expected_source=None):
    """Unconnected socket preserves mapping across targets and alternate replies."""
    transaction = secrets.token_bytes(12)
    attrs = b'' if change is None else struct.pack('!HHI', 3, 4, change)
    request = struct.pack('!HHI', 1, len(attrs), COOKIE) + transaction + attrs
    result = {'target': list(endpoint), 'change_request': change, 'attempts': 0,
              'status': 'timeout', 'invalid_responses': 0}
    started = time.monotonic()
    for _ in range(attempts):
        if deadline is not None and time.monotonic() >= deadline:
            result['status'] = 'budget-exhausted'
            break
        result['attempts'] += 1
        try:
            sock.sendto(request, endpoint)
            until = time.monotonic() + timeout
            if deadline is not None:
                until = min(until, deadline)
            while time.monotonic() < until:
                sock.settimeout(max(0.001, until - time.monotonic()))
                packet, source = sock.recvfrom(2048)
                if tuple(source[:2]) != tuple(expected_source or endpoint):
                    result['invalid_responses'] += 1
                    continue
                try:
                    attributes = parse_binding(packet, transaction)
                except ValueError:
                    result['invalid_responses'] += 1
                    continue
                result.update(status='ok', response_source=list(source[:2]),
                              rtt_ms=round((time.monotonic() - started) * 1000, 1),
                              **attributes)
                return result
        except socket.timeout:
            continue
        except OSError as exc:
            result.update(status='socket-error', error=type(exc).__name__,
                          error_code=getattr(exc, 'winerror', None) or exc.errno)
            break
    result['elapsed_ms'] = round((time.monotonic() - started) * 1000, 1)
    return result


def classify_mapping(observations):
    good = [row for row in observations if row.get('status') == 'ok']
    ips = {row['target'][0] for row in good}
    if len(ips) < 2:
        return {'behavior': 'unknown', 'reason': 'need-two-distinct-server-ips'}
    maps = {tuple(row['mapped']) for row in good}
    if len(maps) == 1:
        return {'behavior': 'endpoint-independent', 'confidence': 'observed',
                'reason': 'same-socket-same-mapping-across-distinct-server-ips'}
    # Different external IPs can also mean multiple WAN exits. Do not label that
    # symmetric NAT, or distinguish ADM/APDM without controlled destination ports.
    if len({row['mapped'][0] for row in good}) > 1:
        return {'behavior': 'destination-dependent-or-multiple-egress',
                'confidence': 'observed', 'reason': 'public-ip-changed'}
    return {'behavior': 'destination-dependent', 'confidence': 'observed',
            'reason': 'mapped-port-changed-on-same-socket',
            'subtype': 'unknown-without-controlled-address-and-port-tests'}


def _endpoint(item, allow_private):
    host, port = item
    address = ipaddress.ip_address(host)
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('invalid-port')
    if address.is_unspecified or address.is_multicast:
        raise ValueError('unusable-address')
    if not allow_private and not address.is_global:
        raise ValueError('non-public-server')
    return str(address), port


def probe_network(servers=None, *, timeout=0.6, budget=8.0, allow_private=False,
                  filtering_server=None, ipv6_servers=None):
    """Run on a worker. No uploads; all operations share one wall-clock budget.

    filtering_server must be a trusted numeric RFC 5780 endpoint. If it lacks a
    second public IP, full filtering classification stays unknown; a validated
    before/after alternate-port test can still observe port-dependent filtering.
    A timeout alone never establishes a filtering class. Alternate endpoints may
    not redirect probes to a LAN.
    """
    deadline = time.monotonic() + max(0.1, min(float(budget), 20.0))
    result = {'schema': 1, 'method': 'stun-same-socket-v1', 'ipv4': {
        'udp': 'unknown', 'observations': [], 'mapping': {'behavior': 'unknown'},
        'filtering': {'behavior': 'unknown', 'reason': 'no-rfc5780-server-configured'}},
        'ipv6': {'udp': 'not-tested', 'observations': []},
        'p2p': {'status': 'not-tested', 'reason': 'requires-both-peers-ice-and-data-channel',
                'ipv4_verified': False, 'ipv6_verified': False}}
    endpoints = []
    for item in (DEFAULT_SERVERS if servers is None else servers):
        try:
            target = _endpoint(item, allow_private)
            if ipaddress.ip_address(target[0]).version != 4:
                continue
            if target not in endpoints:
                endpoints.append(target)
        except (ValueError, TypeError):
            continue
        if len(endpoints) >= 4:
            break
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind(('0.0.0.0', 0))
            result['ipv4']['local_port'] = sock.getsockname()[1]
            for target in endpoints:
                result['ipv4']['observations'].append(binding(
                    sock, target, timeout=timeout, deadline=deadline))
            observations = result['ipv4']['observations']
            result['ipv4']['udp'] = 'reachable' if any(
                row['status'] == 'ok' for row in observations) else 'unconfirmed'
            result['ipv4']['mapping'] = classify_mapping(observations)
    except OSError as exc:
        result['ipv4']['error'] = type(exc).__name__
    if filtering_server is not None and time.monotonic() < deadline:
        try:
            result['ipv4']['filtering'] = probe_filtering(
                _endpoint(filtering_server, allow_private), timeout=timeout,
                deadline=deadline, allow_private=allow_private)
        except (ValueError, OSError, TypeError) as exc:
            result['ipv4']['filtering'] = {'behavior': 'unknown',
                                         'reason': type(exc).__name__}
    for item in (ipv6_servers or ()):
        if time.monotonic() >= deadline:
            break
        try:
            target = _endpoint(item, allow_private)
            if ipaddress.ip_address(target[0]).version != 6:
                continue
            with socket.socket(socket.AF_INET6, socket.SOCK_DGRAM) as sock:
                sock.bind(('::', 0))
                row = binding(sock, target, timeout=timeout, deadline=deadline)
                result['ipv6']['observations'].append(row)
        except (ValueError, OSError, TypeError) as exc:
            result['ipv6']['observations'].append({'status': 'socket-error',
                                                 'error': type(exc).__name__})
        if len(result['ipv6']['observations']) >= 2:
            break
    if result['ipv6']['observations']:
        result['ipv6']['udp'] = 'reachable' if any(
            row['status'] == 'ok' for row in result['ipv6']['observations']) else 'unconfirmed'
    result['elapsed_ms'] = round((max(0.1, min(float(budget), 20.0)) -
                                 (deadline - time.monotonic())) * 1000, 1)
    return result


def probe_filtering(primary, *, timeout, deadline, allow_private=False):
    """Fresh socket: never contact alternate IP/port before CHANGE-REQUEST."""
    result = {'behavior': 'unknown', 'observations': []}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(('0.0.0.0', 0))
        first = binding(sock, primary, timeout=timeout, deadline=deadline)
        result['observations'].append(first)
        if first['status'] != 'ok':
            result['reason'] = 'primary-binding-unavailable'
            return result
        try:
            other = _endpoint(first['other'], allow_private)
        except (KeyError, ValueError, TypeError):
            result['reason'] = 'server-missing-valid-other-address'
            return result
        if other[1] == primary[1]:
            result['reason'] = 'server-needs-distinct-alternate-port'
            return result
        if other[0] == primary[0]:
            # A one-IP server cannot distinguish EIF from ADF, but a fresh
            # socket plus successful before/after controls can observe APDF.
            before = binding(sock, primary, timeout=timeout, deadline=deadline,
                             change=2, expected_source=other)
            direct = binding(sock, other, timeout=timeout, deadline=deadline)
            after = binding(sock, primary, timeout=timeout, deadline=deadline,
                            change=2, expected_source=other)
            result['observations'].extend((before, direct, after))
            if (before['status'] == 'timeout' and direct['status'] == 'ok'
                    and after['status'] == 'ok' and
                    first['mapped'] == direct['mapped'] == after['mapped']):
                result.update(behavior='address-and-port-dependent', confidence='observed',
                              reason='alternate-port-blocked-until-outbound-contact')
            else:
                result['reason'] = 'one-ip-server-cannot-confirm-full-filtering-class'
            result['scope'] = 'combined-path-including-host-firewall-and-nat'
            result['full_rfc5780'] = False
            return result
        changed = binding(sock, primary, timeout=timeout, deadline=deadline,
                          change=6, expected_source=other)
        result['observations'].append(changed)
        if changed['status'] == 'ok':
            result.update(behavior='endpoint-independent', confidence='observed')
            return result
        port_only = (primary[0], other[1])
        changed_port = binding(sock, primary, timeout=timeout, deadline=deadline,
                               change=2, expected_source=port_only)
        result['observations'].append(changed_port)
        # Validate server capability after opening both alternate mappings. Only
        # an actual response to each CHANGE-REQUEST makes earlier timeouts useful.
        for endpoint in (other, port_only):
            result['observations'].append(binding(
                sock, endpoint, timeout=timeout, deadline=deadline))
        control_ip = binding(sock, primary, timeout=timeout, deadline=deadline,
                             change=6, expected_source=other)
        control_port = binding(sock, primary, timeout=timeout, deadline=deadline,
                               change=2, expected_source=port_only)
        result['observations'].extend((control_ip, control_port))
        if control_ip['status'] != 'ok' or control_port['status'] != 'ok':
            result['reason'] = 'change-request-support-or-reachability-unconfirmed'
        elif any(row['status'] not in ('ok', 'timeout') for row in
                 (changed, changed_port)):
            result['reason'] = 'incomplete-filtering-tests'
        elif changed_port['status'] == 'ok':
            result.update(behavior='address-dependent', confidence='observed')
        else:
            result.update(behavior='address-and-port-dependent', confidence='observed')
        result['scope'] = 'combined-path-including-host-firewall-and-nat'
        return result

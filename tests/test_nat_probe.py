"""STUN behavior discovery is bounded, transaction-checked, and fail-closed."""
import ipaddress
import socket
import struct
import sys
import time
import select
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/buggcraft'))
from utils.nat_probe import COOKIE, binding, classify_mapping, parse_binding, probe_network, probe_filtering


def response(transaction, *, mapped=('198.51.100.2', 5000), other=None,
             origin=None, legacy=False):
    attributes = bytearray()

    def address(kind, endpoint, xor=False):
        packed = ipaddress.ip_address(endpoint[0]).packed
        port = endpoint[1] ^ (COOKIE >> 16) if xor else endpoint[1]
        if xor:
            mask = struct.pack('!I', COOKIE) + transaction
            packed = bytes(a ^ b for a, b in zip(packed, mask))
        family = 1 if len(packed) == 4 else 2
        value = struct.pack('!BBH', 0, family, port) + packed
        attributes.extend(struct.pack('!HH', kind, len(value)) + value)
        attributes.extend(b'\0' * (-len(value) % 4))

    address(0x20, mapped, True)
    if legacy:
        address(1, mapped)
    if origin:
        address(0x802b, origin)
    if other:
        address(0x802c, other)
    return struct.pack('!HHI12s', 0x101, len(attributes), COOKIE, transaction) + attributes


class NatProbeTests(unittest.TestCase):
    def test_parses_ipv4_xor_and_rfc5780_capabilities(self):
        tx = b'abcdefghijkl'
        self.assertEqual(parse_binding(response(tx, other=('198.51.100.3', 4001),
            origin=('198.51.100.2', 3478), legacy=True), tx), {
            'mapped': ['198.51.100.2', 5000],
            'legacy_mapped': ['198.51.100.2', 5000],
            'origin': ['198.51.100.2', 3478], 'other': ['198.51.100.3', 4001]})

    def test_parses_ipv6_xor_mapped_address(self):
        tx = b'abcdefghijkl'
        endpoint = ('2001:db8::2', 5001)
        self.assertEqual(parse_binding(response(tx, mapped=endpoint), tx)['mapped'],
                         [endpoint[0], endpoint[1]])

    def test_rejects_unmatched_transaction_and_trailing_data(self):
        packet = response(b'abcdefghijkl')
        with self.assertRaisesRegex(ValueError, 'wrong-transaction'):
            parse_binding(packet, b'XXXXXXXXXXXX')
        with self.assertRaisesRegex(ValueError, 'invalid-binding-response'):
            parse_binding(packet + b'\0\0\0\0', b'abcdefghijkl')

    def test_mapping_needs_multiple_reachable_distinct_public_servers(self):
        self.assertEqual(classify_mapping([])['behavior'], 'unknown')
        self.assertEqual(classify_mapping([
            {'status': 'ok', 'target': ['192.0.2.2', 3333], 'mapped': ['198.51.100.1', 5000]},
            {'status': 'ok', 'target': ['192.0.2.2', 3334], 'mapped': ['198.51.100.1', 5000]},
        ])['reason'], 'need-two-distinct-server-ips')

    def test_mapping_does_not_call_public_ip_changes_symmetric_nat(self):
        result = classify_mapping([
            {'status': 'ok', 'target': ['8.8.8.8', 3478], 'mapped': ['198.51.100.1', 5000]},
            {'status': 'ok', 'target': ['1.1.1.1', 3478], 'mapped': ['198.51.100.2', 6000]},
        ])
        self.assertEqual(result['behavior'], 'destination-dependent-or-multiple-egress')
        self.assertNotIn('symmetric', result['behavior'])

    def test_no_filtering_classification_without_another_ip_and_port(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
            server.bind(('127.0.0.1', 0))
            endpoint = ('127.0.0.1', server.getsockname()[1])
            ready = __import__('threading').Event()

            def serve():
                ready.set()
                packet, source = server.recvfrom(256)
                transaction = packet[8:20]
                server.sendto(response(transaction, other=endpoint), source)

            import threading
            worker = threading.Thread(target=serve, daemon=True)
            worker.start()
            ready.wait(1)
            result = probe_filtering(endpoint, timeout=0.12,
                                     deadline=time.monotonic() + 0.8, allow_private=True)
            worker.join(1)
        self.assertEqual(result['behavior'], 'unknown')
        self.assertEqual(result['reason'], 'server-needs-distinct-alternate-port')

    def test_probe_respects_deadline_with_unreachable_servers(self):
        started = time.monotonic()
        result = probe_network([('192.0.2.1', 9), ('192.0.2.2', 9),
                                ('192.0.2.3', 9), ('192.0.2.4', 9)],
                               timeout=1, budget=0.15, allow_private=True)
        self.assertLess(time.monotonic() - started, 0.5)
        self.assertIn(result['ipv4']['udp'], ('unconfirmed', 'reachable'))
        self.assertFalse(result['p2p']['ipv4_verified'])

    def test_alternate_port_filtering_requires_before_and_after_controls(self):
        for mode, expected in (('blocked-until-contact', 'address-and-port-dependent'),
                               ('ignored-change-request', 'unknown'), ('always-allowed', 'unknown')):
            with self.subTest(mode=mode), socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as primary, \
                    socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as alternate:
                primary.bind(('127.0.0.1', 0)); alternate.bind(('127.0.0.1', 0))
                first, other = primary.getsockname(), alternate.getsockname()
                stop = threading.Event()
                contacted = set()
                def serve():
                    while not stop.is_set():
                        ready, _, _ = select.select([primary, alternate], [], [], .02)
                        for receiver in ready:
                            packet, source = receiver.recvfrom(256)
                            change = len(packet) > 20
                            if receiver is alternate:
                                contacted.add(source)
                            if change and mode == 'blocked-until-contact' and source not in contacted:
                                continue
                            sender = (primary if mode == 'ignored-change-request' else alternate) if change else receiver
                            sender.sendto(response(packet[8:20], mapped=source, other=other), source)
                worker = threading.Thread(target=serve, daemon=True); worker.start()
                try:
                    result = probe_filtering(first, timeout=.04, deadline=time.monotonic() + .8, allow_private=True)
                finally:
                    stop.set(); worker.join(1)
                self.assertEqual(result['behavior'], expected, result)
                self.assertFalse(result['full_rfc5780'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
